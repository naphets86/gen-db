"""
Tests für die Multi-Omics-Endpoints in app.py

Die CRUD-Funktionen werden durch Fakes ersetzt; geprüft werden Request-Validierung,
Mapping der Domain Models auf die Response Schemas und die Fehlerbehandlung.
"""
import pytest
from fastapi.testclient import TestClient

from backend import crud
from backend.app import app
from backend.models import (
    MultiOmicsCreationResult, MultiOmicsNetwork, MultiOmicsSearchMatch, OmicsLayer
)

TRANSCRIPTOME = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
PROTEOME = [[0, 1, 0], [1, 0, 0], [0, 0, 0]]
LAYERS = [
    {"layer_name": "transcriptome", "adjacency_matrix": TRANSCRIPTOME},
    {"layer_name": "proteome", "adjacency_matrix": PROTEOME},
]
CREATE_BODY = {
    "name": "TP53 Multi-Omics", "organism": "Human",
    "node_labels": ["TP53", "MDM2", "ATM"], "layers": LAYERS,
}
SEARCH_BODY = {"node_labels": ["TP53", "MDM2", "ATM"], "layers": LAYERS}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.unit
class TestCreateMultiOmics:
    def test_create(self, client, monkeypatch):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return MultiOmicsCreationResult(
                network_id=3, name=kwargs["name"], network_type=kwargs["network_type"],
                organism=kwargs["organism"], description=kwargs["description"], node_count=3,
                edge_count=4, layer_names=kwargs["layer_names"], signature_hash="h" * 64,
            )

        monkeypatch.setattr(crud, "create_multiomics_network", _create)
        response = client.post("/api/multiomics", json=CREATE_BODY)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["network_id"] == 3
        assert data["layer_names"] == ["transcriptome", "proteome"]
        assert data["network_type"] == "multi_omics"
        assert captured["layer_matrices"] == [TRANSCRIPTOME, PROTEOME]
        assert captured["description"] == ""

    def test_invalid_input_is_422(self, client, monkeypatch):
        def _create(**kwargs):
            raise ValueError("layer names must be unique")

        monkeypatch.setattr(crud, "create_multiomics_network", _create)
        response = client.post("/api/multiomics", json=CREATE_BODY)
        assert response.status_code == 422
        assert "unique" in response.json()["detail"]

    def test_database_error_is_500(self, client, monkeypatch):
        def _create(**kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(crud, "create_multiomics_network", _create)
        assert client.post("/api/multiomics", json=CREATE_BODY).status_code == 500

    def test_schema_requires_at_least_one_layer(self, client):
        assert client.post("/api/multiomics", json={**CREATE_BODY, "layers": []}).status_code == 422


@pytest.mark.unit
class TestGetMultiOmics:
    def test_found(self, client, monkeypatch):
        network = MultiOmicsNetwork(
            network_id=3, name="n", network_type="multi_omics", organism="Human", description="d",
            node_labels=["a", "b", "c"], node_count=3, edge_count=4,
            layers=[OmicsLayer("transcriptome", TRANSCRIPTOME, 2), OmicsLayer("proteome", PROTEOME, 2)],
            created_at="2026-10-08",
        )
        monkeypatch.setattr(crud, "get_multiomics_network_by_id", lambda network_id: network)
        response = client.get("/api/multiomics/3")
        assert response.status_code == 200
        data = response.json()["data"]
        assert [layer["layer_name"] for layer in data["layers"]] == ["transcriptome", "proteome"]
        assert data["layers"][0]["adjacency_matrix"] == TRANSCRIPTOME

    def test_not_found(self, client, monkeypatch):
        monkeypatch.setattr(crud, "get_multiomics_network_by_id", lambda network_id: None)
        assert client.get("/api/multiomics/99").status_code == 404

    def test_error_is_500(self, client, monkeypatch):
        def _get(network_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(crud, "get_multiomics_network_by_id", _get)
        assert client.get("/api/multiomics/1").status_code == 500


@pytest.mark.unit
class TestSearchMultiOmics:
    def _match(self, network_id=1, match_type="subgraph", mode="coherent"):
        return MultiOmicsSearchMatch(
            network_id=network_id, name="n", network_type="multi_omics", organism="Human",
            node_count=4, edge_count=6, node_labels=["a", "b", "c", "d"],
            layer_names=["transcriptome", "proteome"], mode=mode, match_type=match_type,
            subgraph_result="keep_B",
        )

    def test_search_returns_matches(self, client, monkeypatch):
        captured = {}

        def _search(**kwargs):
            captured.update(kwargs)
            return [self._match(1), self._match(2, "exact")]

        monkeypatch.setattr(crud, "search_multiomics", _search)
        response = client.post("/api/multiomics/search", json=SEARCH_BODY)
        assert response.status_code == 200
        data = response.json()["data"]
        assert [m["network_id"] for m in data] == [1, 2]
        assert data[1]["match_type"] == "exact"
        assert data[0]["layer_names"] == ["transcriptome", "proteome"]
        assert captured["mode"] == "coherent"
        assert captured["layer_names"] == ["transcriptome", "proteome"]

    def test_mode_is_passed(self, client, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            crud, "search_multiomics", lambda **kwargs: captured.update(kwargs) or []
        )
        response = client.post("/api/multiomics/search", json={**SEARCH_BODY, "mode": "independent"})
        assert response.status_code == 200 and response.json()["data"] == []
        assert captured["mode"] == "independent"

    def test_unknown_mode_is_rejected_by_schema(self, client):
        assert client.post("/api/multiomics/search", json={**SEARCH_BODY, "mode": "weird"}).status_code == 422

    def test_invalid_input_is_422(self, client, monkeypatch):
        def _search(**kwargs):
            raise ValueError("number of node labels must equal the size of the adjacency matrices")

        monkeypatch.setattr(crud, "search_multiomics", _search)
        response = client.post("/api/multiomics/search", json=SEARCH_BODY)
        assert response.status_code == 422
        assert "node labels" in response.json()["detail"]

    def test_error_is_500(self, client, monkeypatch):
        def _search(**kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(crud, "search_multiomics", _search)
        assert client.post("/api/multiomics/search", json=SEARCH_BODY).status_code == 500
