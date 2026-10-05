"""Tests for database connections and the isolated test schema."""
from uuid import uuid4

import pytest
import psycopg2

from backend.database import get_db_connection, get_db_cursor


@pytest.mark.db
class TestDatabaseConnection:

    def test_get_db_connection_success(self, test_db_config):
        with get_db_connection() as conn:
            assert not conn.closed
            with conn.cursor() as cursor:
                cursor.execute('SELECT current_database()')
                assert cursor.fetchone()[0] == test_db_config['database']

    def test_get_db_connection_commit(self):
        name = f'Test_{uuid4().hex}'
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO biological_networks
                        (name, network_type, organism, description, node_count, edge_count)
                        VALUES (%s, 'metabolic', 'Test', 'Test', 3, 2)
                    """, (name,))

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        'SELECT COUNT(*) FROM biological_networks WHERE name = %s',
                        (name,),
                    )
                    assert cursor.fetchone()[0] == 1
        finally:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        'DELETE FROM biological_networks WHERE name = %s',
                        (name,),
                    )

    def test_get_db_connection_rollback_on_error(self):
        with pytest.raises(psycopg2.Error):
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO biological_networks (invalid_column) VALUES ('test')"
                    )

    def test_get_db_connection_closes_after_context(self):
        with get_db_connection() as conn:
            pass
        assert conn.closed

    def test_get_db_cursor_returns_dict_cursor(self, db_connection):
        cursor = get_db_cursor(db_connection)
        assert cursor is not None
        assert cursor.connection == db_connection

    def test_get_db_cursor_returns_rows_as_dicts(self, clean_database):
        cursor = get_db_cursor(clean_database)
        cursor.execute("""
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES ('Test', 'protein', 'Human', 'Test network', 2, 1)
        """)
        clean_database.commit()
        cursor.execute("SELECT * FROM biological_networks WHERE name='Test'")
        row = cursor.fetchone()
        assert row['name'] == 'Test'
        assert row['organism'] == 'Human'

    def test_database_connection_pool_size(self):
        for _ in range(3):
            with get_db_connection() as conn:
                assert not conn.closed

    def test_database_ssl_mode_config(self, test_config):
        assert hasattr(test_config, 'database_ssl_mode')

    def test_database_tables_exist(self, clean_database):
        with clean_database.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'biological_networks'
                )
            """)
            assert cursor.fetchone()[0] is True
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'network_matrices'
                )
            """)
            assert cursor.fetchone()[0] is True

    def test_database_table_structure_biological_networks(self, clean_database):
        cursor = get_db_cursor(clean_database)
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='biological_networks'"
        )
        columns = [row['column_name'] for row in cursor.fetchall()]
        required = {
            'network_id', 'name', 'network_type', 'organism', 'description',
            'node_count', 'edge_count', 'created_at',
        }
        assert required.issubset(columns)

    def test_database_table_structure_network_matrices(self, clean_database):
        cursor = get_db_cursor(clean_database)
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='network_matrices'"
        )
        columns = [row['column_name'] for row in cursor.fetchall()]
        required = {
            'network_id', 'node_labels', 'adjacency_matrix',
            'signature_array', 'signature_hash',
        }
        assert required.issubset(columns)

    def test_cascade_delete_on_network_deletion(self, clean_database):
        cursor = get_db_cursor(clean_database)
        cursor.execute("""
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES ('Test', 'metabolic', 'Test', 'Test', 2, 1)
            RETURNING network_id
        """)
        network_id = cursor.fetchone()['network_id']
        cursor.execute("""
            INSERT INTO network_matrices
            (network_id, node_labels, adjacency_matrix, signature_array, signature_hash)
            VALUES (%s, %s, %s, %s, %s)
        """, (network_id, ['A', 'B'], [[0, 1], [0, 0]], [1, 2], 'hash123'))
        clean_database.commit()

        cursor.execute('SELECT COUNT(*) AS count FROM network_matrices WHERE network_id=%s', (network_id,))
        assert cursor.fetchone()['count'] == 1
        cursor.execute('DELETE FROM biological_networks WHERE network_id=%s', (network_id,))
        clean_database.commit()
        cursor.execute('SELECT COUNT(*) AS count FROM network_matrices WHERE network_id=%s', (network_id,))
        assert cursor.fetchone()['count'] == 0