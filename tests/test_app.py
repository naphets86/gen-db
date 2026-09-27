"""
Tests for app.py FastAPI application - Updated for Schemas Architecture

Changes:
- API now uses Pydantic Schemas for validation
- CRUD returns Domain Models
- Response format uses wrapper schemas (ListResponse, SingleResponse, etc.)
"""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.schemas import NetworkCreate, NetworkSearch


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.unit
class TestHealthEndpoint:

    def test_health_check(self, client):
        """Test health check endpoint"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


@pytest.mark.integration
class TestNetworkEndpoints:

    def test_get_networks_empty(self, client, clean_database, monkeypatch):
        """Test GET /api/networks with empty database"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        response = client.get("/api/networks")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 0
        assert data["count"] == 0

    def test_get_networks_multiple(self, client, clean_database, sample_network_data, monkeypatch):
        """Test GET /api/networks with multiple networks"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        # Create two networks
        response1 = client.post("/api/networks", json=sample_network_data)
        assert response1.status_code == 200

        data2 = sample_network_data.copy()
        data2['name'] = 'Network_2'
        response2 = client.post("/api/networks", json=data2)
        assert response2.status_code == 200

        # Get all networks
        response = client.get("/api/networks")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 2
        assert data["count"] == 2
        # Check response schema
        assert all('network_id' in net for net in data["data"])
        assert all('name' in net for net in data["data"])

    def test_create_network_valid(self, client, clean_database, sample_network_data, monkeypatch):
        """Test POST /api/networks with valid data"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        response = client.post("/api/networks", json=sample_network_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "network_id" in data["data"]
        assert data["data"]["name"] == sample_network_data["name"]
        assert data["data"]["network_type"] == sample_network_data["network_type"]
        assert data["data"]["organism"] == sample_network_data["organism"]
        assert data["data"]["node_count"] == 3
        assert data["data"]["edge_count"] == 2

    def test_create_network_response_schema(self, client, clean_database, sample_network_data, monkeypatch):
        """Test that response follows NetworkCreationResponse schema"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        response = client.post("/api/networks", json=sample_network_data)

        assert response.status_code == 200
        data = response.json()
        response_data = data["data"]

        # Verify all required fields are present
        required_fields = ["network_id", "name", "network_type", "organism", 
                          "description", "node_count", "edge_count"]
        assert all(field in response_data for field in required_fields)

    def test_create_network_invalid_missing_field(self, client):
        """Test POST /api/networks with missing required field"""
        invalid_data = {
            "name": "Test",
            # Missing: network_type, organism, node_labels, adjacency_matrix
        }

        response = client.post("/api/networks", json=invalid_data)
        assert response.status_code == 422  # Pydantic validation error

    def test_create_network_invalid_empty_labels(self, client):
        """Test POST /api/networks with empty node_labels"""
        invalid_data = {
            "name": "Test",
            "network_type": "protein",
            "organism": "Human",
            "node_labels": [],  # Empty!
            "adjacency_matrix": [[0]]
        }

        response = client.post("/api/networks", json=invalid_data)
        assert response.status_code == 422  # Validation error

    def test_get_network_by_id_exists(self, client, clean_database, sample_network_data, monkeypatch):
        """Test GET /api/networks/{network_id} for existing network"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        create_response = client.post("/api/networks", json=sample_network_data)
        network_id = create_response.json()["data"]["network_id"]

        response = client.get(f"/api/networks/{network_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["network_id"] == network_id
        assert data["data"]["name"] == "Test_Network"
        # Full network should include adjacency_matrix
        assert "adjacency_matrix" in data["data"]
        assert "node_labels" in data["data"]

    def test_get_network_by_id_not_exists(self, client, clean_database, monkeypatch):
        """Test GET /api/networks/{network_id} for non-existent network"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        response = client.get("/api/networks/99999")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data or "error" in str(data).lower()

    def test_get_network_full_response_schema(self, client, clean_database, sample_network_data, monkeypatch):
        """Test that full network response follows NetworkResponse schema"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        create_response = client.post("/api/networks", json=sample_network_data)
        network_id = create_response.json()["data"]["network_id"]

        response = client.get(f"/api/networks/{network_id}")

        assert response.status_code == 200
        network_data = response.json()["data"]

        # Verify full response schema fields
        required_fields = ["network_id", "name", "network_type", "organism",
                          "description", "node_labels", "adjacency_matrix",
                          "node_count", "edge_count"]
        assert all(field in network_data for field in required_fields)

    def test_delete_network_success(self, client, clean_database, sample_network_data, monkeypatch):
        """Test DELETE /api/networks/{network_id} success"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        create_response = client.post("/api/networks", json=sample_network_data)
        network_id = create_response.json()["data"]["network_id"]

        response = client.delete(f"/api/networks/{network_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "message" in data

        # Verify network is deleted
        get_response = client.get(f"/api/networks/{network_id}")
        assert get_response.status_code == 404

    def test_delete_network_not_exists(self, client, clean_database, monkeypatch):
        """Test DELETE /api/networks/{network_id} for non-existent network"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        response = client.delete("/api/networks/99999")
        assert response.status_code == 404


@pytest.mark.integration
class TestSearchEndpoint:

    def test_search_networks_valid_request_schema(self, client):
        """Test that search endpoint validates NetworkSearch schema"""
        # Valid data should have node_labels and adjacency_matrix
        valid_data = {
            "node_labels": ["A", "B"],
            "adjacency_matrix": [[0, 1], [1, 0]]
        }

        # This might fail at DB level but schema validation should pass
        response = client.post("/api/networks/search", json=valid_data)
        # Should either be 200 (success) or 500 (DB error), but not 422 (validation error)
        assert response.status_code in [200, 500]

    def test_search_networks_invalid_missing_labels(self, client):
        """Test search with missing node_labels"""
        invalid_data = {
            # Missing node_labels!
            "adjacency_matrix": [[0, 1], [1, 0]]
        }

        response = client.post("/api/networks/search", json=invalid_data)
        assert response.status_code == 422  # Validation error

    def test_search_networks_invalid_empty_labels(self, client):
        """Test search with empty node_labels"""
        invalid_data = {
            "node_labels": [],  # Empty!
            "adjacency_matrix": [[0]]
        }

        response = client.post("/api/networks/search", json=invalid_data)
        assert response.status_code == 422  # Validation error

    def test_search_networks_valid(self, client, clean_database, sample_glycolysis, monkeypatch):
        """Test POST /api/networks/search with valid query"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        # Create a network
        client.post("/api/networks", json=sample_glycolysis)

        # Search for subgraph
        search_data = {
            "node_labels": ["Glucose", "G6P"],
            "adjacency_matrix": [[0, 1], [0, 0]]
        }

        response = client.post("/api/networks/search", json=search_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        # Each match should have required fields
        for match in data["data"]:
            assert "network_id" in match
            assert "name" in match
            assert "match_type" in match

    def test_search_networks_response_schema(self, client, clean_database, sample_glycolysis, monkeypatch):
        """Test that search response follows SearchMatchResponse schema"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        client.post("/api/networks", json=sample_glycolysis)

        search_data = {
            "node_labels": ["Glucose", "G6P"],
            "adjacency_matrix": [[0, 1], [0, 0]]
        }

        response = client.post("/api/networks/search", json=search_data)

        assert response.status_code == 200
        data = response.json()

        # Verify each match has all required fields
        for match in data["data"]:
            required_fields = ["network_id", "name", "network_type", "organism",
                              "node_labels", "node_count", "edge_count", "match_type"]
            assert all(field in match for field in required_fields)

    def test_search_networks_invalid_data(self, client):
        """Test search with completely invalid data"""
        invalid_data = {
            "node_labels": "not_a_list",  # Should be list
            "adjacency_matrix": "not_a_matrix"  # Should be list of lists
        }

        response = client.post("/api/networks/search", json=invalid_data)
        assert response.status_code == 422  # Validation error

    def test_search_networks_empty_database(self, client, clean_database, monkeypatch):
        """Test search with no networks in database"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        search_data = {
            "node_labels": ["A", "B"],
            "adjacency_matrix": [[0, 1], [1, 0]]
        }

        response = client.post("/api/networks/search", json=search_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 0  # No matches


@pytest.mark.integration
class TestAPIConsistency:
    """Tests for API consistency and proper response wrapping"""

    def test_all_endpoints_use_success_wrapper(self, client, clean_database, sample_network_data, monkeypatch):
        """Test that all endpoints return success wrapper"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        # GET /networks
        response = client.get("/api/networks")
        assert "success" in response.json()
        assert "data" in response.json()

        # POST /networks
        response = client.post("/api/networks", json=sample_network_data)
        assert "success" in response.json()
        assert "data" in response.json()

        # GET /networks/{id}
        network_id = response.json()["data"]["network_id"]
        response = client.get(f"/api/networks/{network_id}")
        assert "success" in response.json()
        assert "data" in response.json()

    def test_health_endpoint_returns_correct_status(self, client):
        """Test that health endpoint has correct structure"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        # Status values should be reasonable
        assert data["status"] in ["healthy", "unhealthy"]
        assert data["database"] in ["connected", "disconnected"]
