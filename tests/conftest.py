"""
Pytest configuration - COMPLETE with ALL required fixtures
Creates gen_test database and provides all fixtures for tests
"""
import os
import sys
from pathlib import Path
import pytest
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import logging

logger = logging.getLogger(__name__)

# ============================================================
# CRITICAL: Set Working Directory to Project Root
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

# Add src to path
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from backend.config import get_config, reload_config
from backend.app import app
from fastapi.testclient import TestClient

# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope='session', autouse=True)
def setup_test_environment():
    """Setup Test Environment"""
    os.chdir(PROJECT_ROOT)
    
    print(f"\n{'='*70}")
    print(f"TEST ENVIRONMENT SETUP")
    print(f"{'='*70}")
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Current Dir:  {os.getcwd()}")
    
    yield
    
    print(f"{'='*70}\n")


@pytest.fixture(scope='session', autouse=True)
def setup_pydantic_config(setup_test_environment):
    """ZENTRAL: Setup Pydantic Config fuer Tests"""
    os.chdir(PROJECT_ROOT)
    config = reload_config()
    
    print(f"\n{'='*70}")
    print(f"PYDANTIC CONFIG LOADED")
    print(f"{'='*70}")
    
    print(f"\nProduction Database:")
    print(f"   Host:     {config.database_host}")
    print(f"   Port:     {config.database_port}")
    print(f"   User:     {config.database_user}")
    print(f"   Database: {config.database_name}")
    
    print(f"\nTest Database Config:")
    print(f"   Host:     {config.test_database_host or config.database_host}")
    print(f"   Port:     {config.test_database_port or config.database_port}")
    print(f"   User:     {config.test_database_user or config.database_user}")
    print(f"   Database: {config.test_database_name or 'gen_test (default)'}")
    
    print(f"{'='*70}\n")
    
    return config


@pytest.fixture(scope='session', autouse=True)
def setup_test_database(setup_pydantic_config):
    """
    ZENTRAL: Creates gen_test database before tests
    
    - Connects as postgres to postgres (System DB)
    - Creates gen_test if not exists
    - Creates tables if needed
    """
    config = setup_pydantic_config
    
    # Connection data for system database
    admin_config = {
        'host': config.database_host,
        'port': config.database_port,
        'user': config.database_user,
        'password': config.database_password,
        'database': 'postgres'
    }
    
    test_db_name = config.test_database_name or 'gen_test'
    
    print(f"Setting up test database '{test_db_name}'...")
    
    try:
        # 1. Connect to System DB as postgres
        admin_conn = psycopg2.connect(**admin_config)
        admin_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        admin_cursor = admin_conn.cursor()
        
        # 2. Check if database exists
        admin_cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (test_db_name,)
        )
        
        if not admin_cursor.fetchone():
            # 3. Create database
            print(f"   Creating database '{test_db_name}'...")
            admin_cursor.execute(f"CREATE DATABASE {test_db_name}")
            print(f"   OK - Database '{test_db_name}' created!")
        else:
            print(f"   OK - Database '{test_db_name}' already exists")
        
        admin_cursor.close()
        admin_conn.close()
        
        # 4. Connect to Test DB and create tables
        test_conn = psycopg2.connect(
            host=config.database_host,
            port=config.database_port,
            user=config.database_user,
            password=config.database_password,
            database=test_db_name
        )
        test_cursor = test_conn.cursor()
        
        # Create tables (Clean Schema)
        print(f"   Creating tables in '{test_db_name}'...")
        
        # biological_networks table
        test_cursor.execute("""
            CREATE TABLE IF NOT EXISTS biological_networks (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                description TEXT,
                node_count INT NOT NULL,
                edge_count INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # network_matrices table
        test_cursor.execute("""
            CREATE TABLE IF NOT EXISTS network_matrices (
                id SERIAL PRIMARY KEY,
                network_id INT NOT NULL,
                matrix_data BYTEA NOT NULL,
                signature_hash VARCHAR(64),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (network_id) REFERENCES biological_networks(id) ON DELETE CASCADE
            )
        """)
        
        test_conn.commit()
        test_cursor.close()
        test_conn.close()
        
        print(f"   OK - Tables created in '{test_db_name}'!")
        print(f"OK - Test database setup complete!\n")
        
    except psycopg2.Error as e:
        print(f"ERROR - Database setup failed: {e}\n")
        raise
    
    yield


@pytest.fixture(scope='session')
def pydantic_config(setup_test_database):
    """
    Pydantic Config for tests
    Depends on setup_test_database to ensure correct order
    """
    os.chdir(PROJECT_ROOT)
    return get_config()


@pytest.fixture(scope='session')
def test_db_config(pydantic_config):
    """
    Test database config
    Uses TEST_DATABASE_* if set, otherwise uses production DB
    """
    config = pydantic_config
    
    return {
        'host': config.test_database_host or config.database_host,
        'port': config.test_database_port or config.database_port,
        'user': config.test_database_user or config.database_user,
        'password': config.test_database_password or config.database_password,
        'database': config.test_database_name or 'gen_test',
    }


@pytest.fixture(scope='session')
def db_connection(setup_test_database, test_db_config):
    """
    Database connection for tests
    Depends on setup_test_database to ensure DB exists before connecting
    Uses test_db_config (gen_test database)
    """
    try:
        print(f"\nAttempting Test DB connection:")
        print(f"   Host: {test_db_config['host']}")
        print(f"   User: {test_db_config['user']}")
        print(f"   Database: {test_db_config['database']}")
        
        conn = psycopg2.connect(
            host=test_db_config['host'],
            port=test_db_config['port'],
            user=test_db_config['user'],
            password=test_db_config['password'],
            database=test_db_config['database']
        )
        
        print(f"   OK - Connection successful!\n")
        yield conn
        conn.close()
        
    except psycopg2.OperationalError as e:
        print(f"   ERROR - Connection failed: {e}\n")
        raise


@pytest.fixture(scope='function')
def clean_database(db_connection):
    """
    Clean database before each test
    Deletes all data from tables to ensure test isolation
    """
    cursor = db_connection.cursor()
    
    # Delete all data from tables (cascade works)
    cursor.execute("TRUNCATE TABLE network_matrices CASCADE")
    cursor.execute("TRUNCATE TABLE biological_networks CASCADE")
    
    db_connection.commit()
    cursor.close()
    
    # HIER LAG DER FEHLER: Wir müssen db_connection zurückgeben, 
    # damit das Monkeypatching im Test die echte Verbindung erhält!
    yield db_connection
    
    # Optional: cleanup after test
    cursor = db_connection.cursor()
    cursor.execute("TRUNCATE TABLE network_matrices CASCADE")
    cursor.execute("TRUNCATE TABLE biological_networks CASCADE")
    db_connection.commit()
    cursor.close()


@pytest.fixture(scope='function')
def sample_network_data():
    """
    Provide sample network data for tests
    """
    import numpy as np
    
    return {
        'name': 'test_network_001',
        'description': 'Test network for unit tests',
        'node_count': 5,
        'edge_count': 8,
        'matrix': np.array([
            [0, 1, 1, 0, 0],
            [1, 0, 1, 1, 0],
            [1, 1, 0, 1, 1],
            [0, 1, 1, 0, 1],
            [0, 0, 1, 1, 0]
        ], dtype=np.uint8),
        'node_labels': ['Gene_A', 'Gene_B', 'Gene_C', 'Gene_D', 'Gene_E']
    }


@pytest.fixture(scope='function')
def client():
    """
    FastAPI TestClient for API tests
    """
    return TestClient(app)


def pytest_configure(config):
    """pytest Hook - called on startup"""
    os.chdir(PROJECT_ROOT)
