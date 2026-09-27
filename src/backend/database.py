import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import logging
from .config import get_config

logger = logging.getLogger(__name__)


def get_database_config():
    """
    Holt Datenbank-Konfiguration aus der Pydantic Config
    
    Returns:
        Dictionary mit Datenbankverbindungsparametern
    """
    config = get_config()
    return {
        'dbname': config.database_name,
        'user': config.database_user,
        'password': config.database_password,
        'host': config.database_host,
        'port': config.database_port,
    }


@contextmanager
def get_db_connection():
    """
    Stellt eine Verbindung zur Datenbank her und schließt sie nach der Nutzung automatisch.
    Verwendet den Context-Manager-Ansatz für das 'with'-Statement.
    """
    config = get_config()
    
    # Verbindung zur echten Datenbank aufbauen
    conn = psycopg2.connect(
        host=config.database_host,
        port=config.database_port,
        user=config.database_user,
        password=config.database_password,
        database=config.database_name
    )
    try:
        yield conn       # Übergibt das Verbindungsobjekt an den 'with'-Block
        conn.commit()    # Speichert Änderungen bei Erfolg
    except Exception:
        conn.rollback()  # Rollt bei Fehlern alles zurück
        raise
    finally:
        conn.close()     # Schließt die Verbindung garantiert am Ende


def get_db_cursor(conn):
    """Get a cursor with RealDictCursor for dict-like results"""
    return conn.cursor(cursor_factory=RealDictCursor)
