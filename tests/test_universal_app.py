"""Unit tests for the universal-structure HTTP endpoints."""
import pytest
from fastapi.testclient import TestClient

from backend import crud
from backend.app import app
from backend.models import (
    UniversalSearchMatch,
    UniversalStructureCreationResult,
    UniversalStructureRecord,
)
from backend.universal_schema import RelationType, Schema, Structure


SCHEMA_BODY = {
    "name": "gene-network",
    "version": 2,
    "coordinates": "local",
    "features": ["kinase"],
    "relations": [{"name": "regulates", "arity": 2, "levels": 3}],
}
STRUCTURE_BODY = {
    "schema_name": "gene-network",
    "schema_version": 2,
    "name": "example",
    "organism": "Human",
    "entities": {"a": ["kinase"], "b": []},
    "relations": {"regulates": [{"entities": ["a", "b"], "weight": 2}]},
}
SEARCH_BODY = {
    "schema_name": "gene-network",
    "schema_version": 2,
    "entities": {"a": ["kinase"], "b": []},
    "relations": {"regulates": [{"entities": ["a", "b"], "weight": 2}]},
}


@pytest.fixture
def client():
    return TestClient(app)


def _schema():
    return Schema(
        name="gene-network",
        version=2,
        coordinates="local",
        features=("kinase",),
        relations=(RelationType("regulates", 2, 3),),
    )


@pytest.mark.unit
class TestUniversalSchemaEndpoints:
    def test_register_schema(self, client, monkeypatch):
        captured = {}

        def _register(schema):
            captured["schema"] = schema
            return 8

        monkeypatch.setattr(crud, "register_universal_schema", _register)
        response = client.post("/api/universal/schemas", json=SCHEMA_BODY)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["schema_id"] == 8
        assert data["layer_labels"] == ["ex", "lab:kinase", "bin:regulates:1", "bin:regulates:2", "bin:regulates:3"]
        assert captured["schema"] == _schema()

    def test_invalid_schema_is_rejected(self, client, monkeypatch):
        monkeypatch.setattr(crud, "register_universal_schema", lambda schema: 1)
        invalid = {**SCHEMA_BODY, "relations": [
            {"name": "bad:type", "arity": 2, "levels": 1}
        ]}
        assert client.post("/api/universal/schemas", json=invalid).status_code == 422

    def test_registration_database_error_is_500(self, client, monkeypatch):
        def _fail(schema):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(crud, "register_universal_schema", _fail)
        assert client.post("/api/universal/schemas", json=SCHEMA_BODY).status_code == 500

    def test_get_schema(self, client, monkeypatch):
        captured = {}

        def _get(name, version):
            captured.update(name=name, version=version)
            return _schema()

        monkeypatch.setattr(crud, "get_universal_schema", _get)
        response = client.get("/api/universal/schemas/gene-network?version=2")
        assert response.status_code == 200
        assert response.json()["data"]["name"] == "gene-network"
        assert captured == {"name": "gene-network", "version": 2}

    def test_unknown_schema_is_404(self, client, monkeypatch):
        monkeypatch.setattr(crud, "get_universal_schema", lambda name, version: None)
        assert client.get("/api/universal/schemas/missing").status_code == 404


@pytest.mark.unit
class TestUniversalStructureEndpoints:
    def test_create_structure_maps_entities_relations_and_metadata(self, client, monkeypatch):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return UniversalStructureCreationResult(
                network_id=12, name="example", network_type="universal", organism="Human",
                description="", schema_name="gene-network", schema_version=2,
                node_count=2, edge_count=1, length=3, signature_hash="hash",
            )

        monkeypatch.setattr(crud, "create_universal_structure", _create)
        response = client.post("/api/universal", json=STRUCTURE_BODY)

        assert response.status_code == 200
        assert response.json()["data"]["network_id"] == 12
        assert captured["entities"] == {"a": ["kinase"], "b": []}
        assert captured["relations"] == {"regulates": {("a", "b"): 2}}
        assert captured["schema_version"] == 2

    def test_invalid_structure_is_422(self, client, monkeypatch):
        def _create(**kwargs):
            raise ValueError("unknown schema")

        monkeypatch.setattr(crud, "create_universal_structure", _create)
        response = client.post("/api/universal", json=STRUCTURE_BODY)
        assert response.status_code == 422
        assert response.json()["detail"] == "unknown schema"

    def test_duplicate_relation_tuples_are_rejected(self, client, monkeypatch):
        monkeypatch.setattr(
            crud, "create_universal_structure",
            lambda **kwargs: pytest.fail("invalid duplicate tuples reached CRUD"),
        )
        duplicate = {
            **STRUCTURE_BODY,
            "relations": {
                "regulates": [
                    {"entities": ["a", "b"], "weight": 1},
                    {"entities": ["a", "b"], "weight": 2},
                ]
            },
        }
        response = client.post("/api/universal", json=duplicate)
        assert response.status_code == 422
        assert "duplicate tuple" in response.json()["detail"]

    def test_structure_database_error_is_500(self, client, monkeypatch):
        def _create(**kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(crud, "create_universal_structure", _create)
        assert client.post("/api/universal", json=STRUCTURE_BODY).status_code == 500

    def test_get_structure_serializes_features_and_relations(self, client, monkeypatch):
        schema = _schema()
        record = UniversalStructureRecord(
            network_id=12, name="example", network_type="universal", organism="Human",
            description="", schema_name=schema.name, schema_version=schema.version,
            node_count=2, edge_count=1, length=3, entity_names=["a", "b"],
            structure=Structure.build(
                schema, {"a": ["kinase"], "b": []},
                {"regulates": {("a", "b"): 2}},
            ),
            signature_hash="hash", created_at="2026-10-10",
        )
        monkeypatch.setattr(crud, "get_universal_structure_by_id", lambda network_id: record)

        response = client.get("/api/universal/12")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["entities"] == {"a": ["kinase"], "b": []}
        assert data["relations"] == {
            "regulates": [{"entities": ["a", "b"], "weight": 2}]
        }

    def test_missing_structure_is_404(self, client, monkeypatch):
        monkeypatch.setattr(crud, "get_universal_structure_by_id", lambda network_id: None)
        assert client.get("/api/universal/404").status_code == 404

    def test_structure_database_error_is_500(self, client, monkeypatch):
        def _get(network_id):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(crud, "get_universal_structure_by_id", _get)
        assert client.get("/api/universal/12").status_code == 500


@pytest.mark.unit
class TestUniversalSearchEndpoint:
    def test_search_passes_query_options_and_maps_matches(self, client, monkeypatch):
        captured = {}

        def _search(**kwargs):
            captured.update(kwargs)
            return [UniversalSearchMatch(
                network_id=12, name="example", network_type="universal", organism="Human",
                node_count=3, edge_count=2, schema_name="gene-network", schema_version=2,
                layers=["bin:regulates:2"], mode="independent", match_type="subgraph",
                subgraph_result="keep_B",
            )]

        monkeypatch.setattr(crud, "search_universal", _search)
        body = {
            **SEARCH_BODY,
            "mode": "independent",
            "layers": ["bin:regulates:2"],
            "include_existence": True,
        }
        response = client.post("/api/universal/search", json=body)

        assert response.status_code == 200
        assert response.json()["data"][0]["match_type"] == "subgraph"
        assert response.json()["data"][0]["layers"] == ["bin:regulates:2"]
        assert captured == {
            "schema_name": "gene-network",
            "schema_version": 2,
            "entities": {"a": ["kinase"], "b": []},
            "relations": {"regulates": {("a", "b"): 2}},
            "mode": "independent",
            "layers": ["bin:regulates:2"],
            "include_existence": True,
        }

    def test_search_defaults_and_empty_results(self, client, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            crud, "search_universal", lambda **kwargs: captured.update(kwargs) or []
        )
        response = client.post("/api/universal/search", json=SEARCH_BODY)

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert captured["mode"] == "coherent"
        assert captured["layers"] is None
        assert captured["include_existence"] is False

    def test_invalid_mode_is_rejected(self, client):
        assert client.post(
            "/api/universal/search", json={**SEARCH_BODY, "mode": "invalid"}
        ).status_code == 422

    def test_invalid_query_is_422(self, client, monkeypatch):
        def _search(**kwargs):
            raise ValueError("unknown layer")

        monkeypatch.setattr(crud, "search_universal", _search)
        response = client.post("/api/universal/search", json=SEARCH_BODY)
        assert response.status_code == 422

    def test_search_database_error_is_500(self, client, monkeypatch):
        def _search(**kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(crud, "search_universal", _search)
        assert client.post("/api/universal/search", json=SEARCH_BODY).status_code == 500
