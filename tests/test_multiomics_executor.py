"""
Tests für die Multi-Omics-Vergleiche im Subgraph Executor

Überprüft (Python-Implementierung, ohne CSUBGRAPH_LIB_PATH):
- Einzelne Vergleiche von Schichtstapeln in beiden Modi
- Fehlerbehandlung (ungültige Stapel, Modus, unerwartete Fehler)
- Parallele Verarbeitung vieler Kandidaten über den Prozess-Pool
- Übereinstimmung mit dem Subgraph Algorithmus (Dependency) bei einer Schicht
"""

import random

import numpy as np
import pytest
from subgraph import Subgraph

from backend import multiomics_python, subgraph_executor
from backend.subgraph_executor import (
    compare_many_multiomics,
    execute_multiomics_comparison,
    execute_subgraph_comparison,
    reset_backend,
    shutdown_executor,
)

CHAIN_3 = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
CHAIN_4 = [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]
RING_4 = [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [1, 0, 0, 0]]
EMPTY_4 = [[0] * 4 for _ in range(4)]


def matrix(columns):
    n = len(columns)
    return [[(columns[j] >> i) & 1 for j in range(n)] for i in range(n)]


@pytest.fixture(autouse=True)
def python_backend(monkeypatch):
    """Ohne csubgraph: immer die Python-Implementierung, Executor nach jedem Test beenden."""

    class _Config:
        csubgraph_lib_path = None
        subgraph_max_workers = 2

    monkeypatch.setattr(subgraph_executor, "_get_config_safe", lambda: _Config())
    reset_backend()
    yield
    shutdown_executor()
    reset_backend()


class TestExecuteMultiOmicsComparison:
    def test_query_contained_in_candidate(self):
        assert execute_multiomics_comparison([CHAIN_3, CHAIN_3], [CHAIN_4, CHAIN_4]) == ("keep_B", None)

    def test_candidate_contained_in_query(self):
        assert execute_multiomics_comparison([CHAIN_4, CHAIN_4], [CHAIN_3, CHAIN_3]) == ("keep_A", None)

    def test_identical_stacks(self):
        result, error = execute_multiomics_comparison([CHAIN_4, RING_4], [CHAIN_4, RING_4])
        assert error is None and result == "equal_keep_A"

    def test_equal_stacks_prefer_a_and_more_edges_prefer_b(self):
        assert execute_multiomics_comparison([CHAIN_4, EMPTY_4], [CHAIN_4, EMPTY_4]) == ("equal_keep_A", None)
        # strukturell gleich (Zeilenkomponenten), aber B hat mehr Kanten: nur über Mutual-Fall erreichbar
        a = [matrix([1, 2, 0])]
        b = [matrix([1, 2, 7])]
        assert execute_multiomics_comparison(a, b) == ("equal_keep_B", None)

    def test_no_relation(self):
        assert execute_multiomics_comparison([matrix([1, 2, 3])], [matrix([2, 1, 0])]) == ("keep_both", None)

    def test_mode_changes_result(self):
        a = [matrix([1, 2, 3]), matrix([4, 5, 6])]
        b = [matrix([1, 2, 0]), matrix([0, 5, 6])]
        assert execute_multiomics_comparison(a, b, "independent")[0] != \
            execute_multiomics_comparison(a, b, "coherent")[0]
        assert execute_multiomics_comparison(a, b, "coherent") == ("keep_both", None)

    def test_default_mode_is_coherent(self):
        a = [matrix([1, 2, 3]), matrix([4, 5, 6])]
        b = [matrix([1, 2, 0]), matrix([0, 5, 6])]
        assert execute_multiomics_comparison(a, b) == execute_multiomics_comparison(a, b, "coherent")

    def test_unknown_mode(self):
        result, error = execute_multiomics_comparison([CHAIN_3], [CHAIN_4], "weird")
        assert result is None and "Invalid mode" in error

    @pytest.mark.parametrize(
        "a, b, text",
        [
            ([], [CHAIN_4], "Invalid layer stack: layers_a"),
            ([CHAIN_4], [], "Invalid layer stack: layers_b"),
            ([[[0, 1]]], [CHAIN_4], "Invalid layer stack: layers_a"),
            (CHAIN_3, [CHAIN_4], "Invalid layer stack: layers_a"),
            ([[[]]], [CHAIN_4], "Invalid layer stack: layers_a"),
            ([CHAIN_3], [CHAIN_4, CHAIN_4], "layer counts differ"),
        ],
    )
    def test_invalid_stacks(self, a, b, text):
        result, error = execute_multiomics_comparison(a, b)
        assert result is None and text in error

    def test_non_binary_matrix_reports_error(self):
        result, error = execute_multiomics_comparison([[[0, 2], [0, 0]]], [CHAIN_4])
        assert result is None and "only 0 and 1" in error

    def test_too_many_nodes_reports_error(self):
        big = np.zeros((64, 64), dtype=int).tolist()
        result, error = execute_multiomics_comparison([big], [big])
        assert result is None and "at most 63" in error

    def test_unexpected_error_is_returned(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("kaputt")

        monkeypatch.setattr(multiomics_python, "compare_layered", _boom)
        assert execute_multiomics_comparison([CHAIN_3], [CHAIN_4]) == (None, "Unexpected error: kaputt")

    def test_unknown_result_from_implementation(self, monkeypatch):
        monkeypatch.setattr(multiomics_python, "compare_layered", lambda a, b, mode: "WAT")
        result, error = execute_multiomics_comparison([CHAIN_3], [CHAIN_4])
        assert result is None and "unknown result" in error

    def test_numpy_input_is_accepted(self):
        stack = np.array([CHAIN_3])
        assert execute_multiomics_comparison(stack, np.array([CHAIN_4])) == ("keep_B", None)


class TestSingleLayerAgreesWithSubgraphAlgorithm:
    """Bei einer Schicht liefert Multi-Omics dieselben Werte wie der Subgraph Algorithmus."""

    @pytest.mark.parametrize("mode", ["coherent", "independent"])
    def test_random_pairs(self, mode):
        rng = random.Random(11)
        algorithm = Subgraph()
        seen = set()
        for _ in range(150):
            na = rng.randint(2, 6)
            nb = na if rng.random() < 0.5 else rng.randint(2, 6)
            a = matrix([rng.choice([1, 2, 3, 5]) % (1 << na) for _ in range(na)])
            b = matrix([rng.choice([1, 2, 3, 5]) % (1 << nb) for _ in range(nb)])
            expected, _ = algorithm.compare_graphs(np.array(a), np.array(b))
            assert execute_multiomics_comparison([a], [b], mode) == (expected, None), (a, b)
            seen.add(expected)
        assert len(seen) >= 3

    @pytest.mark.parametrize(
        "a, b",
        [(CHAIN_3, CHAIN_4), (CHAIN_4, CHAIN_3), (CHAIN_4, CHAIN_4), (CHAIN_4, RING_4)],
    )
    def test_fixed_pairs(self, a, b):
        assert execute_multiomics_comparison([a], [b]) == execute_subgraph_comparison(a, b)


class TestCompareManyMultiOmics:
    def test_empty_candidates(self):
        assert compare_many_multiomics([CHAIN_3], []) == []

    def test_results_in_candidate_order(self):
        query = [CHAIN_3, CHAIN_3]
        candidates = [[CHAIN_4, CHAIN_4], [CHAIN_3, CHAIN_3], [matrix([2, 1, 0])] * 2]
        results = compare_many_multiomics(query, candidates)
        assert [r for r, _ in results] == ["keep_B", "equal_keep_A", "keep_both"]
        assert all(error is None for _, error in results)

    def test_matches_sequential_comparisons(self):
        rng = random.Random(5)
        query = [matrix([1, 2, 3]), matrix([4, 5, 6])]
        candidates = []
        for _ in range(40):
            n = rng.randint(3, 6)
            candidates.append([matrix([rng.choice([1, 2, 3, 4, 5, 6]) % (1 << n) for _ in range(n)])
                               for _ in range(2)])
        for mode in ("coherent", "independent"):
            parallel = compare_many_multiomics(query, candidates, mode, chunksize=7)
            sequential = [execute_multiomics_comparison(query, c, mode) for c in candidates]
            assert parallel == sequential

    def test_mode_is_applied_to_all_candidates(self):
        query = [matrix([1, 2, 3]), matrix([4, 5, 6])]
        candidate = [matrix([1, 2, 0]), matrix([0, 5, 6])]
        assert compare_many_multiomics(query, [candidate], "coherent") == [("keep_both", None)]
        assert compare_many_multiomics(query, [candidate], "independent")[0][0] != "keep_both"

    def test_errors_are_returned_per_candidate(self):
        results = compare_many_multiomics([CHAIN_3], [[CHAIN_4], [[[0, 1]]], [CHAIN_4, CHAIN_4]])
        assert results[0] == ("keep_B", None)
        assert results[1][0] is None and "Invalid layer stack" in results[1][1]
        assert results[2][0] is None and "layer counts differ" in results[2][1]

    def test_chunksize_below_one_is_treated_as_one(self):
        assert compare_many_multiomics([CHAIN_3], [[CHAIN_4]], chunksize=0) == [("keep_B", None)]
