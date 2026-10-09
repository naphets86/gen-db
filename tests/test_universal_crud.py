"""
Tests für die universellen Funktionen in crud.py (ohne Datenbank)

Verbindung und Cursor werden durch eine kleine In-Memory-Datenbank ersetzt, die genau die
SQL-Befehle der universellen Kodierung versteht (Schemata, Entitätsregister, Komponenten,
Strukturen, Paarindex) und eine Transaktion bei Fehlern zurückrollt. Dadurch laufen Anlegen,
Lesen und Suchen echt durch die Kodierung und den Kern; unbekannte SQL-Befehle lassen den Test
fehlschlagen. Das Verhalten gegen PostgreSQL deckt test_universal_integration.py ab.
"""

import copy
import hashlib
import json
from contextlib import contextmanager

import pytest

from backend import crud
from backend.models import (
    UniversalSearchMatch,
    UniversalStructureCreationResult,
    UniversalStructureRecord,
)
from backend.universal_core import Stack
from backend.universal_schema import (
    RegisterCoordinates,
    RelationType,
    Schema,
    SchemaEncoder,
    Structure,
    matrix_schema,
)

pytestmark = pytest.mark.unit

GENE = Schema(
    name="gene-regulation",
    features=("kinase",),
    relations=(RelationType("regulates", 2, 1),),
)

COMPLEX = Schema(
    name="complex-network",
    features=("kinase",),
    relations=(RelationType("regulates", 2, 2), RelationType("complex", 3, 2)),
)

MATRIX = matrix_schema(["t", "p"], name="omics")


class FakeUniversalDatabase:
    """In-Memory-Ersatz für die Tabellen aus init-db.sql, die die universelle Kodierung nutzt."""

    CREATED_AT = "2026-10-09 12:00:00"

    def __init__(self):
        self.tables = {
            "schemas": {}, "entities": {}, "networks": {}, "components": {},
            "structures": {}, "pairs": [],
            "sequences": {"schema": 0, "entity": 0, "component": 0, "network": 0},
        }
        self.executed = []

    # -- Verbindung ---------------------------------------------------------

    @contextmanager
    def connection(self):
        snapshot = copy.deepcopy(self.tables)
        try:
            yield object()
        except Exception:
            self.tables = snapshot
            raise

    def cursor(self, _connection):
        return _FakeCursor(self)

    def statements(self, prefix):
        return [sql for sql, _ in self.executed if sql.startswith(prefix)]

    def _next(self, name):
        self.tables["sequences"][name] += 1
        return self.tables["sequences"][name]


class _FakeCursor:
    def __init__(self, database):
        self.db = database
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.db.executed.append((sql, params))
        for prefix, handler in self.HANDLERS:
            if sql.startswith(prefix):
                self._rows = handler(self, sql, params)
                return
        raise AssertionError(f"unexpected SQL statement: {sql}")

    # -- Schemata -----------------------------------------------------------

    def _select_schema(self, sql, params):
        schemas = self.db.tables["schemas"]
        if "ORDER BY version DESC LIMIT 1" in sql:
            (name,) = params
            found = [s for s in schemas.values() if s["name"] == name]
            found = sorted(found, key=lambda s: s["version"], reverse=True)[:1]
        else:
            name, version = params
            found = [s for s in schemas.values() if (s["name"], s["version"]) == (name, version)]
        return [{"schema_id": s["schema_id"], "definition": s["definition"]} for s in found]

    def _insert_schema(self, sql, params):
        name, version, layer_count, definition = params
        schema_id = self.db._next("schema")
        self.db.tables["schemas"][schema_id] = {
            "schema_id": schema_id, "name": name, "version": version,
            "layer_count": layer_count, "definition": json.loads(definition),
        }
        return [{"schema_id": schema_id}]

    # -- Entitätsregister ---------------------------------------------------

    def _insert_entities(self, sql, params):
        (names,) = params
        for name in names:
            coordinate = self.db._next("entity")  # BIGSERIAL: auch bei Konflikt verbraucht
            self.db.tables["entities"].setdefault(name, coordinate)
        return []

    def _select_entities(self, sql, params):
        (names,) = params
        entities = self.db.tables["entities"]
        return [{"entity": name, "coordinate": entities[name]} for name in names if name in entities]

    def _select_next_free(self, sql, params):
        entities = self.db.tables["entities"]
        return [{"next_free": max(entities.values(), default=-1) + 1}]

    # -- Wörterbuch ---------------------------------------------------------

    def _insert_components(self, sql, params):
        schema_id, payload = params
        for layer_index, digest, members in json.loads(payload):
            key = (schema_id, layer_index, digest)
            if key not in self.db.tables["components"]:
                self.db.tables["components"][key] = {
                    "component_id": self.db._next("component"), "members": members,
                }
        return []

    def _select_components(self, sql, params):
        schema_id, digests = params
        return [
            {"layer_index": layer_index, "members_hash": digest, "component_id": row["component_id"]}
            for (sid, layer_index, digest), row in self.db.tables["components"].items()
            if sid == schema_id and digest in digests
        ]

    # -- Netzwerke und Strukturen -------------------------------------------

    def _insert_network(self, sql, params):
        name, network_type, organism, description, node_count, edge_count = params
        network_id = self.db._next("network")
        self.db.tables["networks"][network_id] = {
            "network_id": network_id, "name": name, "network_type": network_type,
            "organism": organism, "description": description, "node_count": node_count,
            "edge_count": edge_count, "created_at": self.db.CREATED_AT,
        }
        return [{"network_id": network_id}]

    def _insert_structure(self, sql, params):
        network_id, schema_id, length, entity_names, layers, signature_hash = params
        self.db.tables["structures"][network_id] = {
            "schema_id": schema_id, "length": length, "entity_names": list(entity_names),
            "layers": json.loads(layers), "signature_hash": signature_hash,
        }
        return []

    def _insert_pairs(self, sql, params):
        schema_id, network_id, length, layer_indices, kinds, firsts, seconds = params
        for layer_index, kind, first, second in zip(layer_indices, kinds, firsts, seconds):
            self.db.tables["pairs"].append({
                "schema_id": schema_id, "layer_index": layer_index, "kind": kind,
                "first_id": first, "second_id": second, "network_id": network_id, "length": length,
            })
        return []

    def _select_structure(self, sql, params):
        (network_id,) = params
        tables = self.db.tables
        network, structure = tables["networks"].get(network_id), tables["structures"].get(network_id)
        if network is None or structure is None:
            return []
        schema = tables["schemas"][structure["schema_id"]]
        return [{
            **network,
            "length": structure["length"], "entity_names": structure["entity_names"],
            "layers": structure["layers"], "signature_hash": structure["signature_hash"],
            "schema_name": schema["name"], "schema_version": schema["version"],
            "definition": schema["definition"],
        }]

    # -- Suche --------------------------------------------------------------

    def _select_candidates(self, sql, params):
        schema_id, layer_index, minimum_length, pairs = params
        wanted = {tuple(pair) for pair in pairs}
        reached = {
            row["network_id"] for row in self.db.tables["pairs"]
            if row["schema_id"] == schema_id and row["layer_index"] == layer_index
            and row["kind"] == "cyc" and row["length"] >= minimum_length
            and (row["first_id"], row["second_id"]) in wanted
        }
        return [{"network_id": network_id} for network_id in sorted(reached)]

    def _select_matches(self, sql, params):
        (network_ids,) = params
        tables = self.db.tables
        rows = [
            {**tables["networks"][network_id], "layers": tables["structures"][network_id]["layers"]}
            for network_id in network_ids
        ]
        return sorted(rows, key=lambda row: (row["node_count"], row["network_id"]))

    HANDLERS = [
        ("SELECT schema_id, definition FROM universal_schemas", _select_schema),
        ("INSERT INTO universal_schemas", _insert_schema),
        ("INSERT INTO entity_register", _insert_entities),
        ("SELECT entity, coordinate FROM entity_register", _select_entities),
        ("SELECT COALESCE(MAX(coordinate), -1) + 1 AS next_free", _select_next_free),
        ("INSERT INTO universal_components", _insert_components),
        ("SELECT layer_index, members_hash, component_id FROM universal_components", _select_components),
        ("INSERT INTO biological_networks", _insert_network),
        ("INSERT INTO universal_structures", _insert_structure),
        ("INSERT INTO universal_pairs", _insert_pairs),
        ("SELECT bn.*, us.length", _select_structure),
        ("SELECT DISTINCT network_id FROM universal_pairs", _select_candidates),
        ("SELECT bn.network_id, bn.name", _select_matches),
    ]


@pytest.fixture
def bare_db(monkeypatch):
    """Leere In-Memory-Datenbank ohne registrierte Schemata."""
    database = FakeUniversalDatabase()
    monkeypatch.setattr(crud, "get_db_connection", database.connection)
    monkeypatch.setattr(crud, "get_db_cursor", database.cursor)
    return database


@pytest.fixture
def db(bare_db):
    """In-Memory-Datenbank mit den registrierten Schemata GENE, COMPLEX und MATRIX."""
    for schema in (GENE, COMPLEX, MATRIX):
        crud.register_universal_schema(schema)
    bare_db.executed.clear()
    return bare_db


def create(name, entities, relations=None, schema_name=GENE.name, **options):
    return crud.create_universal_structure(
        schema_name, name, "regulatory", "Homo sapiens", f"{name} description",
        entities, relations, **options,
    )


def add_chain(names=("a", "b", "c"), name="chain"):
    """Kette n0 -> n1 -> ... mit Merkmal 'kinase' am ersten Knoten."""
    entities = {names[0]: ["kinase"], **{entity: [] for entity in names[1:]}}
    relations = {"regulates": list(zip(names, names[1:]))}
    return create(name, entities, relations)


def search(entities, relations=None, **options):
    return crud.search_universal(GENE.name, entities, relations, **options)


class TestHashes:
    def test_component_hash_is_sha256_of_sorted_members(self):
        assert crud.component_hash({3, 1, 2}) == hashlib.sha256(b"1,2,3").hexdigest()

    def test_component_hash_of_empty_component(self):
        assert crud.component_hash(frozenset()) == hashlib.sha256(b"").hexdigest()

    def test_component_hash_distinguishes_components(self):
        assert crud.component_hash({1, 2}) != crud.component_hash({12})
        assert crud.component_hash({1}) != crud.component_hash({2})

    def test_stack_signature_hash_is_sha256_of_the_json_lists(self):
        stack = Stack.of([[{2, 1}, set()]])
        assert crud.stack_signature_hash(stack) == hashlib.sha256(b"[[[1,2],[]]]").hexdigest()

    def test_stack_signature_hash_depends_on_the_stack(self):
        assert crud.stack_signature_hash(Stack.of([[{1}]])) != crud.stack_signature_hash(Stack.of([[{2}]]))


class TestRegisterUniversalSchema:
    def test_new_schema_gets_an_id_and_is_stored(self, bare_db):
        assert crud.register_universal_schema(GENE) == 1
        stored = bare_db.tables["schemas"][1]
        assert (stored["name"], stored["version"], stored["layer_count"]) == ("gene-regulation", 1, 3)
        assert Schema.from_dict(stored["definition"]) == GENE

    def test_registration_is_idempotent(self, bare_db):
        first = crud.register_universal_schema(GENE)
        second = crud.register_universal_schema(Schema.from_dict(GENE.to_dict()))
        assert first == second
        assert len(bare_db.statements("INSERT INTO universal_schemas")) == 1

    def test_same_name_and_version_with_other_definition_is_rejected(self, bare_db):
        crud.register_universal_schema(GENE)
        changed = Schema(name=GENE.name, features=("kinase", "receptor"), relations=GENE.relations)
        with pytest.raises(ValueError, match="already registered with a different definition"):
            crud.register_universal_schema(changed)
        assert len(bare_db.tables["schemas"]) == 1

    def test_new_version_is_a_new_schema(self, bare_db):
        first = crud.register_universal_schema(GENE)
        second = crud.register_universal_schema(
            Schema(name=GENE.name, version=2, features=GENE.features, relations=GENE.relations)
        )
        assert second != first


class TestGetUniversalSchema:
    def test_found(self, db):
        assert crud.get_universal_schema("gene-regulation") == GENE

    def test_without_version_the_latest_is_returned(self, db):
        newer = Schema(name=GENE.name, version=3, features=("kinase", "receptor"),
                       relations=GENE.relations)
        crud.register_universal_schema(newer)
        assert crud.get_universal_schema(GENE.name) == newer

    def test_explicit_version(self, db):
        crud.register_universal_schema(
            Schema(name=GENE.name, version=2, features=(), relations=GENE.relations)
        )
        assert crud.get_universal_schema(GENE.name, 1) == GENE
        assert crud.get_universal_schema(GENE.name, 2).version == 2

    def test_unknown_name_or_version(self, db):
        assert crud.get_universal_schema("nope") is None
        assert crud.get_universal_schema(GENE.name, 9) is None


class TestCreateUniversalStructure:
    def test_returns_creation_result(self, db):
        result = add_chain()
        assert isinstance(result, UniversalStructureCreationResult)
        assert (result.network_id, result.name) == (1, "chain")
        assert (result.network_type, result.organism) == ("regulatory", "Homo sapiens")
        assert result.description == "chain description"
        assert (result.schema_name, result.schema_version) == ("gene-regulation", 1)
        assert (result.node_count, result.edge_count, result.length) == (3, 2, 3)
        assert len(result.signature_hash) == 64

    def test_stores_the_encoded_stack(self, db):
        result = add_chain()
        expected = [
            [[1], [2], [3]],       # ex
            [[1], [], []],         # lab:kinase
            [[], [1], [2]],        # bin:regulates:1
        ]
        stored = db.tables["structures"][1]
        assert stored["layers"] == expected
        assert stored["length"] == 3
        assert stored["entity_names"] == ["a", "b", "c"]
        assert stored["signature_hash"] == result.signature_hash == \
            crud.stack_signature_hash(Stack.of(expected))

    def test_stores_network_metadata(self, db):
        add_chain()
        row = db.tables["networks"][1]
        assert (row["name"], row["node_count"], row["edge_count"]) == ("chain", 3, 2)

    def test_edge_count_sums_all_relation_tuples(self, db):
        result = create(
            "mixed", ["a", "b", "c"],
            {"regulates": {("a", "b"): 2, ("b", "c"): 1}, "complex": [("a", "b", "c")]},
            schema_name=COMPLEX.name,
        )
        assert (result.node_count, result.edge_count) == (3, 3)
        assert result.length == 4  # drei Entitäten und ein Relationsknoten

    def test_entities_receive_register_coordinates_in_order_of_appearance(self, db):
        add_chain(("a", "b", "c"))
        assert db.tables["entities"] == {"a": 1, "b": 2, "c": 3}

    def test_existing_coordinates_never_change(self, db):
        add_chain(("a", "b", "c"), name="first")
        add_chain(("z", "a", "d"), name="second")
        entities = db.tables["entities"]
        assert (entities["a"], entities["b"], entities["c"]) == (1, 2, 3)
        assert entities["z"] > 3 and entities["d"] > 3 and entities["z"] != entities["d"]

    def test_columns_follow_the_coordinates_not_the_input_order(self, db):
        add_chain(("a", "b", "c"), name="first")
        result = create("second", ["c", "a"], {"regulates": [("c", "a")]})
        assert db.tables["structures"][result.network_id]["entity_names"] == ["a", "c"]

    def test_components_are_shared_between_structures(self, db):
        add_chain(("a", "b", "c"), name="first")
        before = len(db.tables["components"])
        add_chain(("a", "b", "c"), name="second")
        assert len(db.tables["components"]) == before

    def test_pairs_of_all_layers_are_indexed(self, db):
        add_chain()
        rows = db.tables["pairs"]
        assert len(rows) == 15
        for kind, expected in (("cyc", 9), ("lin", 6)):
            assert sum(1 for row in rows if row["kind"] == kind) == expected
        assert {row["length"] for row in rows} == {3}
        assert {row["network_id"] for row in rows} == {1}
        assert {row["layer_index"] for row in rows} == {0, 1, 2}

    def test_pair_ids_refer_to_the_dictionary(self, db):
        add_chain()
        known = {row["component_id"] for row in db.tables["components"].values()}
        for row in db.tables["pairs"]:
            assert {row["first_id"], row["second_id"]} <= known

    def test_empty_structure_has_no_pairs(self, db):
        result = create("empty", [])
        assert (result.node_count, result.edge_count, result.length) == (0, 0, 0)
        assert db.tables["pairs"] == [] and db.statements("INSERT INTO universal_pairs") == []
        assert db.statements("INSERT INTO entity_register") == []

    def test_single_entity_has_no_pairs(self, db):
        result = create("single", {"a": ["kinase"]})
        assert result.length == 1
        assert db.statements("INSERT INTO universal_pairs") == []

    def test_local_coordinates_do_not_touch_the_register(self, db):
        result = create(
            "omics", ["g0", "g1", "g2"],
            {"t": [("g0", "g1"), ("g1", "g2")], "p": [("g1", "g0")]}, schema_name=MATRIX.name,
        )
        assert db.tables["entities"] == {}
        assert db.tables["structures"][result.network_id]["layers"][0] == [[0], [1], [2]]
        assert db.statements("INSERT INTO entity_register") == []

    def test_schema_version_selects_the_schema(self, db):
        crud.register_universal_schema(
            Schema(name=GENE.name, version=2, features=(), relations=GENE.relations)
        )
        latest = create("latest", ["a", "b"], {"regulates": [("a", "b")]})
        older = create("older", {"a": ["kinase"]}, schema_version=1)
        assert latest.schema_version == 2 and older.schema_version == 1
        assert len(db.tables["structures"][latest.network_id]["layers"]) == 2
        assert len(db.tables["structures"][older.network_id]["layers"]) == 3

    def test_unknown_schema(self, db):
        with pytest.raises(ValueError, match="unknown schema 'nope'$"):
            create("x", ["a"], schema_name="nope")

    def test_unknown_schema_version(self, db):
        with pytest.raises(ValueError, match="unknown schema 'gene-regulation' version 9"):
            create("x", ["a"], schema_version=9)

    def test_invalid_structure_changes_nothing(self, db):
        with pytest.raises(ValueError, match="unknown entities"):
            create("bad", ["a"], {"regulates": [("a", "ghost")]})
        assert db.tables["networks"] == {} and db.tables["entities"] == {}
        assert db.statements("INSERT") == []

    def test_failure_rolls_back_the_whole_transaction(self, db, monkeypatch):
        def _boom(*args):
            raise RuntimeError("Datenbank weg")

        monkeypatch.setattr(crud, "_pair_columns", _boom)
        with pytest.raises(RuntimeError):
            add_chain()
        tables = db.tables
        assert tables["networks"] == {} and tables["structures"] == {}
        assert tables["entities"] == {} and tables["components"] == {}


class TestGetUniversalStructureById:
    def test_round_trip(self, db):
        entities = {"a": ["kinase"], "b": [], "c": []}
        relations = {"regulates": [("a", "b"), ("b", "c")]}
        created = create("chain", entities, relations)

        record = crud.get_universal_structure_by_id(created.network_id)

        assert isinstance(record, UniversalStructureRecord)
        assert record.structure == Structure.build(GENE, entities, relations)
        assert record.entity_names == ["a", "b", "c"]
        assert (record.name, record.network_type, record.organism) == ("chain", "regulatory", "Homo sapiens")
        assert record.description == "chain description"
        assert (record.schema_name, record.schema_version) == ("gene-regulation", 1)
        assert (record.node_count, record.edge_count, record.length) == (3, 2, 3)
        assert record.signature_hash == created.signature_hash
        assert record.created_at == FakeUniversalDatabase.CREATED_AT

    def test_round_trip_with_weights_and_general_relations(self, db):
        entities = {"a": ["kinase"], "b": [], "c": []}
        relations = {
            "regulates": {("a", "b"): 2, ("c", "a"): 1},
            "complex": {("a", "b", "c"): 2, ("c", "c", "a"): 1},
        }
        created = create("rich", entities, relations, schema_name=COMPLEX.name)
        record = crud.get_universal_structure_by_id(created.network_id)
        assert record.structure == Structure.build(COMPLEX, entities, relations)

    def test_round_trip_with_local_coordinates(self, db):
        relations = {"t": [("g0", "g1")], "p": [("g1", "g2"), ("g2", "g0")]}
        created = create("omics", ["g0", "g1", "g2"], relations, schema_name=MATRIX.name)
        record = crud.get_universal_structure_by_id(created.network_id)
        assert record.structure == Structure.build(MATRIX, ["g0", "g1", "g2"], relations)
        assert record.entity_names == ["g0", "g1", "g2"]

    def test_round_trip_of_the_empty_structure(self, db):
        created = create("empty", [])
        record = crud.get_universal_structure_by_id(created.network_id)
        assert record.structure.entities == {} and record.entity_names == []

    def test_unknown_id(self, db):
        assert crud.get_universal_structure_by_id(99) is None

    def test_network_without_stack_is_not_found(self, db):
        db.tables["networks"][7] = {
            "network_id": 7, "name": "plain", "network_type": "metabolic", "organism": "x",
            "description": "", "node_count": 3, "edge_count": 2, "created_at": None,
        }
        assert crud.get_universal_structure_by_id(7) is None

    def test_missing_creation_time(self, db):
        created = add_chain()
        db.tables["networks"][created.network_id]["created_at"] = None
        assert crud.get_universal_structure_by_id(created.network_id).created_at is None

    def test_missing_signature_hash(self, db):
        created = add_chain()
        db.tables["structures"][created.network_id]["signature_hash"] = None
        assert crud.get_universal_structure_by_id(created.network_id).signature_hash is None

    def test_corrupt_stack_is_rejected(self, db):
        created = add_chain()
        db.tables["structures"][created.network_id]["layers"][1][2] = [1]  # Merkmal an Spalte c
        with pytest.raises(ValueError, match="not the image"):
            crud.get_universal_structure_by_id(created.network_id)


class TestSearchUniversal:
    @pytest.fixture
    def corpus(self, db):
        """chain a->b->c, longer a->b->c->d, unrelated x->y->z."""
        add_chain(("a", "b", "c"), name="chain")
        add_chain(("a", "b", "c", "d"), name="longer")
        add_chain(("x", "y", "z"), name="unrelated")
        db.executed.clear()
        return db

    def test_finds_structures_containing_the_query(self, corpus):
        matches = search(["a", "b"], {"regulates": [("a", "b")]})
        assert [match.name for match in matches] == ["chain", "longer"]
        assert all(isinstance(match, UniversalSearchMatch) for match in matches)

    def test_match_fields(self, corpus):
        match = search(["a", "b"], {"regulates": [("a", "b")]})[0]
        assert match.network_id == 1
        assert (match.network_type, match.organism) == ("regulatory", "Homo sapiens")
        assert (match.node_count, match.edge_count) == (3, 2)
        assert (match.schema_name, match.schema_version) == ("gene-regulation", 1)
        assert match.layers == ["bin:regulates:1"]
        assert match.mode == "coherent"
        assert (match.match_type, match.subgraph_result) == ("subgraph", "keep_B")

    def test_identical_structure_is_an_exact_match(self, corpus):
        matches = search(["a", "b", "c"], {"regulates": [("a", "b"), ("b", "c")]})
        assert [(m.name, m.match_type, m.subgraph_result) for m in matches] == [
            ("chain", "exact", "equal_keep_A"),
            ("longer", "subgraph", "keep_B"),
        ]

    def test_results_are_sorted_by_size_then_id(self, db):
        add_chain(("a", "b", "c", "d"), name="big")
        add_chain(("a", "b"), name="small")
        add_chain(("a", "b"), name="small-too")
        matches = search(["a", "b"], {"regulates": [("a", "b")]})
        assert [m.name for m in matches] == ["small", "small-too", "big"]

    def test_unrelated_structures_are_not_candidates(self, corpus):
        names = [m.name for m in search(["a", "b"], {"regulates": [("a", "b")]})]
        assert "unrelated" not in names

    def test_reads_only_the_cyclic_lists_of_the_query_pairs(self, corpus):
        search(["a", "b", "c"], {"regulates": [("a", "b"), ("b", "c")]})
        (statement, params), = [
            item for item in corpus.executed if item[0].startswith("SELECT DISTINCT network_id")
        ]
        assert "kind = 'cyc'" in statement and "length >= %s" in statement
        schema_id, layer_index, minimum_length, pairs = params
        assert (schema_id, layer_index, minimum_length) == (1, 2, 3)
        assert len(pairs) == 2 and pairs == tuple(sorted(pairs))

    def test_unknown_entity_as_source_cannot_match(self, corpus):
        matches = search(["a", "ghost"], {"regulates": [("ghost", "a")]})
        assert matches == []

    def test_unknown_entities_are_never_registered(self, corpus):
        search(["a", "ghost"], {"regulates": [("ghost", "a")]})
        assert "ghost" not in corpus.tables["entities"]

    def test_unknown_entity_without_own_edges_is_shape_only(self, corpus):
        # d ist unbekannt, taucht aber nur als Senke auf: die aktive Schicht kennt nur a und b
        matches = search(["a", "b", "d"], {"regulates": [("a", "b"), ("b", "d")]})
        assert [(m.name, m.subgraph_result) for m in matches] == [
            ("chain", "equal_keep_A"), ("longer", "keep_B"),
        ]

    def test_no_candidates_means_no_further_queries(self, corpus):
        assert search(["x", "q"], {"regulates": [("q", "x")]}) == []
        assert not corpus.statements("SELECT bn.network_id")

    def test_query_without_pairs_matches_nothing(self, corpus):
        assert search({"a": ["kinase"]}) == []

    def test_query_without_entities_has_no_active_layer(self, corpus):
        with pytest.raises(ValueError, match="no non-empty layer"):
            search([])
        assert corpus.statements("SELECT entity, coordinate") == []

    def test_layers_by_name(self, corpus):
        matches = search({"a": ["kinase"], "b": []}, {"regulates": [("a", "b")]},
                         layers=["lab:kinase", "bin:regulates:1"], mode="independent")
        assert [m.layers for m in matches] == [["lab:kinase", "bin:regulates:1"]] * 2

    def test_layers_by_index(self, corpus):
        matches = search(["a", "b"], {"regulates": [("a", "b")]}, layers=[2])
        assert [m.layers for m in matches] == [["bin:regulates:1"]] * 2

    def test_existence_layer_on_request(self, corpus):
        matches = search(["a", "b"], {"regulates": [("a", "b")]}, include_existence=True)
        assert [m.layers for m in matches] == [["ex", "bin:regulates:1"]] * 2

    def test_existence_layer_makes_the_entities_matter(self, corpus):
        assert search(["a", "ghost"], {"regulates": [("a", "ghost")]}, include_existence=True) == []

    def test_schema_version_selects_the_schema(self, corpus):
        assert search(["a", "b"], {"regulates": [("a", "b")]}, schema_version=1)
        with pytest.raises(ValueError, match="version 4"):
            search(["a", "b"], {"regulates": [("a", "b")]}, schema_version=4)

    def test_invalid_mode_is_rejected_before_any_database_access(self, corpus):
        with pytest.raises(ValueError, match="unknown mode 'weird'"):
            search(["a", "b"], {"regulates": [("a", "b")]}, mode="weird")
        assert corpus.executed == []

    def test_unknown_schema(self, corpus):
        with pytest.raises(ValueError, match="unknown schema 'nope'"):
            crud.search_universal("nope", ["a"])

    def test_query_without_active_layer(self, corpus):
        with pytest.raises(ValueError, match="no non-empty layer"):
            search(["a", "b"])

    def test_invalid_query(self, corpus):
        with pytest.raises(ValueError, match="unknown features"):
            search({"a": ["phosphatase"]})

    def test_invalid_layer_selection(self, corpus):
        with pytest.raises(ValueError, match="unknown layer 'lab:nothing'"):
            search(["a", "b"], {"regulates": [("a", "b")]}, layers=["lab:nothing"])


class TestSearchModes:
    """Zwei Schichten, deren Paare in der gespeicherten Struktur an verschiedenen Positionen liegen."""

    @pytest.fixture
    def shifted(self, db):
        create(
            "stored", ["g0", "g1", "g2"],
            {"t": [("g0", "g1"), ("g1", "g2")], "p": [("g1", "g0"), ("g0", "g2")]},
            schema_name=MATRIX.name,
        )
        db.executed.clear()
        return db

    @staticmethod
    def query(mode):
        return crud.search_universal(
            MATRIX.name, ["q0", "q1"],
            {"t": [("q0", "q1")], "p": [("q0", "q1")]}, mode=mode,
        )

    def test_independent_mode_accepts_each_layer_at_its_own_position(self, shifted):
        matches = self.query("independent")
        assert [(m.name, m.mode, m.subgraph_result) for m in matches] == \
            [("stored", "independent", "keep_B")]
        assert matches[0].layers == ["bin:t:1", "bin:p:1"]

    def test_coherent_mode_verifies_the_candidates(self, shifted):
        assert self.query("coherent") == []
        # der Kandidat wurde gelesen und erst bei der kohärenten Prüfung verworfen
        assert shifted.statements("SELECT bn.network_id")

    def test_local_coordinates_are_used_for_the_query(self, shifted):
        assert self.query("independent")[0].network_id == 1
        assert shifted.statements("SELECT entity, coordinate") == []

    def test_matrix_structure_found_by_its_own_stack(self, db):
        relations = {"t": [("a", "b"), ("b", "c")], "p": [("c", "a")]}
        create("same", ["a", "b", "c"], relations, schema_name=MATRIX.name)
        matches = crud.search_universal(MATRIX.name, ["a", "b", "c"], relations)
        assert [(m.name, m.match_type) for m in matches] == [("same", "exact")]
