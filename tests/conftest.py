"""Pytest fixtures with an isolated PostgreSQL test database."""
import os
import sys
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from backend.app import app
from backend.config import get_config, reload_config


@pytest.fixture(scope='session', autouse=True)
def setup_test_database():
    """Create a dedicated database and schema, refusing production names."""
    config = reload_config()
    test_db_name = config.test_database_name or 'gen_test'
    if test_db_name == config.database_name:
        raise RuntimeError(
            'Test database must differ from DATABASE_NAME; refusing to run tests.'
        )
    if test_db_name in {'postgres', 'template0', 'template1'}:
        raise RuntimeError(
            f'{test_db_name!r} is a PostgreSQL system database, not a test database.'
        )

    test_host = config.test_database_host or config.database_host
    test_port = config.test_database_port or config.database_port
    test_user = config.test_database_user or config.database_user
    test_password = config.test_database_password or config.database_password
    admin_conn = psycopg2.connect(
        host=test_host,
        port=test_port,
        user=test_user,
        password=test_password,
        database='postgres',
    )
    admin_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with admin_conn.cursor() as cursor:
            cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (test_db_name,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL('CREATE DATABASE {}').format(sql.Identifier(test_db_name))
                )
    finally:
        admin_conn.close()

    test_conn = psycopg2.connect(
        host=test_host,
        port=test_port,
        user=test_user,
        password=test_password,
        database=test_db_name,
    )
    try:
        with test_conn.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS omics_layers CASCADE')
            cursor.execute('DROP TABLE IF EXISTS omics_networks CASCADE')
            cursor.execute('DROP TABLE IF EXISTS network_matrices CASCADE')
            cursor.execute('DROP TABLE IF EXISTS biological_networks CASCADE')
            cursor.execute("""
                CREATE TABLE biological_networks (
                    network_id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    network_type VARCHAR(50),
                    organism VARCHAR(100),
                    description TEXT,
                    node_count INTEGER NOT NULL,
                    edge_count INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE TABLE network_matrices (
                    network_id INTEGER PRIMARY KEY REFERENCES biological_networks(network_id) ON DELETE CASCADE,
                    node_labels TEXT[] NOT NULL,
                    adjacency_matrix INTEGER[][] NOT NULL,
                    signature_array BIGINT[] NOT NULL,
                    signature_hash VARCHAR(64),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE TABLE omics_networks (
                    network_id INTEGER PRIMARY KEY REFERENCES biological_networks(network_id) ON DELETE CASCADE,
                    node_labels TEXT[] NOT NULL,
                    layer_count INTEGER NOT NULL CHECK (layer_count >= 1),
                    signature_hash VARCHAR(64)
                )
            """)
            cursor.execute("""
                CREATE TABLE omics_layers (
                    network_id INTEGER NOT NULL REFERENCES omics_networks(network_id) ON DELETE CASCADE,
                    layer_index INTEGER NOT NULL,
                    layer_name VARCHAR(100) NOT NULL,
                    adjacency_matrix INTEGER[][] NOT NULL,
                    row_components BIGINT[] NOT NULL,
                    edge_count INTEGER NOT NULL,
                    PRIMARY KEY (network_id, layer_name),
                    UNIQUE (network_id, layer_index)
                )
            """)
            cursor.execute('CREATE INDEX idx_omics_layers_name ON omics_layers(layer_name)')
            cursor.execute('CREATE INDEX idx_networks_type ON biological_networks(network_type)')
            cursor.execute('CREATE INDEX idx_networks_organism ON biological_networks(organism)')
            cursor.execute('CREATE INDEX idx_networks_node_count ON biological_networks(node_count)')
            cursor.execute('CREATE INDEX idx_matrices_hash ON network_matrices(signature_hash)')
        test_conn.commit()
    except Exception:
        test_conn.rollback()
        raise
    finally:
        test_conn.close()


@pytest.fixture(scope='session')
def pydantic_config(setup_test_database):
    return get_config()


@pytest.fixture(scope='session')
def test_db_config(pydantic_config):
    config = pydantic_config
    return {
        'host': config.test_database_host or config.database_host,
        'port': config.test_database_port or config.database_port,
        'user': config.test_database_user or config.database_user,
        'password': config.test_database_password or config.database_password,
        'database': config.test_database_name or 'gen_test',
    }


@pytest.fixture(scope='session')
def test_config(pydantic_config):
    return pydantic_config


@pytest.fixture(scope='function', autouse=True)
def route_database_connections_to_test_db(test_db_config, monkeypatch):
    """Route backend database connections away from the configured production DB."""
    from backend import database

    test_config = get_config().model_copy(update={
        'database_host': test_db_config['host'],
        'database_port': test_db_config['port'],
        'database_user': test_db_config['user'],
        'database_password': test_db_config['password'],
        'database_name': test_db_config['database'],
    })
    monkeypatch.setattr(database, 'get_config', lambda: test_config)


@pytest.fixture(scope='session')
def db_connection(setup_test_database, test_db_config):
    conn = psycopg2.connect(**test_db_config)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope='function')
def clean_database(db_connection):
    with db_connection.cursor() as cursor:
        cursor.execute('TRUNCATE TABLE omics_layers, omics_networks, network_matrices, biological_networks RESTART IDENTITY CASCADE')
    db_connection.commit()
    yield db_connection
    with db_connection.cursor() as cursor:
        cursor.execute('TRUNCATE TABLE omics_layers, omics_networks, network_matrices, biological_networks RESTART IDENTITY CASCADE')
    db_connection.commit()


@pytest.fixture(scope='function')
def sample_network_data():
    return {
        'name': 'Test_Network',
        'network_type': 'metabolic',
        'organism': 'Test',
        'description': 'Test network for unit tests',
        'node_labels': ['A', 'B', 'C'],
        'adjacency_matrix': [[0, 1, 0], [0, 0, 1], [0, 0, 0]],
    }


@pytest.fixture(scope='function')
def sample_glycolysis():
    return {
        'name': 'Glycolysis',
        'network_type': 'metabolic',
        'organism': 'Homo sapiens',
        'description': 'Test glycolysis network',
        'node_labels': ['Glucose', 'G6P', 'F6P', 'FBP', 'DHAP', 'G3P', 'Pyruvate'],
        'adjacency_matrix': [
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 1, 0],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1],
            [0, 0, 0, 0, 0, 0, 0],
        ],
    }


@pytest.fixture(scope='function')
def sample_partial_glycolysis():
    return {
        'name': 'Partial_Glycolysis',
        'network_type': 'metabolic',
        'organism': 'Homo sapiens',
        'description': 'Test glycolysis subnetwork',
        'node_labels': ['Glucose', 'G6P', 'F6P'],
        'adjacency_matrix': [[0, 1, 0], [0, 0, 1], [0, 0, 0]],
    }


@pytest.fixture(scope='function')
def client():
    return TestClient(app)


def pytest_configure(config):
    os.chdir(PROJECT_ROOT)