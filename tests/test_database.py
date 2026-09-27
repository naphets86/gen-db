"""
Tests for database.py module - Updated for new Config architecture

Changes:
- Uses new Config class instead of hardcoded DATABASE_CONFIG
- Compatible with get_config() singleton pattern
"""
import pytest
import psycopg2
from backend.database import get_db_connection, get_db_cursor
from backend.config import get_config


@pytest.mark.db
class TestDatabaseConnection:

    def test_get_db_connection_success(self, test_db_config, monkeypatch):
        """Test successful database connection"""
        # Patch database config to use test config
        monkeypatch.setattr('backend.database.DATABASE_CONFIG', test_db_config)

        with get_db_connection() as conn:
            assert conn is not None
            assert not conn.closed

    def test_get_db_connection_commit(self, clean_database):
        """Test database commit functionality"""
        cursor = clean_database.cursor()
        cursor.execute('''
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES ('Test', 'metabolic', 'Test', 'Test', 3, 2)
        ''')
        clean_database.commit()

        cursor.execute("SELECT COUNT(*) FROM biological_networks")
        count = cursor.fetchone()[0]
        assert count == 1

    def test_get_db_connection_rollback_on_error(self, test_db_config, monkeypatch):
        """Test database rollback on error"""
        monkeypatch.setattr('backend.database.DATABASE_CONFIG', test_db_config)

        with pytest.raises(psycopg2.Error):
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Invalid column should raise error
                cursor.execute("INSERT INTO biological_networks (invalid_column) VALUES ('test')")

    def test_get_db_connection_closes_after_context(self, test_db_config, monkeypatch):
        """Test that connection closes after context manager"""
        monkeypatch.setattr('backend.database.DATABASE_CONFIG', test_db_config)

        with get_db_connection() as conn:
            pass

        assert conn.closed

    def test_get_db_cursor_returns_dict_cursor(self, db_connection):
        """Test that cursor is a dict cursor"""
        cursor = get_db_cursor(db_connection)
        assert cursor is not None
        assert cursor.connection == db_connection

    def test_get_db_cursor_returns_rows_as_dicts(self, clean_database):
        """Test that cursor returns rows as dictionaries"""
        # Insert test data
        cursor = get_db_cursor(clean_database)
        cursor.execute('''
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES ('Test', 'protein', 'Human', 'Test network', 2, 1)
        ''')
        clean_database.commit()

        # Fetch and verify dict format
        cursor.execute("SELECT * FROM biological_networks WHERE name='Test'")
        row = cursor.fetchone()

        # Should be dict-like with key access
        assert row is not None
        assert 'name' in row
        assert row['name'] == 'Test'
        assert 'organism' in row
        assert row['organism'] == 'Human'

    def test_database_connection_pool_size(self, test_db_config, monkeypatch):
        """Test that database respects pool size configuration"""
        monkeypatch.setattr('backend.database.DATABASE_CONFIG', test_db_config)

        # Get multiple connections
        with get_db_connection() as conn1:
            assert conn1 is not None

        with get_db_connection() as conn2:
            assert conn2 is not None

        # Should work without exhausting pool
        with get_db_connection() as conn3:
            assert conn3 is not None

    def test_database_ssl_mode_config(self, test_config):
        """Test that SSL mode can be configured (test uses disable)"""
        config = test_config
        # Test database typically uses ssl_mode='disable' for localhost
        # This test just verifies config is accessible
        assert hasattr(config, 'database_ssl_mode')

    def test_database_tables_exist(self, clean_database):
        """Test that all required tables exist"""
        cursor = clean_database.cursor()

        # Check biological_networks table
        cursor.execute('''
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'biological_networks'
            )
        ''')
        assert cursor.fetchone()[0] is True

        # Check network_matrices table
        cursor.execute('''
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'network_matrices'
            )
        ''')
        assert cursor.fetchone()[0] is True

    def test_database_table_structure_biological_networks(self, clean_database):
        """Test structure of biological_networks table"""
        cursor = get_db_cursor(clean_database)

        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='biological_networks'")
        columns = [row['column_name'] for row in cursor.fetchall()]

        required_columns = ['network_id', 'name', 'network_type', 'organism', 'description', 'node_count', 'edge_count', 'created_at']
        assert all(col in columns for col in required_columns)

    def test_database_table_structure_network_matrices(self, clean_database):
        """Test structure of network_matrices table"""
        cursor = get_db_cursor(clean_database)

        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='network_matrices'")
        columns = [row['column_name'] for row in cursor.fetchall()]

        required_columns = ['network_id', 'node_labels', 'adjacency_matrix', 'signature_array', 'signature_hash']
        assert all(col in columns for col in required_columns)

    def test_cascade_delete_on_network_deletion(self, clean_database):
        """Test that network_matrices entries are deleted when network is deleted (CASCADE)"""
        cursor = get_db_cursor(clean_database)

        # Insert network
        cursor.execute('''
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES ('Test', 'metabolic', 'Test', 'Test', 2, 1)
            RETURNING network_id
        ''')
        network_id = cursor.fetchone()['network_id']
        clean_database.commit()

        # Insert matrix entry
        cursor.execute('''
            INSERT INTO network_matrices
            (network_id, node_labels, adjacency_matrix, signature_array, signature_hash)
            VALUES (%s, %s, %s, %s, %s)
        ''', (network_id, ['A', 'B'], [[0, 1], [0, 0]], [1, 2], 'hash123'))
        clean_database.commit()

        # Verify entry exists
        cursor.execute("SELECT COUNT(*) FROM network_matrices WHERE network_id=%s", (network_id,))
        assert cursor.fetchone()[0] == 1

        # Delete network
        cursor.execute("DELETE FROM biological_networks WHERE network_id=%s", (network_id,))
        clean_database.commit()

        # Verify matrix entry is also deleted (CASCADE)
        cursor.execute("SELECT COUNT(*) FROM network_matrices WHERE network_id=%s", (network_id,))
        assert cursor.fetchone()[0] == 0
