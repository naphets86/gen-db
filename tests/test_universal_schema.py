"""
Tests für Schema, Struktur, Koordinatensysteme und Kodierung (universal_schema)

Überprüft (reines Python, ohne Datenbank):
- RelationType und Schema: Validierung, Schichtanordnung, Schichtzahl L_Sigma, (De-)Serialisierung
- Structure.build: Prüfung und Normalisierung
- Koordinatensysteme: Register, lokal, Anfrage
- SchemaEncoder: Kodierung Schicht für Schicht, Verlustfreiheit (decode), Zurückweisung von
  Stapeln außerhalb des Bildes
- aktive Schichten einer Anfrage und Matrixstapel als Schema
"""

import random

import pytest

from backend.universal_core import Stack, stack_from_matrices
from backend.universal_schema import (
    COORDINATE_SYSTEMS,
    LocalCoordinates,
    QueryCoordinates,
    RegisterCoordinates,
    RelationType,
    Schema,
    SchemaEncoder,
    Structure,
    encode_matrices,
    matrix_schema,
    matrix_search_layers,
    resolve_active_layers,
)

pytestmark = pytest.mark.unit

GENE = Schema(
    name="gene",
    features=("kinase",),
    relations=(RelationType("regulates", 2, 1),),
)

COMPLEX = Schema(
    name="complex",
    version=2,
    features=("kinase", "receptor"),
    relations=(
        RelationType("regulates", 2, 3),
        RelationType("complex", 3, 2),
        RelationType("flag", 1, 1),
    ),
)

COMPLEX_LABELS = [
    "ex", "lab:kinase", "lab:receptor",
    "bin:regulates:1", "bin:regulates:2", "bin:regulates:3",
    "inz:complex:1", "inz:complex:2", "inz:complex:3", "wgt:complex:2",
    "inz:flag:1",
]


def complex_structure():
    return Structure.build(
        COMPLEX,
        {"a": {"kinase"}, "b": {"kinase", "receptor"}, "c": set()},
        {
            "regulates": {("a", "b"): 3, ("b", "c"): 1},
            "complex": {("a", "b", "c"): 2, ("c", "c", "a"): 1},
            "flag": [("b",)],
        },
    )


def complex_register():
    """c, a, b erhalten 0, 1, 2: die Spaltenreihenfolge unterscheidet sich von der Eingabe."""
    return RegisterCoordinates({"c": 0, "a": 1, "b": 2})


class TestRelationType:
    def test_defaults(self):
        relation = RelationType("interacts")
        assert (relation.arity, relation.levels) == (2, 1)

    @pytest.mark.parametrize("name", ["", None, 5])
    def test_name_must_be_a_non_empty_string(self, name):
        with pytest.raises(ValueError, match="relation type name must be a non-empty string"):
            RelationType(name)

    def test_name_must_not_contain_colon(self):
        with pytest.raises(ValueError, match="must not contain ':'"):
            RelationType("a:b")

    @pytest.mark.parametrize("arity", [0, -1, 2.0, "2"])
    def test_arity_must_be_a_positive_integer(self, arity):
        with pytest.raises(ValueError, match="arity must be an integer >= 1"):
            RelationType("r", arity)

    @pytest.mark.parametrize("levels", [0, -1, 1.5, None])
    def test_levels_must_be_a_positive_integer(self, levels):
        with pytest.raises(ValueError, match="levels must be an integer >= 1"):
            RelationType("r", 2, levels)


class TestSchemaValidation:
    def test_minimal_schema_has_only_the_existence_layer(self):
        schema = Schema(name="empty")
        assert schema.layer_count == 1
        assert schema.layer_labels == ("ex",)
        assert schema.coordinates == "register" and schema.version == 1

    def test_coordinate_systems_constant(self):
        assert COORDINATE_SYSTEMS == ("register", "local")

    def test_unknown_coordinate_system(self):
        with pytest.raises(ValueError, match="unknown coordinate system 'polar'"):
            Schema(name="s", coordinates="polar")

    @pytest.mark.parametrize("version", [0, -3, 1.0, "1"])
    def test_version_must_be_a_positive_integer(self, version):
        with pytest.raises(ValueError, match="version must be an integer >= 1"):
            Schema(name="s", version=version)

    @pytest.mark.parametrize("name", ["", None, "a:b"])
    def test_schema_name(self, name):
        with pytest.raises(ValueError, match="schema name"):
            Schema(name=name)

    def test_feature_names_are_checked(self):
        with pytest.raises(ValueError, match="feature name 'x:y' must not contain"):
            Schema(name="s", features=("x:y",))

    def test_feature_names_must_be_unique(self):
        with pytest.raises(ValueError, match="feature names must be unique"):
            Schema(name="s", features=("a", "a"))

    def test_relation_names_must_be_unique(self):
        with pytest.raises(ValueError, match="relation type names must be unique"):
            Schema(name="s", relations=(RelationType("r"), RelationType("r", 3)))


class TestSchemaLayout:
    def test_layer_labels(self):
        assert COMPLEX.layer_labels == tuple(COMPLEX_LABELS)

    def test_layout_maps_keys_to_positions(self):
        layout = COMPLEX.layout
        assert layout[("ex",)] == 0
        assert layout[("lab", "receptor")] == 2
        assert layout[("bin", "regulates", 3)] == 5
        assert layout[("inz", "complex", 3)] == 8
        assert layout[("wgt", "complex", 2)] == 9
        assert layout[("inz", "flag", 1)] == 10

    def test_binary_relations_have_no_incidence_or_weight_layers(self):
        assert [label for label in COMPLEX.layer_labels if "regulates" in label] == [
            "bin:regulates:1", "bin:regulates:2", "bin:regulates:3"
        ]

    def test_unweighted_general_relation_has_no_weight_layer(self):
        schema = Schema(name="s", relations=(RelationType("triple", 3, 1),))
        assert schema.layer_labels == ("ex", "inz:triple:1", "inz:triple:2", "inz:triple:3")

    @pytest.mark.parametrize(
        "features, relations",
        [
            (0, [(2, 1)]),
            (3, [(2, 1), (2, 4)]),
            (1, [(1, 1)]),
            (0, [(1, 3)]),
            (2, [(2, 2), (3, 2), (4, 5), (1, 1)]),
        ],
    )
    def test_layer_count_formula(self, features, relations):
        schema = Schema(
            name="s",
            features=tuple(f"f{i}" for i in range(features)),
            relations=tuple(RelationType(f"r{i}", k, w) for i, (k, w) in enumerate(relations)),
        )
        expected = 1 + features
        for k, w in relations:
            expected += w if k == 2 else k + w - 1
        assert schema.layer_count == expected == len(schema.layer_labels)

    def test_relation_lookup(self):
        assert COMPLEX.relation("complex") == RelationType("complex", 3, 2)

    def test_unknown_relation(self):
        with pytest.raises(ValueError, match="unknown relation type 'nope'"):
            COMPLEX.relation("nope")


class TestSchemaSerialization:
    def test_round_trip(self):
        assert Schema.from_dict(COMPLEX.to_dict()) == COMPLEX

    def test_to_dict_is_json_ready(self):
        assert GENE.to_dict() == {
            "name": "gene", "version": 1, "coordinates": "register",
            "features": ["kinase"],
            "relations": [{"name": "regulates", "arity": 2, "levels": 1}],
        }

    def test_coordinates_default_to_register(self):
        data = GENE.to_dict()
        del data["coordinates"]
        assert Schema.from_dict(data).coordinates == "register"

    def test_local_coordinates_survive(self):
        assert Schema.from_dict(matrix_schema(["t"]).to_dict()).coordinates == "local"

    def test_missing_key(self):
        data = GENE.to_dict()
        del data["relations"]
        with pytest.raises(ValueError, match="invalid schema definition"):
            Schema.from_dict(data)

    def test_wrong_type(self):
        data = GENE.to_dict()
        data["features"] = 5
        with pytest.raises(ValueError, match="invalid schema definition"):
            Schema.from_dict(data)

    def test_invalid_content_is_reported_by_the_schema(self):
        data = GENE.to_dict()
        data["version"] = 0
        with pytest.raises(ValueError, match="version"):
            Schema.from_dict(data)

    def test_equality_ignores_cached_layout(self):
        first = Schema.from_dict(COMPLEX.to_dict())
        first.layout  # füllt den Cache
        assert first == COMPLEX and hash(first) == hash(COMPLEX)


class TestStructureBuild:
    def test_entities_as_mapping(self):
        structure = Structure.build(GENE, {"a": ["kinase"], "b": []})
        assert structure.entities == {"a": frozenset({"kinase"}), "b": frozenset()}

    def test_entities_as_sequence(self):
        structure = Structure.build(GENE, ["a", "b"])
        assert structure.entities == {"a": frozenset(), "b": frozenset()}

    def test_every_relation_type_is_present(self):
        structure = Structure.build(COMPLEX, ["a"])
        assert structure.relations == {"regulates": {}, "complex": {}, "flag": {}}

    def test_relations_as_rows_get_weight_one(self):
        structure = Structure.build(GENE, ["a", "b"], {"regulates": [["a", "b"]]})
        assert structure.relations["regulates"] == {("a", "b"): 1}

    def test_relations_as_mapping_keep_weights(self):
        structure = Structure.build(COMPLEX, ["a", "b"], {"regulates": {("a", "b"): 3}})
        assert structure.relations["regulates"] == {("a", "b"): 3}

    def test_duplicate_rows_collapse(self):
        structure = Structure.build(GENE, ["a", "b"], {"regulates": [("a", "b"), ("a", "b")]})
        assert len(structure.relations["regulates"]) == 1

    def test_size(self):
        assert complex_structure().size == 3 + 2 + 2 + 1

    def test_unknown_feature(self):
        with pytest.raises(ValueError, match=r"entity 'a' has unknown features \['phosphatase'\]"):
            Structure.build(GENE, {"a": ["kinase", "phosphatase"]})

    def test_unknown_relation_type(self):
        with pytest.raises(ValueError, match="unknown relation type 'nope'"):
            Structure.build(GENE, ["a"], {"nope": []})

    def test_wrong_arity(self):
        with pytest.raises(ValueError, match="must have 2 entities"):
            Structure.build(GENE, ["a"], {"regulates": [("a",)]})

    def test_unknown_entity_in_relation(self):
        with pytest.raises(ValueError, match=r"unknown entities \['z'\]"):
            Structure.build(GENE, ["a"], {"regulates": [("a", "z")]})

    @pytest.mark.parametrize("weight", [0, 4, -1, "2", 1.0])
    def test_weight_must_be_within_levels(self, weight):
        with pytest.raises(ValueError, match=r"weight .* outside 1\.\.3"):
            Structure.build(COMPLEX, ["a", "b"], {"regulates": {("a", "b"): weight}})


class TestRegisterCoordinates:
    def test_assigns_consecutive_coordinates(self):
        register = RegisterCoordinates()
        assert [register(name) for name in ("x", "y", "x", "z")] == [0, 1, 0, 2]

    def test_existing_coordinates_never_change(self):
        register = RegisterCoordinates({"a": 5})
        assert register("b") == 6
        assert register("a") == 5

    def test_next_coordinate(self):
        assert RegisterCoordinates().next_coordinate == 0
        assert RegisterCoordinates({"a": 3, "b": 0}).next_coordinate == 4

    def test_lookup_does_not_assign(self):
        register = RegisterCoordinates({"a": 0})
        assert register.lookup("a") == 0
        assert register.lookup("b") is None
        assert len(register) == 1

    def test_frozen_register_rejects_unknown_entities(self):
        register = RegisterCoordinates({"a": 0}, frozen=True)
        assert register("a") == 0
        with pytest.raises(ValueError, match="entity 'b' is not registered"):
            register("b")
        assert "b" not in register

    def test_entity_is_the_inverse(self):
        register = RegisterCoordinates({"a": 7})
        assert register.entity(7) == "a"
        with pytest.raises(ValueError, match="coordinate 8 is not registered"):
            register.entity(8)

    def test_contains_and_len(self):
        register = RegisterCoordinates({"a": 0, "b": 1})
        assert "a" in register and "c" not in register and len(register) == 2

    def test_items_sorted_by_coordinate(self):
        register = RegisterCoordinates({"b": 9, "a": 3, "c": 5})
        assert register.items() == [("a", 3), ("c", 5), ("b", 9)]

    @pytest.mark.parametrize("coordinate", [-1, "1", 1.5])
    def test_assigned_coordinates_must_be_non_negative_integers(self, coordinate):
        with pytest.raises(ValueError, match="non-negative integer"):
            RegisterCoordinates({"a": coordinate})

    def test_assigned_coordinates_must_be_injective(self):
        with pytest.raises(ValueError, match="coordinate 1 is assigned twice"):
            RegisterCoordinates({"a": 1, "b": 1})


class TestLocalCoordinates:
    def test_rank_in_given_order(self):
        local = LocalCoordinates(["x", "y", "z"])
        assert [local(name) for name in ("z", "x", "y")] == [2, 0, 1]

    def test_entity_is_the_inverse(self):
        local = LocalCoordinates(["x", "y"])
        assert [local.entity(0), local.entity(1)] == ["x", "y"]

    def test_unknown_entity(self):
        with pytest.raises(ValueError, match="entity 'q' is not part of the local"):
            LocalCoordinates(["x"])("q")

    @pytest.mark.parametrize("coordinate", [-1, 2])
    def test_coordinate_out_of_range(self, coordinate):
        with pytest.raises(ValueError, match=r"coordinate .* is outside 0\.\.1"):
            LocalCoordinates(["x", "y"]).entity(coordinate)

    def test_entities_must_be_unique(self):
        with pytest.raises(ValueError, match="must be unique"):
            LocalCoordinates(["x", "x"])


class TestQueryCoordinates:
    def test_known_entities_keep_their_coordinate(self):
        query = QueryCoordinates(RegisterCoordinates({"a": 0, "b": 4}))
        assert (query("a"), query("b")) == (0, 4)

    def test_unknown_entities_get_temporary_coordinates_above_the_register(self):
        register = RegisterCoordinates({"a": 0, "b": 4})
        query = QueryCoordinates(register)
        assert (query("x"), query("y"), query("x")) == (5, 6, 5)
        assert "x" not in register and len(register) == 2

    def test_first_free_protects_against_foreign_coordinates(self):
        query = QueryCoordinates(RegisterCoordinates({"a": 0}), first_free=100)
        assert query("x") == 100

    def test_first_free_below_register_is_ignored(self):
        query = QueryCoordinates(RegisterCoordinates({"a": 7}), first_free=3)
        assert query("x") == 8

    def test_entity_is_the_inverse_for_both_kinds(self):
        query = QueryCoordinates(RegisterCoordinates({"a": 0}))
        temporary = query("x")
        assert query.entity(temporary) == "x"
        assert query.entity(0) == "a"

    def test_unknown_coordinate(self):
        with pytest.raises(ValueError, match="coordinate 9 is not registered"):
            QueryCoordinates(RegisterCoordinates({"a": 0})).entity(9)


class TestEncode:
    def test_gene_schema_by_hand(self):
        structure = Structure.build(
            GENE, {"a": ["kinase"], "b": []}, {"regulates": [("a", "b")]}
        )
        stack = SchemaEncoder(GENE, RegisterCoordinates({"a": 0, "b": 1})).encode(structure)
        assert stack.to_lists() == [
            [[0], [1]],   # ex
            [[0], []],    # lab:kinase
            [[], [0]],    # bin:regulates:1, a -> b trägt a in der Spalte von b ein
        ]

    def test_every_layer_of_the_complex_schema(self):
        stack = SchemaEncoder(COMPLEX, complex_register()).encode(complex_structure())
        e = []
        assert stack.length == 6
        assert stack.to_lists() == [
            [[0], [1], [2], e, e, e],            # ex
            [e, [1], [2], e, e, e],              # lab:kinase
            [e, e, [2], e, e, e],                # lab:receptor
            [[2], e, [1], e, e, e],              # bin:regulates:1
            [e, e, [1], e, e, e],                # bin:regulates:2
            [e, e, [1], e, e, e],                # bin:regulates:3
            [e, e, e, [0], [1], e],              # inz:complex:1
            [e, e, e, [0], [2], e],              # inz:complex:2
            [e, e, e, [1], [0], e],              # inz:complex:3
            [e, e, e, e, [1], e],                # wgt:complex:2
            [e, e, e, e, e, [2]],                # inz:flag:1
        ]

    def test_layer_count_depends_only_on_the_schema(self):
        empty = SchemaEncoder(COMPLEX, RegisterCoordinates()).encode(Structure.build(COMPLEX, []))
        assert empty.layer_count == COMPLEX.layer_count and empty.length == 0

    def test_independent_of_input_order(self):
        first = Structure.build(COMPLEX, ["a", "b", "c"],
                                {"regulates": {("a", "b"): 2, ("b", "c"): 1}})
        second = Structure.build(COMPLEX, ["c", "b", "a"],
                                 {"regulates": {("b", "c"): 1, ("a", "b"): 2}})
        encoded = [SchemaEncoder(COMPLEX, RegisterCoordinates({"a": 0, "b": 1, "c": 2})).encode(s)
                   for s in (first, second)]
        assert encoded[0] == encoded[1]

    def test_register_coordinates_are_assigned_on_demand(self):
        register = RegisterCoordinates()
        SchemaEncoder(GENE, register).encode(Structure.build(GENE, ["p", "q"]))
        assert register.items() == [("p", 0), ("q", 1)]

    def test_local_coordinates_use_the_rank(self):
        structure = Structure.build(GENE, ["b", "a"], {"regulates": [("b", "a")]})
        stack = SchemaEncoder(GENE, LocalCoordinates(["b", "a"])).encode(structure)
        assert stack.to_lists()[0] == [[0], [1]]
        assert stack.to_lists()[2] == [[], [0]]

    def test_structure_is_validated_against_the_schema(self):
        invalid = Structure(entities={"a": frozenset({"unknown"})}, relations={"regulates": {}})
        with pytest.raises(ValueError, match="unknown features"):
            SchemaEncoder(GENE, RegisterCoordinates()).encode(invalid)

    def test_entity_without_coordinate(self):
        encoder = SchemaEncoder(GENE, RegisterCoordinates({"a": 0}, frozen=True))
        with pytest.raises(ValueError, match="not registered"):
            encoder.encode(Structure.build(GENE, ["a", "b"]))

    def test_query_coordinates_encode_unknown_entities_without_storing_them(self):
        register = RegisterCoordinates({"a": 0})
        encoder = SchemaEncoder(GENE, QueryCoordinates(register))
        stack = encoder.encode(Structure.build(GENE, ["a", "new"], {"regulates": [("a", "new")]}))
        assert stack.to_lists()[0] == [[0], [1]]
        assert len(register) == 1


class TestDecode:
    def roundtrip(self, schema, structure, register):
        encoder = SchemaEncoder(schema, register)
        return encoder.decode(encoder.encode(structure))

    def test_round_trip(self):
        structure = complex_structure()
        assert self.roundtrip(COMPLEX, structure, complex_register()) == structure

    def test_round_trip_of_the_empty_structure(self):
        structure = Structure.build(COMPLEX, [])
        assert self.roundtrip(COMPLEX, structure, RegisterCoordinates()) == structure

    def test_round_trip_with_local_coordinates(self):
        structure = Structure.build(GENE, ["x", "y"], {"regulates": [("y", "x")]})
        encoder = SchemaEncoder(GENE, LocalCoordinates(["x", "y"]))
        assert encoder.decode(encoder.encode(structure)) == structure

    def test_round_trip_of_random_structures(self):
        rng = random.Random(5)
        for _ in range(150):
            names = [f"e{i}" for i in range(rng.randint(0, 5))]
            entities = {name: [f for f in COMPLEX.features if rng.random() < 0.4] for name in names}
            relations = {"regulates": {}, "complex": {}, "flag": {}}
            if names:
                for _ in range(rng.randint(0, 6)):
                    pair = (rng.choice(names), rng.choice(names))
                    relations["regulates"][pair] = rng.randint(1, 3)
                for _ in range(rng.randint(0, 4)):
                    triple = tuple(rng.choice(names) for _ in range(3))
                    relations["complex"][triple] = rng.randint(1, 2)
                for _ in range(rng.randint(0, 3)):
                    relations["flag"][(rng.choice(names),)] = 1
            structure = Structure.build(COMPLEX, entities, relations)
            assert self.roundtrip(COMPLEX, structure, RegisterCoordinates()) == structure

    def test_encoding_is_injective_on_distinct_structures(self):
        encoder = SchemaEncoder(GENE, RegisterCoordinates({"a": 0, "b": 1}))
        forward = encoder.encode(Structure.build(GENE, ["a", "b"], {"regulates": [("a", "b")]}))
        backward = encoder.encode(Structure.build(GENE, ["a", "b"], {"regulates": [("b", "a")]}))
        assert forward != backward

    def encoded(self):
        return SchemaEncoder(COMPLEX, complex_register()).encode(complex_structure())

    def decode(self, lists):
        return SchemaEncoder(COMPLEX, complex_register()).decode(Stack.of(lists))

    def test_wrong_layer_count(self):
        with pytest.raises(ValueError, match="stack has 1 layers, schema 'complex' needs 11"):
            SchemaEncoder(COMPLEX, complex_register()).decode(Stack.of([[{0}]]))

    def test_existence_component_with_several_coordinates(self):
        lists = self.encoded().to_lists()
        lists[0][0] = [0, 2]
        with pytest.raises(ValueError, match="malformed existence layer"):
            self.decode(lists)

    def test_empty_existence_component_before_an_entity(self):
        lists = self.encoded().to_lists()
        lists[0][0] = []
        with pytest.raises(ValueError, match="malformed existence layer"):
            self.decode(lists)

    def test_unknown_coordinate_in_the_existence_layer(self):
        lists = self.encoded().to_lists()
        lists[0][0] = [99]
        with pytest.raises(ValueError, match="coordinate 99 is not registered"):
            self.decode(lists)

    def test_column_without_relation_type(self):
        lists = [[cell for cell in layer] for layer in self.encoded().to_lists()]
        lists = [layer + [[]] for layer in lists]
        with pytest.raises(ValueError, match="column 6 does not belong to exactly one relation type"):
            self.decode(lists)

    def test_column_with_two_relation_types(self):
        lists = self.encoded().to_lists()
        lists[10][3] = [2]  # inz:flag:1 in der Spalte eines Komplexes
        with pytest.raises(ValueError, match="column 3 does not belong to exactly one relation type"):
            self.decode(lists)

    def test_incidence_must_be_a_single_entity(self):
        lists = self.encoded().to_lists()
        lists[7][3] = []
        with pytest.raises(ValueError, match="incidence 2 of 'complex' must be a single entity"):
            self.decode(lists)
        lists = self.encoded().to_lists()
        lists[7][3] = [0, 1]
        with pytest.raises(ValueError, match="incidence 2 of 'complex' must be a single entity"):
            self.decode(lists)

    def test_stack_outside_the_image_is_rejected(self):
        lists = self.encoded().to_lists()
        lists[1][3] = [1]  # Merkmal in der Spalte eines Relationsknotens
        with pytest.raises(ValueError, match="not the image of a structure of this schema"):
            self.decode(lists)

    def test_higher_weight_level_without_lower_level_is_rejected(self):
        lists = self.encoded().to_lists()
        lists[3][2] = []   # bin:regulates:1 der Kante a -> b entfernen, Stufe 2 und 3 bleiben
        with pytest.raises(ValueError, match="not the image"):
            self.decode(lists)

    def test_weight_of_general_relations_is_the_highest_level(self):
        decoded = self.decode(self.encoded().to_lists())
        assert decoded.relations["complex"] == {("a", "b", "c"): 2, ("c", "c", "a"): 1}


class TestResolveActiveLayers:
    QUERY = SchemaEncoder(GENE, RegisterCoordinates({"a": 0, "b": 1})).encode(
        Structure.build(GENE, {"a": ["kinase"], "b": []}, {"regulates": [("a", "b")]})
    )

    def test_default_is_all_non_empty_layers_without_existence(self):
        assert resolve_active_layers(GENE, self.QUERY) == (1, 2)

    def test_empty_layers_are_not_active(self):
        stack = SchemaEncoder(GENE, RegisterCoordinates()).encode(
            Structure.build(GENE, ["a", "b"], {"regulates": [("a", "b")]})
        )
        assert resolve_active_layers(GENE, stack) == (2,)

    def test_existence_layer_on_request(self):
        assert resolve_active_layers(GENE, self.QUERY, include_existence=True) == (0, 1, 2)

    def test_no_non_empty_layer(self):
        stack = SchemaEncoder(GENE, RegisterCoordinates()).encode(Structure.build(GENE, ["a"]))
        with pytest.raises(ValueError, match="no non-empty layer"):
            resolve_active_layers(GENE, stack)

    def test_explicit_indices(self):
        assert resolve_active_layers(GENE, self.QUERY, [2, 1]) == (1, 2)

    def test_explicit_names(self):
        assert resolve_active_layers(GENE, self.QUERY, ["bin:regulates:1"]) == (2,)

    def test_names_and_indices_can_be_mixed(self):
        assert resolve_active_layers(GENE, self.QUERY, ["lab:kinase", 2]) == (1, 2)

    def test_unknown_name(self):
        with pytest.raises(ValueError, match="unknown layer 'lab:nothing'"):
            resolve_active_layers(GENE, self.QUERY, ["lab:nothing"])

    def test_invalid_index(self):
        with pytest.raises(ValueError, match="layer indices"):
            resolve_active_layers(GENE, self.QUERY, [3])

    def test_empty_selection(self):
        with pytest.raises(ValueError, match="at least one active layer"):
            resolve_active_layers(GENE, self.QUERY, [])

    def test_explicit_empty_layer_is_rejected(self):
        stack = SchemaEncoder(GENE, RegisterCoordinates()).encode(
            Structure.build(GENE, ["a", "b"], {"regulates": [("a", "b")]})
        )
        with pytest.raises(ValueError, match=r"layers \['lab:kinase'\] of the query are empty"):
            resolve_active_layers(GENE, stack, ["lab:kinase", "bin:regulates:1"])

    def test_stack_must_match_the_schema(self):
        with pytest.raises(ValueError, match="stack has 1 layers, schema 'gene' needs 3"):
            resolve_active_layers(GENE, Stack.of([[{0}]]))


class TestMatrixSchema:
    CHAIN = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
    RING = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]

    def test_schema_has_one_binary_relation_per_layer(self):
        schema = matrix_schema(["transcriptome", "proteome"])
        assert schema.coordinates == "local" and schema.features == ()
        assert schema.layer_labels == ("ex", "bin:transcriptome:1", "bin:proteome:1")
        assert (schema.name, schema.version) == ("multiomics-matrix", 1)

    def test_custom_name_and_version(self):
        schema = matrix_schema(["t"], name="custom", version=3)
        assert (schema.name, schema.version) == ("custom", 3)

    def test_duplicate_layer_names(self):
        with pytest.raises(ValueError, match="relation type names must be unique"):
            matrix_schema(["t", "t"])

    def test_search_layers_skip_the_existence_layer(self):
        assert matrix_search_layers(matrix_schema(["t", "p", "m"])) == (1, 2, 3)

    def test_encoding_restricted_to_search_layers_is_the_matrix_stack(self):
        schema = matrix_schema(["t", "p"])
        stack = encode_matrices(schema, ["A", "B", "C"], [self.CHAIN, self.RING])
        projected = stack.project(matrix_search_layers(schema))
        assert projected == stack_from_matrices([self.CHAIN, self.RING])

    def test_existence_layer_holds_local_coordinates(self):
        schema = matrix_schema(["t"])
        stack = encode_matrices(schema, ["A", "B", "C"], [self.CHAIN])
        assert stack.to_lists()[0] == [[0], [1], [2]]

    def test_decode_returns_the_edges(self):
        schema = matrix_schema(["t"])
        stack = encode_matrices(schema, ["A", "B", "C"], [self.CHAIN])
        structure = SchemaEncoder(schema, LocalCoordinates(["A", "B", "C"])).decode(stack)
        assert structure.relations["t"] == {("A", "B"): 1, ("B", "C"): 1}

    def test_number_of_labels_must_match(self):
        with pytest.raises(ValueError, match="number of labels"):
            encode_matrices(matrix_schema(["t"]), ["A", "B"], [self.CHAIN])

    def test_number_of_matrices_must_match(self):
        with pytest.raises(ValueError, match="number of matrices"):
            encode_matrices(matrix_schema(["t", "p"]), ["A", "B", "C"], [self.CHAIN])

    def test_invalid_matrices(self):
        with pytest.raises(ValueError, match="only 0 and 1"):
            encode_matrices(matrix_schema(["t"]), ["A", "B"], [[[0, 2], [0, 0]]])
