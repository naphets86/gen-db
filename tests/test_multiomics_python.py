"""
Tests für die Python-Implementierung der Multi-Omics-Relation (multiomics_python)

Überprüft:
- Validierung von Schichtstapeln
- Zeilenkomponenten und Kantenzahl
- Enthaltensein im kohärenten und im unabhängigen Modus
- Alle Ergebniswerte von compare_layered
- Übereinstimmung mit einer Referenz, die wie csubgraph n Rotationen mit
  Longest-Common-Substring prüft (Bigramm-Charakterisierung), auf Zufallsdaten
"""

import random

import pytest

from backend import multiomics_python as mo


def matrix(columns):
    """Adjazenzmatrix aus Spaltenbitmustern: Bit i der Spalte j ist Eintrag [i][j]."""
    n = len(columns)
    return [[(columns[j] >> i) & 1 for j in range(n)] for i in range(n)]


def stack(*column_lists):
    return [matrix(columns) for columns in column_lists]


# ---------------------------------------------------------------------------
# Referenz: Rotationen + Longest Common Substring (wie SubgraphAlgorithm in C++)
# ---------------------------------------------------------------------------

def ref_lcs(a, b):
    best = 0
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                table[i][j] = table[i - 1][j - 1] + 1
                best = max(best, table[i][j])
    return best


def ref_rotate(seq, rotation):
    n = len(seq)
    return [seq[(i + n - rotation) % n] for i in range(n)]


def ref_contains_sequence(a, b):
    if len(b) < len(a):
        return False
    return any(ref_lcs(list(a), ref_rotate(list(b), r)) >= 2 for r in range(len(b)))


def ref_contains(stack_a, stack_b, mode):
    rows_a = [mo.row_components(layer) for layer in stack_a]
    rows_b = [mo.row_components(layer) for layer in stack_b]
    if mode == "independent":
        return all(ref_contains_sequence(a, b) for a, b in zip(rows_a, rows_b))
    return ref_contains_sequence(list(zip(*rows_a)), list(zip(*rows_b)))


def ref_compare(stack_a, stack_b, mode):
    rows_a = [mo.row_components(layer) for layer in stack_a]
    rows_b = [mo.row_components(layer) for layer in stack_b]
    if len(stack_a[0]) == len(stack_b[0]) and rows_a == rows_b:
        return "IDENTICAL"
    a_in_b = ref_contains(stack_a, stack_b, mode)
    b_in_a = ref_contains(stack_b, stack_a, mode)
    if a_in_b and not b_in_a:
        return "KEEP_B"
    if b_in_a and not a_in_b:
        return "KEEP_A"
    if a_in_b and b_in_a:
        return "EQUAL_KEEP_A" if mo.total_edges(stack_a) >= mo.total_edges(stack_b) else "EQUAL_KEEP_B"
    return "KEEP_BOTH"


def random_stack(rng, layers, n, alphabet):
    """Schichtstapel, dessen Spaltenmuster aus einem kleinen Alphabet stammen (viele Treffer)."""
    return stack(*[[rng.choice(alphabet) % (1 << n) for _ in range(n)] for _ in range(layers)])


CHAIN_3 = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
CHAIN_4 = [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]


class TestValidation:
    def test_valid_stack_is_accepted(self):
        mo.validate_layer_stack([CHAIN_3, CHAIN_3])

    def test_empty_stack_rejected(self):
        with pytest.raises(ValueError, match="at least one layer"):
            mo.validate_layer_stack([])

    def test_empty_matrix_rejected(self):
        with pytest.raises(ValueError, match="empty matrices"):
            mo.validate_layer_stack([[]])

    def test_too_many_nodes_rejected(self):
        big = [[0] * 64 for _ in range(64)]
        with pytest.raises(ValueError, match="at most 63"):
            mo.validate_layer_stack([big])

    def test_63_nodes_accepted(self):
        mo.validate_layer_stack([[[0] * 63 for _ in range(63)]])

    def test_non_square_layer_rejected(self):
        with pytest.raises(ValueError, match="layer 0 must be a square"):
            mo.validate_layer_stack([[[0, 1, 0], [0, 0, 1]]])

    def test_row_of_wrong_length_rejected(self):
        with pytest.raises(ValueError, match="layer 0 must be a square"):
            mo.validate_layer_stack([[[0, 1], [0]]])

    def test_layers_of_different_size_rejected(self):
        with pytest.raises(ValueError, match="layer 1 must be a square 3x3"):
            mo.validate_layer_stack([CHAIN_3, CHAIN_4])

    def test_non_binary_entry_rejected(self):
        with pytest.raises(ValueError, match="only 0 and 1"):
            mo.validate_layer_stack([[[0, 2], [0, 0]]])

    def test_name_is_used_in_message(self):
        with pytest.raises(ValueError, match="Stack A"):
            mo.validate_layer_stack([], "Stack A")


class TestBasics:
    def test_row_components_of_chain(self):
        # Spalte 0: leer, Spalte 1: Eintrag in Zeile 0 -> 1, Spalte 2: Zeile 1 -> 2
        assert mo.row_components(CHAIN_3) == (0, 1, 2)

    def test_row_components_inverse_of_matrix(self):
        assert mo.row_components(matrix([5, 3, 6])) == (5, 3, 6)

    def test_total_edges_over_all_layers(self):
        assert mo.total_edges([CHAIN_3, CHAIN_3, [[1, 1, 1]] * 3]) == 2 + 2 + 9


class TestContains:
    def test_shared_adjacent_pair_means_contained(self):
        a = stack([1, 2, 3])
        b = stack([1, 2, 0])
        assert mo.contains(a, b) is True

    def test_no_shared_pair_means_not_contained(self):
        a = stack([1, 2, 3])
        b = stack([2, 1, 0])
        assert mo.contains(a, b) is False

    def test_larger_graph_is_never_contained_in_smaller(self):
        assert mo.contains([CHAIN_4], [CHAIN_3]) is False

    def test_single_node_is_never_contained(self):
        assert mo.contains([[[1]]], [[[1]]]) is False

    def test_wrap_around_pair_of_b_counts(self):
        # Paar (7, 1) steht in b nur über den Rand (b[2], b[0])
        a = stack([7, 1, 2])
        b = stack([1, 4, 7])
        assert mo.contains(a, b) is True

    def test_edge_count_is_not_monotone(self):
        """A hat mehr Kanten als B und ist trotzdem in B enthalten (kein Kanten-Vorfilter)."""
        a = stack([1, 2, 7])
        b = stack([1, 2, 0])
        assert mo.total_edges(a) > mo.total_edges(b)
        assert mo.contains(a, b) is True

    def test_coherent_is_stricter_than_independent(self):
        a = stack([1, 2, 3], [4, 5, 6])
        b = stack([1, 2, 0], [0, 5, 6])
        assert mo.contains(a, b, "independent") is True
        assert mo.contains(a, b, "coherent") is False

    def test_coherent_implies_independent(self):
        a = stack([1, 2, 3], [4, 5, 6])
        b = stack([1, 2, 0], [4, 5, 0])
        assert mo.contains(a, b, "coherent") is True
        assert mo.contains(a, b, "independent") is True

    def test_default_mode_is_coherent(self):
        a = stack([1, 2, 3], [4, 5, 6])
        b = stack([1, 2, 0], [0, 5, 6])
        assert mo.contains(a, b) is False

    def test_every_layer_must_match_in_independent_mode(self):
        a = stack([1, 2, 3], [4, 5, 6])
        b = stack([1, 2, 0], [6, 5, 4])
        assert mo.contains(a, b, "independent") is False

    def test_single_layer_modes_agree(self):
        a = stack([1, 2, 3])
        b = stack([1, 2, 0])
        assert mo.contains(a, b, "coherent") == mo.contains(a, b, "independent")

    def test_different_layer_counts_rejected(self):
        with pytest.raises(ValueError, match="same number of layers"):
            mo.contains(stack([1, 2, 3]), stack([1, 2, 3], [1, 2, 3]))

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match="unknown mode"):
            mo.contains(stack([1, 2, 3]), stack([1, 2, 3]), "weird")

    def test_invalid_stack_rejected(self):
        with pytest.raises(ValueError, match="Stack B"):
            mo.contains(stack([1, 2, 3]), [[[0, 2], [0, 0]]])


class TestCompareLayered:
    def test_identical(self):
        s = stack([1, 2, 3], [4, 5, 6])
        assert mo.compare_layered(s, s) == "IDENTICAL"

    def test_identical_single_node(self):
        assert mo.compare_layered([[[1]]], [[[1]]]) == "IDENTICAL"

    def test_a_contained_in_larger_b(self):
        assert mo.compare_layered([CHAIN_3], [CHAIN_4]) == "KEEP_B"

    def test_b_contained_in_larger_a(self):
        assert mo.compare_layered([CHAIN_4], [CHAIN_3]) == "KEEP_A"

    def test_unrelated(self):
        assert mo.compare_layered(stack([1, 2, 3]), stack([2, 1, 0])) == "KEEP_BOTH"

    def test_mutual_containment_keeps_graph_with_more_edges(self):
        a = stack([1, 2, 7])
        b = stack([1, 2, 0])
        assert mo.compare_layered(a, b) == "EQUAL_KEEP_A"
        assert mo.compare_layered(b, a) == "EQUAL_KEEP_B"

    def test_mutual_containment_with_equal_edges_keeps_a(self):
        a = stack([1, 2, 4])
        b = stack([1, 2, 2])  # gleiche Kantenzahl wie a (je Spalte eine Kante)
        assert mo.total_edges(a) == mo.total_edges(b)
        assert mo.compare_layered(a, b) == "EQUAL_KEEP_A"

    def test_modes_can_differ(self):
        a = stack([1, 2, 3], [4, 5, 6])
        b = stack([1, 2, 0], [0, 5, 6])
        assert mo.compare_layered(a, b, "independent") != mo.compare_layered(a, b, "coherent")

    def test_invalid_input_rejected(self):
        with pytest.raises(ValueError):
            mo.compare_layered([], [CHAIN_3])
        with pytest.raises(ValueError, match="unknown mode"):
            mo.compare_layered([CHAIN_3], [CHAIN_3], "weird")
        with pytest.raises(ValueError, match="same number of layers"):
            mo.compare_layered([CHAIN_3], [CHAIN_3, CHAIN_3])


class TestAgainstReference:
    """Bigramm-Charakterisierung gegen n Rotationen mit Longest-Common-Substring."""

    @pytest.mark.parametrize("mode", ["coherent", "independent"])
    @pytest.mark.parametrize("layers", [1, 2, 3])
    def test_contains_matches_reference(self, layers, mode):
        rng = random.Random(1000 + layers)
        for _ in range(300):
            na, nb = rng.randint(1, 7), rng.randint(1, 7)
            a = random_stack(rng, layers, na, [1, 2, 3, 4, 5])
            b = random_stack(rng, layers, nb, [1, 2, 3, 4, 5])
            assert mo.contains(a, b, mode) == ref_contains(a, b, mode), (a, b)

    @pytest.mark.parametrize("mode", ["coherent", "independent"])
    @pytest.mark.parametrize("layers", [1, 2])
    def test_compare_matches_reference(self, layers, mode):
        rng = random.Random(2000 + layers)
        seen = set()
        for _ in range(400):
            na = rng.randint(1, 6)
            nb = na if rng.random() < 0.5 else rng.randint(1, 6)
            a = random_stack(rng, layers, na, [1, 2, 3, 5])
            b = random_stack(rng, layers, nb, [1, 2, 3, 5])
            expected = ref_compare(a, b, mode)
            seen.add(expected)
            assert mo.compare_layered(a, b, mode) == expected, (a, b)
        assert {"KEEP_A", "KEEP_B", "KEEP_BOTH"} <= seen
