"""
Tests für den invertierten Paarindex (universal_index)

Überprüft (reines Python, ohne Datenbank):
- Interner: injektives Wörterbuch, lesender Zugriff ohne Vergabe
- PairIndex: Einfügen, Entfernen, Kennzahlen, Fehlerfälle
- Suche in beiden Richtungen und Modi, Trefferlast, Kandidaten, Längenfilter
- classify: alle Ergebnisnamen im Abgleich mit compare_stacks
- Zufallsabgleich der Indexsuche mit dem Einzelvergleich über alle Schlüssel
"""

import random

import pytest

from backend.universal_core import MODES, Stack, compare_stacks, contained
from backend.universal_index import DIRECTIONS, IndexSearch, Interner, PairIndex

pytestmark = pytest.mark.unit

TWO_LAYER_QUERY = Stack.of([[{1}, {2}], [{3}, {4}]])
TWO_LAYER_SHIFTED = Stack.of([[{1}, {2}, {9}], [{9}, {3}, {4}]])


def single(*columns):
    """Stapel mit einer Schicht aus den Spalten (jede Spalte eine Menge)."""
    return Stack.of([[set(column) for column in columns]])


def build(layer_count, **stacks):
    index = PairIndex(layer_count)
    for key, stack in stacks.items():
        index.add(key, stack)
    return index


@pytest.fixture
def chain_index():
    return build(
        1,
        short=single({1}, {2}),
        chain=single({1}, {2}, {3}),
        long=single({1}, {2}, {3}, {4}),
        other=single({7}, {8}, {9}),
        lonely=single({1}),
    )


class TestInterner:
    def test_numbers_are_assigned_consecutively(self):
        interner = Interner()
        assert [interner.intern(frozenset({v})) for v in (5, 6, 7)] == [0, 1, 2]

    def test_same_component_same_number(self):
        interner = Interner()
        assert interner.intern(frozenset({1, 2})) == interner.intern(frozenset({2, 1}))
        assert len(interner) == 1

    def test_empty_component_is_a_component(self):
        interner = Interner()
        assert interner.intern(frozenset()) == 0

    def test_get_does_not_assign(self):
        interner = Interner()
        assert interner.get(frozenset({1})) is None
        assert len(interner) == 0
        interner.intern(frozenset({1}))
        assert interner.get(frozenset({1})) == 0


class TestIndexMaintenance:
    def test_layer_count_must_be_positive(self):
        with pytest.raises(ValueError, match="at least 1"):
            PairIndex(0)

    def test_empty_index(self):
        index = PairIndex(2)
        assert len(index) == 0
        assert index.entry_count() == 0
        assert index.interner_sizes() == [0, 0]
        assert "x" not in index

    def test_add_and_lookup(self):
        index = PairIndex(1)
        stack = single({1}, {2})
        index.add("k", stack)
        assert len(index) == 1 and "k" in index
        assert index.stack("k") == stack

    def test_unknown_key_raises_key_error(self):
        with pytest.raises(KeyError):
            PairIndex(1).stack("missing")

    def test_entry_count_counts_cyclic_and_linear_postings(self):
        index = build(1, k=single({1}, {2}))
        # zyklisch (0,1), (1,0); linear (0,1)
        assert index.entry_count() == 3

    def test_entry_count_grows_with_every_layer(self):
        index = build(2, k=TWO_LAYER_QUERY)
        assert index.entry_count() == 6

    def test_interner_sizes_per_layer(self):
        index = build(2, k=TWO_LAYER_QUERY, m=TWO_LAYER_SHIFTED)
        assert index.interner_sizes() == [3, 3]

    def test_duplicate_key_rejected(self):
        index = build(1, k=single({1}, {2}))
        with pytest.raises(ValueError, match="already indexed"):
            index.add("k", single({3}, {4}))

    def test_wrong_layer_count_rejected(self):
        with pytest.raises(ValueError, match="stack has 2 layers, the index expects 1"):
            PairIndex(1).add("k", TWO_LAYER_QUERY)

    def test_failed_add_leaves_index_unchanged(self):
        index = PairIndex(1)
        with pytest.raises(ValueError):
            index.add("k", TWO_LAYER_QUERY)
        assert len(index) == 0 and index.entry_count() == 0

    def test_remove_clears_all_postings(self):
        index = build(2, k=TWO_LAYER_QUERY)
        index.remove("k")
        assert len(index) == 0 and "k" not in index
        assert index.entry_count() == 0
        assert index.search(TWO_LAYER_QUERY, "independent").keys == []

    def test_remove_keeps_postings_shared_with_other_keys(self):
        index = build(1, first=single({1}, {2}), second=single({1}, {2}, {3}))
        index.remove("first")
        assert index.search(single({1}, {2})).keys == ["second"]

    def test_remove_unknown_key(self):
        with pytest.raises(ValueError, match="is not indexed"):
            PairIndex(1).remove("missing")

    def test_key_can_be_added_again_after_removal(self):
        index = build(1, k=single({1}, {2}))
        index.remove("k")
        index.add("k", single({5}, {6}))
        assert index.search(single({5}, {6})).keys == ["k"]
        assert index.search(single({1}, {2})).keys == []

    def test_removed_key_loses_its_insertion_position(self):
        index = build(1, a=single({1}, {2}), b=single({1}, {2}), c=single({1}, {2}))
        index.remove("a")
        index.add("a", single({1}, {2}))
        assert index.search(single({1}, {2})).keys == ["b", "c", "a"]


class TestSearchValidation:
    def test_unknown_mode(self, chain_index):
        with pytest.raises(ValueError, match="unknown mode 'weird'"):
            chain_index.search(single({1}, {2}), mode="weird")

    def test_unknown_direction(self, chain_index):
        with pytest.raises(ValueError, match="unknown direction 'sideways'"):
            chain_index.search(single({1}, {2}), direction="sideways")

    def test_query_layer_count_must_match(self, chain_index):
        with pytest.raises(ValueError, match="query has 2 layers, the index expects 1"):
            chain_index.search(TWO_LAYER_QUERY)

    def test_invalid_layer_selection(self, chain_index):
        with pytest.raises(ValueError, match="layer indices"):
            chain_index.search(single({1}, {2}), layers=[1])
        with pytest.raises(ValueError, match="at least one active layer"):
            chain_index.search(single({1}, {2}), layers=[])

    def test_directions_constant(self):
        assert DIRECTIONS == ("contains", "contained")


class TestSearchContains:
    def test_finds_stored_structures_containing_the_query(self, chain_index):
        result = chain_index.search(single({1}, {2}))
        assert result.keys == ["short", "chain", "long"]

    def test_result_is_a_named_tuple(self, chain_index):
        result = chain_index.search(single({1}, {2}))
        assert isinstance(result, IndexSearch)
        keys, hit_load, candidates = result
        assert (keys, hit_load, candidates) == (result.keys, result.hit_load, result.candidates)

    def test_default_direction_is_contains_and_mode_coherent(self, chain_index):
        query = single({1}, {2})
        assert chain_index.search(query) == chain_index.search(query, "coherent", None, "contains")

    def test_hit_load_and_candidates(self, chain_index):
        # Paar (1,2) steht in short, chain, long: Trefferlast 3
        result = chain_index.search(single({1}, {2}))
        assert result.hit_load == 3 and result.candidates == 3

    def test_length_filter_counts_towards_hit_load_but_not_candidates(self, chain_index):
        # (1,2) in 3 Listen, (2,3) in 2 Listen; nur Stapel der Länge >= 3 kommen in Frage
        result = chain_index.search(single({1}, {2}, {3}))
        assert result.keys == ["chain", "long"]
        assert result.hit_load == 5 and result.candidates == 2

    def test_query_longer_than_everything_matches_nothing(self, chain_index):
        result = chain_index.search(single({1}, {2}, {3}, {4}, {5}))
        assert result.keys == [] and result.candidates == 0

    def test_pair_may_wrap_around_in_stored_structure(self, chain_index):
        # (3,1) kommt nur zyklisch in chain und long (dort (4,1)) vor
        assert chain_index.search(single({3}, {1})).keys == ["chain"]

    def test_unknown_component_contributes_nothing(self, chain_index):
        result = chain_index.search(single({1}, {99}))
        assert result.keys == [] and result.hit_load == 0 and result.candidates == 0

    def test_query_without_pairs_matches_nothing(self, chain_index):
        assert chain_index.search(single({1})).keys == []

    def test_does_not_modify_the_dictionary(self, chain_index):
        before = chain_index.interner_sizes()
        chain_index.search(single({1}, {99}))
        assert chain_index.interner_sizes() == before

    def test_results_follow_insertion_order(self):
        index = build(1, z=single({1}, {2}), a=single({1}, {2}), m=single({1}, {2}))
        assert index.search(single({1}, {2})).keys == ["z", "a", "m"]

    def test_empty_index(self):
        assert PairIndex(1).search(single({1}, {2})) == IndexSearch([], 0, 0)


class TestSearchContained:
    def test_finds_stored_structures_contained_in_the_query(self, chain_index):
        result = chain_index.search(single({1}, {2}, {3}), direction="contained")
        assert result.keys == ["short", "chain"]

    def test_length_filter_applies_in_the_other_direction(self, chain_index):
        result = chain_index.search(single({1}, {2}), direction="contained")
        assert result.keys == ["short"]

    def test_hit_load_counts_linear_postings(self, chain_index):
        # Paare der Query (1,2),(2,3),(3,1): lineare Listen von (1,2): 3, (2,3): 2, (3,1): 0
        result = chain_index.search(single({1}, {2}, {3}), direction="contained")
        assert result.hit_load == 5 and result.candidates == 2

    def test_unknown_component_contributes_nothing(self, chain_index):
        result = chain_index.search(single({1}, {99}), direction="contained")
        assert result.keys == [] and result.hit_load == 0


class TestModes:
    @pytest.fixture
    def two_layer_index(self):
        return build(2, shifted=TWO_LAYER_SHIFTED)

    def test_independent_accepts_shifted_layers(self, two_layer_index):
        result = two_layer_index.search(TWO_LAYER_QUERY, "independent")
        assert result.keys == ["shifted"] and result.candidates == 1

    def test_coherent_verifies_the_candidates(self, two_layer_index):
        result = two_layer_index.search(TWO_LAYER_QUERY, "coherent")
        assert result.keys == [] and result.candidates == 1

    def test_coherent_verification_in_direction_contained(self):
        index = build(2, stored=TWO_LAYER_QUERY)
        independent = index.search(TWO_LAYER_SHIFTED, "independent", direction="contained")
        coherent = index.search(TWO_LAYER_SHIFTED, "coherent", direction="contained")
        assert independent.keys == ["stored"]
        assert coherent.keys == [] and coherent.candidates == 1

    def test_coherent_accepts_aligned_layers(self):
        aligned = Stack.of([[{1}, {2}, {9}], [{3}, {4}, {9}]])
        index = build(2, aligned=aligned)
        assert index.search(TWO_LAYER_QUERY, "coherent").keys == ["aligned"]

    def test_layers_restrict_the_intersection(self, two_layer_index):
        other = Stack.of([[{1}, {2}, {9}], [{7}, {8}, {9}]])
        index = build(2, other=other)
        assert index.search(TWO_LAYER_QUERY, "independent").keys == []
        assert index.search(TWO_LAYER_QUERY, "independent", layers=[0]).keys == ["other"]

    def test_layer_with_unknown_component_empties_the_intersection(self):
        index = build(2, stored=Stack.of([[{1}, {2}, {9}], [{3}, {4}, {9}]]))
        query = Stack.of([[{1}, {2}], [{3}, {77}]])
        assert index.search(query, "independent").keys == []
        assert index.search(query, "independent", layers=[0]).keys == ["stored"]

    def test_no_active_layers_gives_empty_intersection(self, two_layer_index):
        # Verteidigung: ohne aktive Schicht gibt es keinen Schnitt, also keine Treffer
        query = TWO_LAYER_QUERY
        assert two_layer_index._candidates(query, (), "contains") == (set(), 0)


class TestClassify:
    @pytest.fixture
    def index(self):
        return build(
            1,
            smaller=single({1}, {2}),
            larger=single({1}, {2}, {3}, {4}),
            tie=single({1}, {2}, {4}),
            heavier=single({1}, {2}, {3, 5}),
            same=single({1}, {2}, {3}),
            unrelated=single({7}, {8}, {9}),
        )

    QUERY = single({1}, {2}, {3})

    def test_all_result_names(self, index):
        assert index.classify(self.QUERY) == {
            "smaller": "KEEP_A",
            "larger": "KEEP_B",
            "tie": "EQUAL_KEEP_A",
            "heavier": "EQUAL_KEEP_B",
            "same": "IDENTICAL",
        }

    def test_unrelated_keys_are_missing(self, index):
        assert "unrelated" not in index.classify(self.QUERY)

    def test_agrees_with_compare_stacks(self, index):
        for key, name in index.classify(self.QUERY).items():
            assert compare_stacks(self.QUERY, index.stack(key)) == name

    def test_result_follows_insertion_order(self, index):
        assert list(index.classify(self.QUERY)) == ["smaller", "larger", "tie", "heavier", "same"]

    def test_mode_and_layers(self):
        index = build(2, shifted=TWO_LAYER_SHIFTED)
        assert index.classify(TWO_LAYER_QUERY, "independent") == {"shifted": "KEEP_B"}
        assert index.classify(TWO_LAYER_QUERY, "coherent") == {}
        assert index.classify(TWO_LAYER_QUERY, "coherent", [0]) == {"shifted": "KEEP_B"}

    def test_identical_is_decided_on_the_active_layers(self):
        stored = Stack.of([[{1}, {2}], [{8}, {9}]])
        index = build(2, stored=stored)
        assert index.classify(TWO_LAYER_QUERY, "coherent", [0]) == {"stored": "IDENTICAL"}

    def test_occupancy_comparison_uses_active_layers_only(self):
        stored = Stack.of([[{1}, {2}, {4}], [{1, 2, 3}, {4}, {5}]])
        query = Stack.of([[{1}, {2}, {3}], [{9}, {9}, {9}]])
        index = build(2, stored=stored)
        assert index.classify(query, "independent", [0]) == {"stored": "EQUAL_KEEP_A"}

    def test_structures_without_pairs_are_not_classified(self):
        index = build(1, lonely=single({1}))
        assert index.classify(single({1})) == {}
        assert compare_stacks(single({1}), index.stack("lonely")) == "IDENTICAL"

    def test_invalid_arguments_are_reported(self, index):
        with pytest.raises(ValueError, match="unknown mode"):
            index.classify(self.QUERY, "weird")


def _random_stack(rng, layer_count, length, alphabet=3):
    return Stack.of([
        [set() if rng.random() < 0.1 else {rng.randrange(alphabet)} for _ in range(length)]
        for _ in range(layer_count)
    ])


class TestAgreementWithPairwiseComparison:
    """Die Indexsuche liefert genau die Schlüssel, die der Einzelvergleich akzeptiert."""

    LAYER_COUNT = 2

    @pytest.fixture(scope="class")
    @classmethod
    def database(cls):
        rng = random.Random(7)
        index = PairIndex(cls.LAYER_COUNT)
        for number in range(60):
            index.add(f"k{number}", _random_stack(rng, cls.LAYER_COUNT, rng.randint(2, 5)))
        return index

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("direction", DIRECTIONS)
    @pytest.mark.parametrize("layers", [None, [0], [1]])
    def test_search_equals_brute_force(self, database, mode, direction, layers):
        index = database
        rng = random.Random(f"{mode}{direction}{layers}")
        for _ in range(60):
            query = _random_stack(rng, self.LAYER_COUNT, rng.randint(2, 4))
            expected = [
                key for key in (f"k{number}" for number in range(60))
                if (contained(query, index.stack(key), mode, layers) if direction == "contains"
                    else contained(index.stack(key), query, mode, layers))
            ]
            result = index.search(query, mode, layers, direction)
            assert result.keys == expected
            assert result.candidates >= len(result.keys)
            if mode == "independent":
                assert result.candidates == len(result.keys)

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("layers", [None, [1]])
    def test_classify_equals_compare_stacks(self, database, mode, layers):
        index = database
        rng = random.Random(f"classify{mode}{layers}")
        names = set()
        for _ in range(80):
            query = _random_stack(rng, self.LAYER_COUNT, rng.randint(2, 4))
            expected = {}
            for number in range(60):
                key = f"k{number}"
                name = compare_stacks(query, index.stack(key), mode, layers)
                if name != "KEEP_BOTH":
                    expected[key] = name
            assert index.classify(query, mode, layers) == expected
            names.update(expected.values())
        assert {"KEEP_A", "KEEP_B"} <= names
