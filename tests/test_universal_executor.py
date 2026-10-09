"""
Tests für die universellen Vergleiche im Subgraph Executor

Überprüft (immer Python, ohne CSUBGRAPH_LIB_PATH):
- Abbildung der Ergebnisse von universal_core auf die Gen-DB-Werte
- Einzelvergleiche in beiden Modi, mit Schichtauswahl und Fehlerbehandlung
- Parallele Verarbeitung vieler Kandidaten über den Prozess-Pool (Reihenfolge, Chunks)
- Übereinstimmung des Pool-Vergleichs mit der Indexsuche (Referenzfunktion)
"""

import random

import pytest

from backend import subgraph_executor, universal_core
from backend.subgraph_executor import (
    _compare_universal_to_query,
    _map_universal_result,
    compare_many_universal,
    execute_universal_comparison,
    reset_backend,
    shutdown_executor,
)
from backend.universal_core import MODES, Stack
from backend.universal_index import PairIndex

pytestmark = pytest.mark.unit

TWO_LAYER_QUERY = Stack.of([[{1}, {2}], [{3}, {4}]])
TWO_LAYER_SHIFTED = Stack.of([[{1}, {2}, {9}], [{9}, {3}, {4}]])


def single(*columns):
    return Stack.of([[set(column) for column in columns]])


@pytest.fixture(autouse=True)
def python_backend(monkeypatch):
    """Ohne csubgraph, Executor nach jedem Test beenden."""

    class _Config:
        csubgraph_lib_path = None
        subgraph_max_workers = 2

    monkeypatch.setattr(subgraph_executor, "_get_config_safe", lambda: _Config())
    reset_backend()
    yield
    shutdown_executor()
    reset_backend()


class TestMapUniversalResult:
    @pytest.mark.parametrize(
        "result, expected",
        [
            ("KEEP_A", "keep_A"),
            ("KEEP_B", "keep_B"),
            ("KEEP_BOTH", "keep_both"),
            ("EQUAL_KEEP_A", "equal_keep_A"),
            ("EQUAL_KEEP_B", "equal_keep_B"),
        ],
    )
    def test_names_are_translated(self, result, expected):
        stack = single({1}, {2})
        assert _map_universal_result(result, stack, stack, None) == (expected, None)

    def test_identical_keeps_a_when_it_has_at_least_the_occupancy(self):
        assert _map_universal_result("IDENTICAL", single({1}, {2}), single({1}, {2}), None) == \
            ("equal_keep_A", None)

    def test_identical_keeps_b_when_a_has_less_occupancy(self):
        # nur bei direktem Aufruf erreichbar: compare_stacks meldet IDENTICAL nur bei gleicher Belegung
        assert _map_universal_result("IDENTICAL", single({1}, {2}), single({1}, {2, 3}), None) == \
            ("equal_keep_B", None)

    def test_identical_compares_occupancy_on_active_layers(self):
        a = Stack.of([[{1}, {2}], [{3}, {4}]])
        b = Stack.of([[{1}, {2}], [{3, 5, 6}, {4}]])
        assert _map_universal_result("IDENTICAL", a, b, [0]) == ("equal_keep_A", None)
        assert _map_universal_result("IDENTICAL", a, b, [1]) == ("equal_keep_B", None)

    def test_unknown_result(self):
        stack = single({1}, {2})
        assert _map_universal_result("WAT", stack, stack, None) == \
            (None, "universal comparison returned unknown result: 'WAT'")


class TestExecuteUniversalComparison:
    def test_query_contained_in_candidate(self):
        assert execute_universal_comparison(single({1}, {2}), single({1}, {2}, {3})) == ("keep_B", None)

    def test_candidate_contained_in_query(self):
        assert execute_universal_comparison(single({1}, {2}, {3}), single({1}, {2})) == ("keep_A", None)

    def test_identical_stacks(self):
        assert execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_QUERY) == ("equal_keep_A", None)

    def test_mutual_containment_prefers_larger_occupancy(self):
        assert execute_universal_comparison(single({1}, {2}, {3}), single({1}, {2}, {3, 5})) == \
            ("equal_keep_B", None)
        assert execute_universal_comparison(single({1}, {2}, {3, 5}), single({1}, {2}, {3})) == \
            ("equal_keep_A", None)

    def test_no_relation(self):
        assert execute_universal_comparison(single({1}, {2}), single({3}, {4})) == ("keep_both", None)

    def test_mode_changes_result(self):
        assert execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "independent") == \
            ("keep_B", None)
        assert execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent") == \
            ("keep_both", None)

    def test_default_mode_is_coherent(self):
        assert execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED) == \
            execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent")

    def test_layer_selection(self):
        assert execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent", [0]) == \
            ("keep_B", None)

    def test_more_than_63_entities_are_supported(self):
        wide = Stack.of([[{i} for i in range(100)]])
        assert execute_universal_comparison(wide, wide) == ("equal_keep_A", None)

    def test_unknown_mode_is_reported_not_raised(self):
        result, error = execute_universal_comparison(single({1}, {2}), single({1}, {2}), "weird")
        assert result is None and error.startswith("Unexpected error:") and "unknown mode" in error

    def test_layer_count_mismatch_is_reported(self):
        result, error = execute_universal_comparison(TWO_LAYER_QUERY, single({1}, {2}))
        assert result is None and "same number of layers" in error

    def test_invalid_layer_selection_is_reported(self):
        result, error = execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_QUERY, "coherent", [5])
        assert result is None and "layer indices" in error

    def test_unexpected_error_is_returned(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("kaputt")

        monkeypatch.setattr(universal_core, "compare_stacks", _boom)
        assert execute_universal_comparison(single({1}, {2}), single({1}, {2})) == \
            (None, "Unexpected error: kaputt")

    def test_unknown_result_from_core(self, monkeypatch):
        monkeypatch.setattr(universal_core, "compare_stacks", lambda *args: "WAT")
        result, error = execute_universal_comparison(single({1}, {2}), single({1}, {2}))
        assert result is None and "unknown result" in error


class TestCompareUniversalToQuery:
    def test_is_the_single_comparison_with_positional_arguments(self):
        assert _compare_universal_to_query(
            TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "independent", None
        ) == execute_universal_comparison(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "independent")

    def test_passes_layers_on(self):
        assert _compare_universal_to_query(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent", [0]) == \
            ("keep_B", None)


class TestCompareManyUniversal:
    def test_empty_candidate_list(self):
        assert compare_many_universal(single({1}, {2}), []) == []

    def test_empty_list_does_not_start_the_pool(self):
        compare_many_universal(single({1}, {2}), [])
        assert subgraph_executor._executor is None

    def test_results_follow_the_candidate_order(self):
        candidates = [
            single({1}, {2}, {3}),   # keep_B
            single({7}, {8}),        # keep_both
            single({1}, {2}),        # equal_keep_A (gleiche Stapel)
            single({1}),             # keep_both (kein Paar)
        ]
        results = compare_many_universal(single({1}, {2}), candidates)
        assert results == [("keep_B", None), ("keep_both", None), ("equal_keep_A", None),
                           ("keep_both", None)]

    def test_mode_and_layers_reach_the_workers(self):
        candidates = [TWO_LAYER_SHIFTED]
        assert compare_many_universal(TWO_LAYER_QUERY, candidates, "independent") == [("keep_B", None)]
        assert compare_many_universal(TWO_LAYER_QUERY, candidates, "coherent") == [("keep_both", None)]
        assert compare_many_universal(TWO_LAYER_QUERY, candidates, "coherent", [1]) == [("keep_B", None)]

    @pytest.mark.parametrize("chunksize", [0, 1, 3, 1000])
    def test_chunk_size_does_not_change_the_results(self, chunksize):
        rng = random.Random(1)
        candidates = [_random_stack(rng) for _ in range(25)]
        query = _random_stack(rng)
        expected = [execute_universal_comparison(query, candidate) for candidate in candidates]
        assert compare_many_universal(query, candidates, chunksize=chunksize) == expected

    def test_errors_are_returned_per_candidate(self):
        candidates = [single({1}, {2}, {3}), TWO_LAYER_QUERY, single({1}, {2})]
        results = compare_many_universal(single({1}, {2}), candidates)
        assert results[0] == ("keep_B", None)
        assert results[1][0] is None and "same number of layers" in results[1][1]
        assert results[2] == ("equal_keep_A", None)

    @pytest.mark.parametrize("mode", MODES)
    def test_agrees_with_the_index_search(self, mode):
        rng = random.Random(f"index-{mode}")
        index = PairIndex(2)
        stacks = {f"k{number}": _random_stack(rng, 2) for number in range(40)}
        for key, stack in stacks.items():
            index.add(key, stack)
        found = 0
        for _ in range(10):
            query = _random_stack(rng, 2)
            decisions = compare_many_universal(query, list(stacks.values()), mode)
            accepted = [
                key for key, (decision, error) in zip(stacks, decisions)
                if error is None and decision in {"keep_B", "equal_keep_A", "equal_keep_B"}
            ]
            assert accepted == index.search(query, mode).keys
            found += len(accepted)
        assert found > 0


def _random_stack(rng, layer_count=1):
    length = rng.randint(2, 5)
    return Stack.of([
        [set() if rng.random() < 0.1 else {rng.randrange(3)} for _ in range(length)]
        for _ in range(layer_count)
    ])
