"""
Zentrale Pydantic-basierte Konfiguration für gen-db
Supports .env Datei, Umgebungsvariablen, und Code Defaults
"""
import os
import logging
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class SubgraphConfig(BaseModel):
    """Subgraph-spezifische Konfiguration"""
    
    max_workers: Optional[int] = Field(default=None, ge=1, description="Max parallel workers")


class Config(BaseSettings):
    """
    ZENTRALE Konfiguration für gen-db
    
    Lädt aus (in dieser Reihenfolge):
    1. Umgebungsvariablen (höchste Priorität)
    2. .env Datei (Project Root)
    3. Code Defaults (niedrigste Priorität)
    """
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    # ========================================
    # DATABASE CONFIGURATION (PRODUCTION)
    # ========================================
    database_host: str = Field(default="localhost", description="Database host")
    database_port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    database_user: str = Field(default="postgres", description="Database user")
    database_password: str = Field(default="postgres", description="Database password")
    database_name: str = Field(default="gendb", description="Database name")
    database_pool_size: int = Field(default=10, ge=1, description="Connection pool size")
    database_pool_recycle: int = Field(default=3600, ge=60, description="Pool recycle time (seconds)")
    database_ssl_mode: str = Field(default="disable", description="SSL mode (disable, require, prefer)")
    
    # ========================================
    # DATABASE CONFIGURATION (TESTS)
    # ZENTRAL: Test-spezifische Datenbank-Credentials aus .env
    # ========================================
    test_database_host: Optional[str] = Field(default=None, description="Test database host")
    test_database_port: Optional[int] = Field(default=None, ge=1, le=65535, description="Test database port")
    test_database_user: Optional[str] = Field(default=None, description="Test database user")
    test_database_password: Optional[str] = Field(default=None, description="Test database password")
    test_database_name: Optional[str] = Field(default=None, description="Test database name")
    test_database_pool_size: Optional[int] = Field(default=None, ge=1, description="Test connection pool size")
    
    # ========================================
    # SUBGRAPH CONFIGURATION (ZENTRAL!)
    # ========================================
    subgraph_max_workers: Optional[int] = Field(default=None, ge=1, description="Max parallel workers")
    csubgraph_path: Optional[str] = Field(
        default=None,
        description="Pfad zur csubgraph-CLI (Datei oder Ordner); leer = Python-Implementierung"
    )
    csubgraph_timeout: float = Field(default=30.0, gt=0, description="Timeout je csubgraph-Vergleich (Sekunden)")
    
    # ========================================
    # API CONFIGURATION
    # ========================================
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, ge=1, le=65535, description="API port")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    reload: bool = Field(default=False, description="Auto-reload on code changes")
    show_sql: bool = Field(default=False, description="Show SQL queries in logs")
    
    # ========================================
    # CORS CONFIGURATION
    # ========================================
    cors_origins: List[str] = Field(default=["*"], description="CORS allowed origins")
    cors_methods: List[str] = Field(default=["*"], description="CORS allowed methods")
    cors_headers: List[str] = Field(default=["*"], description="CORS allowed headers")
    cors_credentials: bool = Field(default=True, description="CORS allow credentials")
    
    # ========================================
    # SECURITY
    # ========================================
    secret_key: str = Field(default="change-in-production", description="Secret key for JWT")
    max_upload_size: int = Field(default=10485760, ge=1048576, description="Max upload size in bytes")
    
    # ========================================
    # ENVIRONMENT
    # ========================================
    container_env: str = Field(default="development", description="Container environment")
    generate_fake_data: bool = Field(default=False, description="Generate fake data on startup")
    fake_data_count: int = Field(default=10, ge=1, description="Number of fake records")
    
    def get_database_url(self) -> str:
        """
        Konstruiert Production Database URL
        
        Format: postgresql://user:password@host:port/database
        """
        return (
            f"postgresql://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )
    
    def get_test_database_config(self) -> Dict[str, Any]:
        """
        ZENTRAL: Gibt Test-Datenbank-Config zurück
        
        Nutzt TEST_DATABASE_* Variablen aus .env
        Falls nicht gesetzt, fällt zurück auf Defaults:
        - host: localhost
        - port: 5432
        - user: dbuser
        - password: dbpassword
        - database: gen_test
        - pool_size: 5
        
        Returns:
            Dict mit keys: host, port, user, password, database, pool_size
        """
        return {
            'host': self.test_database_host or 'localhost',
            'port': self.test_database_port or 5432,
            'user': self.test_database_user or 'dbuser',
            'password': self.test_database_password or 'dbpassword',
            'database': self.test_database_name or 'gen_test',
            'pool_size': self.test_database_pool_size or 5,
        }
    
    def get_subgraph_config(self) -> SubgraphConfig:
        """
        Gibt SubgraphConfig Objekt zurück
        
        Returns:
            SubgraphConfig mit max_workers
        """
        return SubgraphConfig(
            max_workers=self.subgraph_max_workers
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert Config zu Dictionary"""
        return self.model_dump()


# ========================================
# Singleton Pattern für Config
# ========================================

_config_instance: Optional[Config] = None


def get_config() -> Config:
    """
    Gibt Config Singleton zurück
    
    Lädt Konfiguration aus:
    1. .env Datei (Project Root)
    2. Umgebungsvariablen
    3. Code Defaults
    
    Returns:
        Config Singleton Instanz
    
    Raises:
        ConfigError: Falls Konfiguration invalid ist
    """
    global _config_instance
    
    if _config_instance is not None:
        return _config_instance
    
    try:
        _config_instance = Config()
        logger.info(f"Configuration loaded (ENV={_config_instance.container_env})")
        return _config_instance
    except Exception as e:
        raise ConfigError(f"Konfigurationsfehler: {e}") from e


def reload_config() -> Config:
    """
    Erstellt neue Config Instanz
    
    Nutze nur in Tests zum Neu-Laden der Konfiguration!
    
    Returns:
        Neue Config Instanz
    
    Raises:
        ConfigError: Falls Konfiguration invalid ist
    """
    global _config_instance
    
    try:
        _config_instance = Config()
        logger.info(f"Configuration reloaded (ENV={_config_instance.container_env})")
        return _config_instance
    except Exception as e:
        raise ConfigError(f"Konfigurationsfehler beim Reload: {e}") from e


class ConfigError(Exception):
    """Exception für Konfigurationsfehler"""
    pass
