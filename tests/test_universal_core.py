"""
Tests für den strukturunabhängigen Kern der universellen Kodierung (universal_core)

Überprüft (reines Python, ohne Datenbank):
- Stack: Validierung, Hilfskonstruktor, Kennzahlen, Tupelfolge, Projektion
- Paarmengen (linear/zyklisch), aktive Schichten, beide Enthaltensrelationen
- compare_stacks: alle sechs Ergebnisse, Schichtauswahl und Fehlerfälle
- Matrixstapel als Spezialfall, inklusive Abgleich mit multiomics_python
"""

import dataclasses
import random

import pytest

from backend import multiomics_python
from backend.universal_core import (
    MODES,
    Stack,
    compare_stacks,
    contained,
    contained_coherent,
    contained_independent,
    cyclic_pairs,
    linear_pairs,
    matrices_from_stack,
    resolve_layers,
    stack_from_matrices,
    validate_matrices,
)

pytestmark = pytest.mark.unit

# Zwei Schichten, an derselben Position (kohärent) bzw. an verschiedenen (unabhängig) enthalten
TWO_LAYER_QUERY = Stack.of([[{1}, {2}], [{3}, {4}]])
TWO_LAYER_SHIFTED = Stack.of([[{1}, {2}, {9}], [{9}, {3}, {4}]])
TWO_LAYER_ALIGNED = Stack.of([[{1}, {2}, {9}], [{3}, {4}, {9}]])


class TestStack:
    def test_of_builds_frozensets_and_to_lists_sorts(self):
        stack = Stack.of([[[3, 1], [2]], [[], [5, 4]]])
        assert stack.layers[0][0] == frozenset({1, 3})
        assert stack.to_lists() == [[[1, 3], [2]], [[], [4, 5]]]

    def test_to_lists_is_inverse_of_of(self):
        lists = [[[1, 2], [3]], [[4], []]]
        assert Stack.of(lists).to_lists() == lists

    def test_properties(self):
        stack = Stack.of([[{1, 2}, {3}, set()], [{4}, set(), {5, 6, 7}]])
        assert stack.length == 3
        assert stack.layer_count == 2
        assert stack.occupancy == 7

    def test_tuples_zip_layers_per_position(self):
        stack = Stack.of([[{1}, {2}], [{3}, {4}]])
        assert stack.tuples() == ((frozenset({1}), frozenset({3})), (frozenset({2}), frozenset({4})))

    def test_project_all_layers_returns_equal_stack(self):
        assert TWO_LAYER_QUERY.project(None) == TWO_LAYER_QUERY

    def test_project_subset_sorts_indices(self):
        stack = Stack.of([[{1}], [{2}], [{3}]])
        assert stack.project([2, 0]).to_lists() == [[[1]], [[3]]]

    def test_project_invalid_layers(self):
        with pytest.raises(ValueError, match="at least one active layer"):
            TWO_LAYER_QUERY.project([])
        with pytest.raises(ValueError, match="layer indices"):
            TWO_LAYER_QUERY.project([2])

    def test_stack_is_hashable_and_frozen(self):
        assert hash(TWO_LAYER_QUERY) == hash(Stack.of([[{1}, {2}], [{3}, {4}]]))
        with pytest.raises(dataclasses.FrozenInstanceError):
            TWO_LAYER_QUERY.layers = ()

    def test_requires_at_least_one_layer(self):
        with pytest.raises(ValueError, match="at least one layer"):
            Stack(())

    def test_layers_must_have_equal_length(self):
        with pytest.raises(ValueError, match="layer 1 has length 1, expected 2"):
            Stack.of([[{1}, {2}], [{3}]])

    def test_components_must_be_frozensets(self):
        with pytest.raises(ValueError, match="must be frozensets"):
            Stack((({1}, frozenset({2})),))

    @pytest.mark.parametrize("member", [-1, "a", 1.5])
    def test_members_must_be_non_negative_integers(self, member):
        with pytest.raises(ValueError, match="non-negative integers"):
            Stack(((frozenset({member}),),))

    def test_empty_layers_are_allowed(self):
        assert Stack.of([[]]).length == 0


class TestResolveLayers:
    def test_none_means_all_layers(self):
        assert resolve_layers(3, None) == (0, 1, 2)

    def test_sorted_and_deduplicated(self):
        assert resolve_layers(4, [3, 1, 3, 1]) == (1, 3)

    def test_accepts_any_iterable(self):
        assert resolve_layers(3, iter([2, 0])) == (0, 2)

    def test_empty_selection_rejected(self):
        with pytest.raises(ValueError, match="at least one active layer"):
            resolve_layers(3, [])

    @pytest.mark.parametrize("layers", [[-1], [3], [0, 5]])
    def test_out_of_range_rejected(self, layers):
        with pytest.raises(ValueError, match=r"layer indices must be in 0\.\.2"):
            resolve_layers(3, layers)


class TestPairs:
    def test_linear_pairs(self):
        assert linear_pairs([]) == set()
        assert linear_pairs(["a"]) == set()
        assert linear_pairs(["a", "b", "c"]) == {("a", "b"), ("b", "c")}

    def test_cyclic_pairs(self):
        assert cyclic_pairs([]) == set()
        assert cyclic_pairs(["a"]) == set()
        assert cyclic_pairs(["a", "b"]) == {("a", "b"), ("b", "a")}
        assert cyclic_pairs(["a", "b", "c"]) == {("a", "b"), ("b", "c"), ("c", "a")}

    def test_linear_pairs_are_cyclic_pairs(self):
        sequence = [4, 8, 15, 16, 23]
        assert linear_pairs(sequence) <= cyclic_pairs(sequence)

    def test_repeated_elements_collapse(self):
        assert linear_pairs([1, 1, 1]) == {(1, 1)}
        assert cyclic_pairs([1, 1, 1]) == {(1, 1)}

    def test_works_on_components(self):
        sequence = [frozenset({1}), frozenset({2, 3})]
        assert linear_pairs(sequence) == {(frozenset({1}), frozenset({2, 3}))}


class TestContainedIndependent:
    def test_each_layer_may_use_its_own_position(self):
        assert contained_independent(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED)

    def test_layer_without_common_pair_fails(self):
        other = Stack.of([[{1}, {2}, {9}], [{7}, {8}, {9}]])
        assert not contained_independent(TWO_LAYER_QUERY, other)

    def test_active_layers_restrict_the_check(self):
        other = Stack.of([[{1}, {2}, {9}], [{7}, {8}, {9}]])
        assert contained_independent(TWO_LAYER_QUERY, other, [0])
        assert not contained_independent(TWO_LAYER_QUERY, other, [1])

    def test_longer_query_is_never_contained(self):
        assert not contained_independent(TWO_LAYER_SHIFTED, TWO_LAYER_QUERY)

    def test_single_column_has_no_pairs(self):
        single = Stack.of([[{1}]])
        assert not contained_independent(single, single)

    def test_pair_may_close_the_cycle(self):
        query = Stack.of([[{3}, {1}]])
        stored = Stack.of([[{1}, {2}, {3}]])
        assert contained_independent(query, stored)

    def test_layer_count_must_match(self):
        with pytest.raises(ValueError, match="same number of layers"):
            contained_independent(TWO_LAYER_QUERY, Stack.of([[{1}, {2}]]))

    def test_invalid_layer_selection(self):
        with pytest.raises(ValueError, match="layer indices"):
            contained_independent(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, [4])


class TestContainedCoherent:
    def test_same_position_in_all_layers(self):
        assert contained_coherent(TWO_LAYER_QUERY, TWO_LAYER_ALIGNED)

    def test_shifted_layers_are_not_coherent(self):
        assert not contained_coherent(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED)

    def test_active_layers_restrict_the_check(self):
        assert contained_coherent(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, [0])
        assert contained_coherent(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, [1])

    def test_longer_query_is_never_contained(self):
        assert not contained_coherent(TWO_LAYER_ALIGNED, TWO_LAYER_QUERY)

    def test_single_column_has_no_pairs(self):
        single = Stack.of([[{1}], [{2}]])
        assert not contained_coherent(single, single)

    def test_layer_count_must_match(self):
        with pytest.raises(ValueError, match="same number of layers"):
            contained_coherent(TWO_LAYER_QUERY, Stack.of([[{1}, {2}]]))

    def test_coherent_implies_independent(self):
        assert contained_coherent(TWO_LAYER_QUERY, TWO_LAYER_ALIGNED)
        assert contained_independent(TWO_LAYER_QUERY, TWO_LAYER_ALIGNED)


class TestContained:
    def test_dispatches_on_mode(self):
        assert contained(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "independent")
        assert not contained(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent")

    def test_default_mode_is_coherent(self):
        assert not contained(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED)

    def test_layers_are_passed_on(self):
        assert contained(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent", [0])
        assert contained(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "independent", [1])

    def test_unknown_mode(self):
        with pytest.raises(ValueError, match="unknown mode 'weird'"):
            contained(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "weird")

    def test_modes_constant(self):
        assert MODES == ("coherent", "independent")


class TestCompareStacks:
    def test_identical(self):
        assert compare_stacks(TWO_LAYER_QUERY, TWO_LAYER_QUERY) == "IDENTICAL"

    def test_identical_single_column_stacks(self):
        single = Stack.of([[{1}]])
        assert compare_stacks(single, single, "independent") == "IDENTICAL"

    def test_query_contained_keeps_b(self):
        a = Stack.of([[{1}, {2}]])
        b = Stack.of([[{1}, {2}, {3}]])
        assert compare_stacks(a, b) == "KEEP_B"

    def test_stored_contained_keeps_a(self):
        a = Stack.of([[{1}, {2}, {3}]])
        b = Stack.of([[{1}, {2}]])
        assert compare_stacks(a, b) == "KEEP_A"

    def test_unrelated_keeps_both(self):
        a = Stack.of([[{1}, {2}]])
        b = Stack.of([[{3}, {4}]])
        assert compare_stacks(a, b) == "KEEP_BOTH"

    def test_mutual_containment_prefers_a_on_tie(self):
        a = Stack.of([[{1}, {2}, {3}]])
        b = Stack.of([[{1}, {2}, {4}]])
        assert compare_stacks(a, b) == "EQUAL_KEEP_A"

    def test_mutual_containment_prefers_larger_occupancy_a(self):
        a = Stack.of([[{1}, {2}, {3, 5}]])
        b = Stack.of([[{1}, {2}, {3}]])
        assert compare_stacks(a, b) == "EQUAL_KEEP_A"

    def test_mutual_containment_prefers_larger_occupancy_b(self):
        a = Stack.of([[{1}, {2}, {3}]])
        b = Stack.of([[{1}, {2}, {3, 5}]])
        assert compare_stacks(a, b) == "EQUAL_KEEP_B"

    def test_mode_changes_result(self):
        assert compare_stacks(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "independent") == "KEEP_B"
        assert compare_stacks(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent") == "KEEP_BOTH"

    def test_default_mode_is_coherent(self):
        assert compare_stacks(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED) == \
            compare_stacks(TWO_LAYER_QUERY, TWO_LAYER_SHIFTED, "coherent")

    def test_active_layers_project_before_comparing(self):
        a = Stack.of([[{1}, {2}], [{3}, {4}]])
        b = Stack.of([[{1}, {2}], [{7}, {8}]])
        assert compare_stacks(a, b, "coherent", [0]) == "IDENTICAL"
        assert compare_stacks(a, b, "coherent") == "KEEP_BOTH"

    def test_occupancy_tie_break_uses_active_layers_only(self):
        a = Stack.of([[{1}, {2}, {3}], [{1, 2, 3}, {4}, {5}]])
        b = Stack.of([[{1}, {2}, {4}], [{9}, {9}, {9}]])
        assert compare_stacks(a, b, "independent", [0]) == "EQUAL_KEEP_A"

    def test_unknown_mode(self):
        with pytest.raises(ValueError, match="unknown mode"):
            compare_stacks(TWO_LAYER_QUERY, TWO_LAYER_QUERY, "weird")

    def test_layer_count_must_match(self):
        with pytest.raises(ValueError, match="same number of layers"):
            compare_stacks(TWO_LAYER_QUERY, Stack.of([[{1}, {2}]]))

    def test_invalid_layer_selection(self):
        with pytest.raises(ValueError, match="layer indices"):
            compare_stacks(TWO_LAYER_QUERY, TWO_LAYER_QUERY, "coherent", [3])

    def test_swapping_arguments_mirrors_the_result(self):
        mirrored = {"KEEP_A": "KEEP_B", "KEEP_B": "KEEP_A", "KEEP_BOTH": "KEEP_BOTH",
                    "IDENTICAL": "IDENTICAL"}
        rng = random.Random(3)
        for _ in range(200):
            a = _random_stack(rng, rng.randint(2, 4), 2)
            b = _random_stack(rng, rng.randint(2, 4), 2)
            for mode in MODES:
                forward, backward = compare_stacks(a, b, mode), compare_stacks(b, a, mode)
                if forward in mirrored:
                    assert backward == mirrored[forward]
                else:
                    assert forward.startswith("EQUAL_") and backward.startswith("EQUAL_")


def _random_stack(rng, length, layer_count):
    return Stack.of([
        [{rng.randint(0, 3)} if rng.random() < 0.8 else set() for _ in range(length)]
        for _ in range(layer_count)
    ])


class TestValidateMatrices:
    def test_returns_size(self):
        assert validate_matrices([[[0, 1], [0, 0]], [[1, 1], [1, 1]]]) == 2

    def test_at_least_one_layer(self):
        with pytest.raises(ValueError, match="at least one layer"):
            validate_matrices([])

    def test_no_empty_matrices(self):
        with pytest.raises(ValueError, match="empty matrices"):
            validate_matrices([[]])

    def test_must_be_square(self):
        with pytest.raises(ValueError, match=r"layer 0 must be a square 2x2"):
            validate_matrices([[[0, 1, 0], [0, 0, 1]]])
        with pytest.raises(ValueError, match=r"layer 0 must be a square 2x2"):
            validate_matrices([[[0, 1], [0]]])

    def test_layers_must_have_equal_size(self):
        with pytest.raises(ValueError, match=r"layer 1 must be a square 2x2"):
            validate_matrices([[[0, 1], [0, 0]], [[0]]])

    def test_only_zero_and_one(self):
        with pytest.raises(ValueError, match="only 0 and 1"):
            validate_matrices([[[0, 2], [0, 0]]])


class TestMatrixStacks:
    CHAIN = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
    RING = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]

    def test_components_are_in_neighbourhoods(self):
        stack = stack_from_matrices([self.CHAIN])
        assert stack.to_lists() == [[[], [0], [1]]]

    def test_two_layers(self):
        stack = stack_from_matrices([self.CHAIN, self.RING])
        assert stack.layer_count == 2 and stack.length == 3
        assert stack.to_lists()[1] == [[2], [0], [1]]

    def test_matches_row_components_bit_pattern(self):
        matrix = [[0, 1, 1], [1, 0, 0], [1, 1, 0]]
        stack = stack_from_matrices([matrix])
        patterns = [sum(1 << i for i in component) for component in stack.layers[0]]
        assert patterns == list(multiomics_python.row_components(matrix))

    def test_round_trip(self):
        matrices = [self.CHAIN, self.RING]
        assert matrices_from_stack(stack_from_matrices(matrices)) == matrices

    def test_no_limit_of_63_nodes(self):
        n = 70
        matrix = [[1 if j == i + 1 else 0 for j in range(n)] for i in range(n)]
        stack = stack_from_matrices([matrix])
        assert stack.length == n
        assert matrices_from_stack(stack) == [matrix]

    def test_stack_from_invalid_matrices(self):
        with pytest.raises(ValueError, match="only 0 and 1"):
            stack_from_matrices([[[0, 3], [0, 0]]])

    def test_matrices_from_stack_needs_columns(self):
        with pytest.raises(ValueError, match="length 0"):
            matrices_from_stack(Stack.of([[]]))

    def test_matrices_from_stack_element_outside_range(self):
        with pytest.raises(ValueError, match="element 5 is outside 0..1"):
            matrices_from_stack(Stack.of([[[5], []]]))


class TestAgreementWithMultiOmicsPython:
    """Auf Matrixstapeln liefert der Kern dieselben Ergebnisse wie multiomics_python."""

    @pytest.mark.parametrize("mode", MODES)
    def test_random_stacks(self, mode):
        rng = random.Random(2026)
        seen = set()
        for _ in range(400):
            layer_count = rng.randint(1, 3)
            base = [_random_matrix(rng, 4) for _ in range(layer_count)]
            first = base if rng.random() < 0.5 else [_mutate(rng, m) for m in base]
            size = rng.randint(2, 5)
            second = [_mutate(rng, _resize(m, size)) for m in base]
            expected = multiomics_python.compare_layered(first, second, mode)
            actual = compare_stacks(stack_from_matrices(first), stack_from_matrices(second), mode)
            assert actual == expected
            seen.add(actual)
        assert {"IDENTICAL", "KEEP_A", "KEEP_B", "KEEP_BOTH"} <= seen


def _random_matrix(rng, n):
    return [[1 if rng.random() < 0.35 else 0 for _ in range(n)] for _ in range(n)]


def _mutate(rng, matrix):
    n = len(matrix)
    copy = [row[:] for row in matrix]
    if rng.random() < 0.5:
        i, j = rng.randrange(n), rng.randrange(n)
        copy[i][j] ^= 1
    return copy


def _resize(matrix, size):
    n = len(matrix)
    return [[matrix[i][j] if i < n and j < n else 0 for j in range(size)] for i in range(size)]
