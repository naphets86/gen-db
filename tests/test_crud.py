"""
Tests for crud.py module - Updated for Domain Models Architecture

CRUD functions now return:
- NetworkCreationResult (instead of Dict)
- Network (instead of Dict)
- List[NetworkSummary] (instead of List[Dict])
- List[SearchMatch] (instead of List[Dict])
"""
import pytest
import numpy as np
from backend.crud import (
    compute_signatures,
    compute_signature_hash,
    create_network,
    get_all_networks,
    get_network_by_id,
    search_subgraph,
    delete_network
)
from backend.models import (
    Network,
    NetworkSummary,
    NetworkCreationResult,
    SearchMatch
)


@pytest.mark.unit
class TestSignatureComputation:

    def test_compute_signatures_simple(self):
        matrix = np.array([[0, 1], [0, 0]])
        signatures = compute_signatures(matrix)

        assert len(signatures) == 2
        assert signatures[0] == 0
        assert signatures[1] == 5

    def test_compute_signatures_complex(self):
        matrix = np.array([
            [0, 1, 0],
            [0, 0, 1],
            [1, 0, 0]
        ])
        signatures = compute_signatures(matrix)

        assert len(signatures) == 3
        assert all(isinstance(sig, int) for sig in signatures)

    def test_compute_signatures_empty(self):
        matrix = np.array([[0]])
        signatures = compute_signatures(matrix)

        assert len(signatures) == 1
        assert signatures[0] == 0

    def test_compute_signature_hash(self):
        signatures = [1, 2, 3]
        hash1 = compute_signature_hash(signatures)
        hash2 = compute_signature_hash(signatures)

        assert isinstance(hash1, str)
        assert len(hash1) == 64
        assert hash1 == hash2

    def test_compute_signature_hash_different_inputs(self):
        hash1 = compute_signature_hash([1, 2, 3])
        hash2 = compute_signature_hash([3, 2, 1])

        assert hash1 != hash2


@pytest.mark.db
class TestCreateNetwork:

    def test_create_network_returns_domain_model(self, clean_database, sample_network_data, monkeypatch):
        """Test that create_network returns NetworkCreationResult (Domain Model)"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        result = create_network(**sample_network_data)

        # Result should be NetworkCreationResult domain model
        assert isinstance(result, NetworkCreationResult)
        assert result.network_id > 0
        assert result.name == 'Test_Network'
        assert result.node_count == 3
        assert result.edge_count == 2
        assert isinstance(result.signature_hash, str)

    def test_create_network_success(self, clean_database, sample_network_data, monkeypatch):
        """Test successful network creation"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        result = create_network(**sample_network_data)

        assert result.network_id is not None
        assert result.name == sample_network_data['name']
        assert result.network_type == sample_network_data['network_type']
        assert result.organism == sample_network_data['organism']

    def test_create_network_with_empty_matrix(self, clean_database, monkeypatch):
        """Test network creation with no edges"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        data = {
            'name': 'Empty_Network',
            'network_type': 'test',
            'organism': 'Test',
            'description': '',
            'node_labels': ['A', 'B'],
            'adjacency_matrix': [[0, 0], [0, 0]]
        }

        result = create_network(**data)
        assert result.edge_count == 0
        assert result.node_count == 2

    def test_create_network_computes_signatures(self, clean_database, sample_network_data, monkeypatch):
        """Test that signatures are computed during network creation"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        result = create_network(**sample_network_data)
        network_id = result.network_id

        # Verify signatures were stored in database
        cursor = clean_database.cursor()
        cursor.execute("SELECT signature_array FROM network_matrices WHERE network_id = %s", (network_id,))

        row = cursor.fetchone()
        assert row is not None
        assert len(row[0]) == 3  # Should have 3 signatures for 3-node graph


@pytest.mark.db
class TestGetNetworks:

    def test_get_all_networks_returns_domain_models(self, clean_database, sample_network_data, monkeypatch):
        """Test that get_all_networks returns List[NetworkSummary]"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        create_network(**sample_network_data)

        networks = get_all_networks()

        assert isinstance(networks, list)
        assert len(networks) == 1
        # Result should be domain models, not dicts
        assert isinstance(networks[0], NetworkSummary)
        assert networks[0].name == 'Test_Network'
        assert networks[0].network_type == 'metabolic'

    def test_get_all_networks_empty(self, clean_database, monkeypatch):
        """Test get_all_networks with empty database"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        networks = get_all_networks()
        assert isinstance(networks, list)
        assert len(networks) == 0

    def test_get_all_networks_multiple(self, clean_database, sample_network_data, monkeypatch):
        """Test get_all_networks with multiple networks"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        create_network(**sample_network_data)
        data2 = sample_network_data.copy()
        data2['name'] = 'Network_2'
        create_network(**data2)

        networks = get_all_networks()
        assert len(networks) == 2
        assert all(isinstance(net, NetworkSummary) for net in networks)

    def test_get_network_by_id_returns_domain_model(self, clean_database, sample_network_data, monkeypatch):
        """Test that get_network_by_id returns Network (Domain Model)"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        result = create_network(**sample_network_data)
        network_id = result.network_id

        network = get_network_by_id(network_id)

        # Result should be Network domain model, not dict
        assert isinstance(network, Network)
        assert network.network_id == network_id
        assert network.name == 'Test_Network'
        assert isinstance(network.adjacency_matrix, list)
        assert isinstance(network.node_labels, list)
        assert network.signature_array is not None

    def test_get_network_by_id_exists(self, clean_database, sample_network_data, monkeypatch):
        """Test retrieving existing network"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        result = create_network(**sample_network_data)
        network_id = result.network_id

        network = get_network_by_id(network_id)

        assert network is not None
        assert network.network_id == network_id
        assert network.name == 'Test_Network'

    def test_get_network_by_id_not_exists(self, clean_database, monkeypatch):
        """Test retrieving non-existent network"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        network = get_network_by_id(99999)
        assert network is None


@pytest.mark.db
class TestDeleteNetwork:

    def test_delete_network_success(self, clean_database, sample_network_data, monkeypatch):
        """Test successful network deletion"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        result = create_network(**sample_network_data)
        network_id = result.network_id

        deleted = delete_network(network_id)
        assert deleted is True

        # Verify network is deleted
        network = get_network_by_id(network_id)
        assert network is None

    def test_delete_network_not_exists(self, clean_database, monkeypatch):
        """Test deleting non-existent network"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        deleted = delete_network(99999)
        assert deleted is False

    def test_delete_network_cascades_matrix(self, clean_database, sample_network_data, monkeypatch):
        """Test that deleting network also deletes matrix (CASCADE)"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        result = create_network(**sample_network_data)
        network_id = result.network_id

        delete_network(network_id)

        # Verify matrix entry is also deleted (CASCADE)
        cursor = clean_database.cursor()
        cursor.execute("SELECT COUNT(*) FROM network_matrices WHERE network_id = %s", (network_id,))
        count = cursor.fetchone()[0]
        assert count == 0


@pytest.mark.db
@pytest.mark.slow
class TestSubgraphSearch:

    def test_search_subgraph_returns_domain_models(self, clean_database, sample_glycolysis,
                                                   sample_partial_glycolysis, monkeypatch):
        """Test that search_subgraph returns List[SearchMatch] (Domain Models)"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        create_network(**sample_glycolysis)

        matches = search_subgraph(
            query_matrix=sample_partial_glycolysis['adjacency_matrix'],
            query_labels=sample_partial_glycolysis['node_labels']
        )

        # Results should be domain models
        assert isinstance(matches, list)
        assert all(isinstance(m, SearchMatch) for m in matches)

    def test_search_subgraph_finds_superset(self, clean_database, sample_glycolysis,
                                            sample_partial_glycolysis, monkeypatch):
        """Test finding network that contains the query subgraph"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        create_network(**sample_glycolysis)

        matches = search_subgraph(
            query_matrix=sample_partial_glycolysis['adjacency_matrix'],
            query_labels=sample_partial_glycolysis['node_labels']
        )

        assert len(matches) >= 1
        assert any(m.name == 'Glycolysis' for m in matches)
        # Check that match has correct attributes
        match = matches[0]
        assert isinstance(match.match_type, str)
        assert match.node_count >= 3

    def test_search_subgraph_no_matches(self, clean_database, sample_glycolysis, monkeypatch):
        """Test search with no matching subgraphs"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        create_network(**sample_glycolysis)

        # Create very different graph
        different_matrix = [[0, 1, 1], [1, 0, 1], [1, 1, 0]]
        different_labels = ['X', 'Y', 'Z']

        matches = search_subgraph(
            query_matrix=different_matrix,
            query_labels=different_labels
        )

        # Should return empty list, not error
        assert isinstance(matches, list)

    def test_search_subgraph_prefiltering(self, clean_database, sample_network_data, monkeypatch):
        """Test that small networks are pre-filtered (not candidates for large query)"""
        monkeypatch.setattr('backend.crud.get_db_connection', lambda: clean_database)

        # Create small network (3 nodes)
        create_network(**sample_network_data)

        # Query with 5 nodes (larger than database network)
        large_matrix = [[0]*5 for _ in range(5)]
        large_labels = ['A', 'B', 'C', 'D', 'E']

        matches = search_subgraph(
            query_matrix=large_matrix,
            query_labels=large_labels
        )

        # Small network shouldn't match larger query
        assert len(matches) == 0
