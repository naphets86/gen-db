"""
Tests der universellen Kodierung gegen die isolierte PostgreSQL-Testdatenbank

Die Tabellen entstehen aus dem universellen Abschnitt von init-db.sql (Tabellen und Indizes
zwischen entity_register und den Beispieldaten), damit das ausgelieferte Schema selbst getestet
wird. Geprüft wird, was die In-Memory-Datenbank in test_universal_crud.py nicht belegen kann:
das SQL (Konfliktbehandlung beim Register, Zeilenvergleich ``(a, b) IN ...``, ``unnest``),
Fremdschlüssel mit CASCADE und die Transaktion.
"""

from pathlib import Path

import pytest

from backend import crud
from backend.universal_schema import RelationType, Schema, Structure, matrix_schema

pytestmark = pytest.mark.db

INIT_SQL = Path(__file__).resolve().parent.parent / "init-db.sql"
UNIVERSAL_TABLES = (
    "universal_pairs", "universal_components", "universal_structures",
    "universal_schemas", "entity_register",
)

GENE = Schema(
    name="gene-regulation",
    features=("kinase",),
    relations=(RelationType("regulates", 2, 2), RelationType("complex", 3, 2)),
)
MATRIX = matrix_schema(["t", "p"], name="omics")


def _universal_ddl() -> str:
    text = INIT_SQL.read_text(encoding="utf-8")
    start = text.index("CREATE TABLE IF NOT EXISTS entity_register")
    end = text.index("INSERT INTO biological_networks")
    return text[start:end]


@pytest.fixture(scope="module", autouse=True)
def universal_tables(setup_test_database, db_connection):
    """Legt die universellen Tabellen aus init-db.sql in der Testdatenbank an."""
    drop = f"DROP TABLE IF EXISTS {', '.join(UNIVERSAL_TABLES)} CASCADE"
    with db_connection.cursor() as cursor:
        cursor.execute(drop)
        cursor.execute(_universal_ddl())
    db_connection.commit()
    yield
    with db_connection.cursor() as cursor:
        cursor.execute(drop)
    db_connection.commit()


@pytest.fixture
def clean_universal(db_connection):
    truncate = (
        f"TRUNCATE TABLE {', '.join(UNIVERSAL_TABLES)}, biological_networks "
        "RESTART IDENTITY CASCADE"
    )

    def wipe():
        with db_connection.cursor() as cursor:
            cursor.execute(truncate)
        db_connection.commit()

    wipe()
    yield db_connection
    wipe()


def _count(connection, table, where="", params=()):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table} {where}", params)
        count = cursor.fetchone()[0]
    connection.commit()  # keine Lesetransaktion offen lassen
    return count


def _chain(names, name):
    entities = {names[0]: ["kinase"], **{entity: [] for entity in names[1:]}}
    return crud.create_universal_structure(
        GENE.name, name, "regulatory", "Homo sapiens", "", entities,
        {"regulates": list(zip(names, names[1:]))},
    )


class TestInitDbSchema:
    def test_all_universal_tables_exist(self, clean_universal):
        with clean_universal.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
                (list(UNIVERSAL_TABLES),),
            )
            found = {row[0] for row in cursor.fetchall()}
        clean_universal.commit()
        assert found == set(UNIVERSAL_TABLES)


class TestSchemas:
    def test_register_and_load(self, clean_universal):
        schema_id = crud.register_universal_schema(GENE)
        assert crud.register_universal_schema(GENE) == schema_id
        assert crud.get_universal_schema(GENE.name) == GENE
        assert _count(clean_universal, "universal_schemas") == 1

    def test_conflicting_definition_is_rejected(self, clean_universal):
        crud.register_universal_schema(GENE)
        other = Schema(name=GENE.name, features=(), relations=GENE.relations)
        with pytest.raises(ValueError, match="different definition"):
            crud.register_universal_schema(other)

    def test_latest_version_is_the_default(self, clean_universal):
        crud.register_universal_schema(GENE)
        newer = Schema(name=GENE.name, version=2, features=GENE.features, relations=GENE.relations)
        crud.register_universal_schema(newer)
        assert crud.get_universal_schema(GENE.name).version == 2
        assert crud.get_universal_schema(GENE.name, 1).version == 1
        assert crud.get_universal_schema("nope") is None


class TestCreateAndGet:
    def test_round_trip(self, clean_universal):
        crud.register_universal_schema(GENE)
        entities = {"a": ["kinase"], "b": [], "c": []}
        relations = {
            "regulates": {("a", "b"): 2, ("c", "a"): 1},
            "complex": {("a", "b", "c"): 2, ("c", "c", "a"): 1},
        }
        created = crud.create_universal_structure(
            GENE.name, "rich", "regulatory", "Homo sapiens", "d", entities, relations
        )
        assert (created.node_count, created.edge_count, created.length) == (3, 4, 5)

        record = crud.get_universal_structure_by_id(created.network_id)
        assert record.structure == Structure.build(GENE, entities, relations)
        assert record.entity_names == ["a", "b", "c"]
        assert record.signature_hash == created.signature_hash
        assert record.created_at is not None

    def test_local_coordinates_round_trip(self, clean_universal):
        crud.register_universal_schema(MATRIX)
        relations = {"t": [("g0", "g1")], "p": [("g1", "g2"), ("g2", "g0")]}
        created = crud.create_universal_structure(
            MATRIX.name, "omics", "multi_omics", "Test", "", ["g0", "g1", "g2"], relations
        )
        record = crud.get_universal_structure_by_id(created.network_id)
        assert record.structure == Structure.build(MATRIX, ["g0", "g1", "g2"], relations)
        assert _count(clean_universal, "entity_register") == 0

    @staticmethod
    def _register(connection):
        with connection.cursor() as cursor:
            cursor.execute("SELECT entity, coordinate FROM entity_register")
            rows = dict(cursor.fetchall())
        connection.commit()
        return rows

    def test_register_coordinates_are_stable(self, clean_universal):
        crud.register_universal_schema(GENE)
        _chain(("a", "b", "c"), "first")
        before = self._register(clean_universal)
        _chain(("z", "a", "d"), "second")
        after = self._register(clean_universal)
        assert {entity: after[entity] for entity in before} == before
        assert len(after) == 5 and len(set(after.values())) == 5

    def test_unknown_id(self, clean_universal):
        assert crud.get_universal_structure_by_id(424242) is None

    def test_index_rows_are_written(self, clean_universal):
        crud.register_universal_schema(GENE)
        created = _chain(("a", "b", "c"), "chain")
        pairs = _count(clean_universal, "universal_pairs", "WHERE network_id = %s", (created.network_id,))
        assert pairs > 0
        assert _count(clean_universal, "universal_pairs",
                      "WHERE network_id = %s AND kind = 'cyc'", (created.network_id,)) > 0

    def test_failed_creation_is_rolled_back(self, clean_universal, monkeypatch):
        crud.register_universal_schema(GENE)

        def _boom(*args):
            raise RuntimeError("Datenbank weg")

        monkeypatch.setattr(crud, "_pair_columns", _boom)
        with pytest.raises(RuntimeError):
            _chain(("a", "b", "c"), "broken")
        for table in ("biological_networks", "universal_structures", "entity_register",
                      "universal_components"):
            assert _count(clean_universal, table) == 0

    def test_deleting_a_network_removes_stack_and_pairs(self, clean_universal):
        crud.register_universal_schema(GENE)
        created = _chain(("a", "b", "c"), "doomed")
        assert crud.delete_network(created.network_id) is True
        assert _count(clean_universal, "universal_structures") == 0
        assert _count(clean_universal, "universal_pairs") == 0
        assert _count(clean_universal, "universal_components") > 0  # Wörterbuch bleibt


class TestSearch:
    @pytest.fixture
    def corpus(self, clean_universal):
        crud.register_universal_schema(GENE)
        _chain(("a", "b", "c"), "chain")
        _chain(("a", "b", "c", "d"), "longer")
        _chain(("x", "y", "z"), "unrelated")
        return clean_universal

    def test_finds_structures_containing_the_query(self, corpus):
        matches = crud.search_universal(GENE.name, ["a", "b"], {"regulates": [("a", "b")]})
        assert [match.name for match in matches] == ["chain", "longer"]
        assert [match.subgraph_result for match in matches] == ["keep_B", "keep_B"]

    def test_identical_structure_is_exact(self, corpus):
        matches = crud.search_universal(
            GENE.name, ["a", "b", "c"], {"regulates": [("a", "b"), ("b", "c")]}
        )
        assert [(m.name, m.match_type) for m in matches] == [("chain", "exact"), ("longer", "subgraph")]

    def test_longer_query_excludes_shorter_structures(self, corpus):
        matches = crud.search_universal(
            GENE.name, ["a", "b", "c", "d"], {"regulates": [("a", "b"), ("b", "c"), ("c", "d")]}
        )
        assert [m.name for m in matches] == ["longer"]

    def test_unknown_entity_cannot_match(self, corpus):
        assert crud.search_universal(GENE.name, ["a", "ghost"], {"regulates": [("ghost", "a")]}) == []
        assert _count(corpus, "entity_register", "WHERE entity = 'ghost'") == 0

    def test_weights_and_features_take_part(self, corpus):
        matches = crud.search_universal(
            GENE.name, {"a": ["kinase"], "b": []}, {"regulates": [("a", "b")]},
            layers=["lab:kinase", "bin:regulates:1"], mode="independent",
        )
        assert [m.name for m in matches] == ["chain", "longer"]

    def test_modes_on_shifted_layers(self, clean_universal):
        crud.register_universal_schema(MATRIX)
        crud.create_universal_structure(
            MATRIX.name, "stored", "multi_omics", "Test", "", ["g0", "g1", "g2"],
            {"t": [("g0", "g1"), ("g1", "g2")], "p": [("g1", "g0"), ("g0", "g2")]},
        )
        query = {"t": [("q0", "q1")], "p": [("q0", "q1")]}
        independent = crud.search_universal(MATRIX.name, ["q0", "q1"], query, mode="independent")
        coherent = crud.search_universal(MATRIX.name, ["q0", "q1"], query, mode="coherent")
        assert [m.name for m in independent] == ["stored"]
        assert coherent == []
