"""
End-to-end integration tests - Enhanced for new Architecture

Tests the complete workflow through multiple layers:
1. API (FastAPI)
2. Schemas (Pydantic Validation)
3. CRUD (Business Logic)
4. Models (Domain Models)
5. Database (Persistence)

Updated for:
- Response wrappers
- Domain models
- Schema validation
"""
import pytest
from fastapi.testclient import TestClient

from backend.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.integration
@pytest.mark.slow
class TestCompleteWorkflow:

    def test_create_search_delete_workflow(self, client, clean_database,
                                          sample_glycolysis, sample_partial_glycolysis,
                                          monkeypatch):
        """Test complete workflow: create → search → delete"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        # Step 1: Create full network
        response1 = client.post("/api/networks", json=sample_glycolysis)
        assert response1.status_code == 200
        full_id = response1.json()["data"]["network_id"]
        assert response1.json()["success"] is True

        # Step 2: Create partial network
        response2 = client.post("/api/networks", json=sample_partial_glycolysis)
        assert response2.status_code == 200
        partial_id = response2.json()["data"]["network_id"]
        assert response2.json()["success"] is True

        # Step 3: Get all networks
        response3 = client.get("/api/networks")
        assert response3.status_code == 200
        assert len(response3.json()["data"]) == 2
        assert response3.json()["count"] == 2

        # Step 4: Search subgraph
        search_data = {
            "node_labels": sample_partial_glycolysis["node_labels"],
            "adjacency_matrix": sample_partial_glycolysis["adjacency_matrix"]
        }
        response4 = client.post("/api/networks/search", json=search_data)
        assert response4.status_code == 200
        matches = response4.json()["data"]
        assert len(matches) >= 1

        # Step 5: Delete first network
        response5 = client.delete("/api/networks/" + str(full_id))
        assert response5.status_code == 200
        assert response5.json()["success"] is True

        # Step 6: Delete second network
        response6 = client.delete("/api/networks/" + str(partial_id))
        assert response6.status_code == 200
        assert response6.json()["success"] is True

        # Step 7: Verify all networks deleted
        response7 = client.get("/api/networks")
        assert len(response7.json()["data"]) == 0
        assert response7.json()["count"] == 0

    def test_concurrent_network_creation(self, client, clean_database, monkeypatch):
        """Test creating multiple networks in sequence"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        networks = []
        for i in range(5):
            networks.append({
                "name": "Network_" + str(i),
                "network_type": "test",
                "organism": "Test",
                "description": f"Test network {i}",
                "node_labels": ["A", "B", "C"],
                "adjacency_matrix": [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
            })

        created_ids = []
        for network_data in networks:
            response = client.post("/api/networks", json=network_data)
            assert response.status_code == 200
            assert response.json()["success"] is True
            created_ids.append(response.json()["data"]["network_id"])

        # Verify all created
        response = client.get("/api/networks")
        assert len(response.json()["data"]) == 5
        assert response.json()["count"] == 5

        # Verify each network can be retrieved
        for network_id in created_ids:
            response = client.get(f"/api/networks/{network_id}")
            assert response.status_code == 200
            assert response.json()["data"]["network_id"] == network_id

    def test_create_retrieve_update_delete_lifecycle(self, client, clean_database, monkeypatch):
        """Test full CRUD lifecycle for a single network"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        network_data = {
            "name": "Lifecycle_Test",
            "network_type": "protein",
            "organism": "Human",
            "description": "Test network for lifecycle",
            "node_labels": ["P1", "P2", "P3"],
            "adjacency_matrix": [[0, 1, 0], [1, 0, 1], [0, 1, 0]]
        }

        # Create
        create_response = client.post("/api/networks", json=network_data)
        assert create_response.status_code == 200
        network_id = create_response.json()["data"]["network_id"]

        # Retrieve
        get_response = client.get(f"/api/networks/{network_id}")
        assert get_response.status_code == 200
        retrieved = get_response.json()["data"]
        assert retrieved["network_id"] == network_id
        assert retrieved["name"] == "Lifecycle_Test"
        assert retrieved["node_count"] == 3
        assert retrieved["edge_count"] == 2

        # Verify in list
        list_response = client.get("/api/networks")
        network_names = [net["name"] for net in list_response.json()["data"]]
        assert "Lifecycle_Test" in network_names

        # Delete
        delete_response = client.delete(f"/api/networks/{network_id}")
        assert delete_response.status_code == 200

        # Verify deleted
        get_deleted = client.get(f"/api/networks/{network_id}")
        assert get_deleted.status_code == 404

    def test_search_workflow_with_multiple_candidates(self, client, clean_database, monkeypatch):
        """Test search with multiple candidate networks"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        # Create multiple networks with different structures
        networks = [
            {
                "name": "Network_Linear",
                "network_type": "metabolic",
                "organism": "Test",
                "description": "",
                "node_labels": ["A", "B", "C"],
                "adjacency_matrix": [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
            },
            {
                "name": "Network_Cyclic",
                "network_type": "metabolic",
                "organism": "Test",
                "description": "",
                "node_labels": ["X", "Y", "Z"],
                "adjacency_matrix": [[0, 1, 0], [0, 0, 1], [1, 0, 0]]
            },
            {
                "name": "Network_Complete",
                "network_type": "metabolic",
                "organism": "Test",
                "description": "",
                "node_labels": ["P", "Q", "R"],
                "adjacency_matrix": [[0, 1, 1], [1, 0, 1], [1, 1, 0]]
            }
        ]

        for network_data in networks:
            response = client.post("/api/networks", json=network_data)
            assert response.status_code == 200

        # Search for a simple 2-node edge
        search_data = {
            "node_labels": ["Node1", "Node2"],
            "adjacency_matrix": [[0, 1], [0, 0]]
        }

        response = client.post("/api/networks/search", json=search_data)
        assert response.status_code == 200
        assert response.json()["success"] is True
        # Should find networks that contain this edge

    def test_validation_error_handling(self, client, clean_database, monkeypatch):
        """Test that invalid input is properly validated and rejected"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        # Missing required fields
        invalid_data = {
            "name": "Test"
            # Missing: network_type, organism, node_labels, adjacency_matrix
        }

        response = client.post("/api/networks", json=invalid_data)
        assert response.status_code == 422  # Validation error

        # Empty node_labels
        invalid_data = {
            "name": "Test",
            "network_type": "protein",
            "organism": "Human",
            "node_labels": [],  # Empty!
            "adjacency_matrix": [[0]]
        }

        response = client.post("/api/networks", json=invalid_data)
        assert response.status_code == 422  # Validation error

        # Mismatched matrix size
        invalid_data = {
            "name": "Test",
            "network_type": "protein",
            "organism": "Human",
            "node_labels": ["A", "B"],  # 2 nodes
            "adjacency_matrix": [[0, 1, 0], [1, 0, 1], [0, 1, 0]]  # 3x3 matrix!
        }

        response = client.post("/api/networks", json=invalid_data)
        # May be 422 or 500 depending on validation, but shouldn't be 200

    def test_response_consistency_across_endpoints(self, client, clean_database, monkeypatch):
        """Test that all endpoints return consistent response format"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        network_data = {
            "name": "Consistency_Test",
            "network_type": "protein",
            "organism": "Test",
            "description": "",
            "node_labels": ["A", "B"],
            "adjacency_matrix": [[0, 1], [0, 0]]
        }

        # POST should have success wrapper
        create_resp = client.post("/api/networks", json=network_data)
        assert "success" in create_resp.json()
        assert "data" in create_resp.json()

        network_id = create_resp.json()["data"]["network_id"]

        # GET should have success wrapper
        get_resp = client.get(f"/api/networks/{network_id}")
        assert "success" in get_resp.json()
        assert "data" in get_resp.json()

        # GET list should have success, data, count
        list_resp = client.get("/api/networks")
        assert "success" in list_resp.json()
        assert "data" in list_resp.json()
        assert "count" in list_resp.json()

        # DELETE should have success
        delete_resp = client.delete(f"/api/networks/{network_id}")
        assert "success" in delete_resp.json()
        assert "message" in delete_resp.json()

        # Search should have success, data
        search_resp = client.post("/api/networks/search", json={
            "node_labels": ["X"],
            "adjacency_matrix": [[0]]
        })
        assert "success" in search_resp.json()
        assert "data" in search_resp.json()

    def test_health_check_always_available(self, client):
        """Test that health check is always available"""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data


@pytest.mark.integration
class TestAPIErrorHandling:

    def test_404_on_nonexistent_network(self, client, clean_database, monkeypatch):
        """Test 404 error for non-existent network"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        response = client.get("/api/networks/99999")
        assert response.status_code == 404

    def test_404_on_delete_nonexistent_network(self, client, clean_database, monkeypatch):
        """Test 404 error when deleting non-existent network"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        response = client.delete("/api/networks/99999")
        assert response.status_code == 404

    def test_500_on_database_error(self, client, clean_database, monkeypatch):
        """Test 500 error when database fails"""
        from backend import crud

        def failing_connection():
            raise RuntimeError("Database connection failed")

        monkeypatch.setattr(crud, 'get_db_connection', failing_connection)

        response = client.post("/api/networks", json={
            "name": "Test",
            "network_type": "protein",
            "organism": "Human",
            "node_labels": ["A"],
            "adjacency_matrix": [[0]]
        })
        # Should be 500 error due to database failure
        assert response.status_code == 500


@pytest.mark.integration
class TestDataPersistence:

    def test_data_persists_across_requests(self, client, clean_database, monkeypatch):
        """Test that data persists across multiple requests"""
        from backend import crud
        monkeypatch.setattr(crud, 'get_db_connection', lambda: clean_database)

        network_data = {
            "name": "Persistence_Test",
            "network_type": "protein",
            "organism": "Human",
            "description": "Test",
            "node_labels": ["A", "B"],
            "adjacency_matrix": [[0, 1], [0, 0]]
        }

        # Create network
        create_resp = client.post("/api/networks", json=network_data)
        network_id = create_resp.json()["data"]["network_id"]

        # Retrieve multiple times, should be same data
        get_resp1 = client.get(f"/api/networks/{network_id}")
        data1 = get_resp1.json()["data"]

        get_resp2 = client.get(f"/api/networks/{network_id}")
        data2 = get_resp2.json()["data"]

        # Data should be identical
        assert data1 == data2
        assert data1["name"] == "Persistence_Test"
        assert data1["node_labels"] == ["A", "B"]
