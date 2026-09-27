"""
Subgraph Executor Module

Verwaltet parallele Ausführung des C++-basierten Subgraph-Algorithmus
mittels ProcessPoolExecutor. Dies ermöglicht nicht-blockierende Requests.

Die C++-Implementierung (aus csubgraph) wird als CLI-Tool aufgerufen,
das JSON via stdin/stdout verarbeitet.

ZENTRALE KONFIGURATION VIA PYDANTIC:
- Nutzt get_config() von config.py
- Subgraph Settings über Config.get_subgraph_config()
- Umgebungsvariablen und .env automatisch integriert
"""

import logging
import json
import subprocess
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Tuple, Optional, Dict, List
from functools import lru_cache
import threading

logger = logging.getLogger(__name__)

# Globaler ProcessPoolExecutor
_executor = None
_executor_lock = threading.Lock()

# Standard-Anzahl von Worker-Prozessen (max(cpu_count, 2))
DEFAULT_MAX_WORKERS = max(os.cpu_count() or 2, 2)


def _get_config_safe():
    """
    Gibt Config Instanz zurück (mit Fallback für Tests ohne Config)
    
    Returns:
        Config Instanz oder None wenn nicht verfügbar
    """
    try:
        from .config import get_config
        return get_config()
    except Exception as e:
        logger.debug(f"Could not load config: {e}")
        return None


def get_executor(max_workers: Optional[int] = None) -> ProcessPoolExecutor:
    """
    Gibt globalen ProcessPoolExecutor zurück (Singleton).
    
    Nutzt Pydantic Config für max_workers wenn nicht übergeben:
    1. Nutzt Config.subgraph_max_workers wenn gesetzt
    2. Fällt zurück auf DEFAULT_MAX_WORKERS (cpu_count)
    
    Args:
        max_workers: Maximale Anzahl paralleler Prozesse (optional)
        
    Returns:
        ProcessPoolExecutor Instanz
    """
    global _executor
    
    if max_workers is None:
        config = _get_config_safe()
        if config and config.subgraph_max_workers:
            max_workers = config.subgraph_max_workers
        else:
            max_workers = DEFAULT_MAX_WORKERS
    
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ProcessPoolExecutor(max_workers=max_workers)
                logger.info(f"ProcessPoolExecutor initialized with {max_workers} workers (via Pydantic Config)")
    
    return _executor


@lru_cache(maxsize=1)
def get_cli_path() -> Optional[str]:
    """
    Findet den Pfad zur subgraph-cli Binärdatei.
    
    ZENTRALE LÖSUNG via Pydantic Config:
    1. Nutzt Config.subgraph_cli_path (aus .env oder Env-Var)
    2. Prüft SUBGRAPH_CLI_PATH Umgebungsvariable (Fallback)
    3. Relative Pfade (../../../csubgraph-main/build/subgraph-cli)
    4. System PATH (/usr/local/bin/subgraph-cli)
    
    Returns:
        Pfad zur CLI oder None wenn nicht gefunden
        
    Note:
        Die Pydantic Config integriert SUBGRAPH_CLI_PATH automatisch,
        daher ist diese Funktion zentral konfigurierbar.
    """
    # 1. Nutze Pydantic Config (hat bereits Env-Var geladen)
    config = _get_config_safe()
    if config and config.subgraph_cli_path:
        if os.path.isfile(config.subgraph_cli_path):
            logger.debug(f"Found subgraph-cli via Pydantic Config: {config.subgraph_cli_path}")
            return config.subgraph_cli_path
        else:
            logger.warning(f"Config specifies {config.subgraph_cli_path} but file does not exist")
    
    # 2. Fallback: Umgebungsvariable prüfen (für Legacy Support)
    env_path = os.environ.get('SUBGRAPH_CLI_PATH')
    if env_path and os.path.isfile(env_path):
        logger.debug(f"Found subgraph-cli via SUBGRAPH_CLI_PATH env var: {env_path}")
        return env_path
    
    # 3. Relative Pfade prüfen (von gen-db/src/backend aus)
    relative_paths = [
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'csubgraph-main', 'build', 'subgraph-cli'),
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'csubgraph-main', 'build', 'subgraph-cli.exe'),
        './subgraph-cli',
        './subgraph-cli.exe',
    ]
    
    for path in relative_paths:
        abs_path = os.path.abspath(path)
        if os.path.isfile(abs_path):
            logger.debug(f"Found subgraph-cli at relative path: {abs_path}")
            return abs_path
    
    # 4. System PATH prüfen
    for system_path in ['/usr/local/bin/subgraph-cli', 'C:\\Program Files\\subgraph\\subgraph-cli.exe']:
        if os.path.isfile(system_path):
            logger.debug(f"Found subgraph-cli at system path: {system_path}")
            return system_path
    
    logger.warning(
        "subgraph-cli binary not found. "
        "Set via: SUBGRAPH_CLI_PATH=/path/to/subgraph-cli or "
        "SUBGRAPH_CLI_PATH in .env file or "
        "Config.subgraph_cli_path in code"
    )
    return None


def execute_subgraph_comparison(graph_a: List[List[int]], graph_b: List[List[int]]) -> Tuple[str, Optional[str]]:
    """
    Führt C++-basierten Subgraph-Vergleich aus.
    
    Diese Funktion wird in einem separaten Prozess ausgeführt, um
    CPU-intensive C++-Berechnungen nicht zu blockieren.
    
    Timeout wird aus Pydantic Config gelesen (subgraph_timeout).
    
    Args:
        graph_a: Erste Adjazenzmatrix als Liste von Listen
        graph_b: Zweite Adjazenzmatrix als Liste von Listen
        
    Returns:
        Tuple (result_string, error_message) wobei error_message None bei Erfolg
        
    Raises:
        RuntimeError: Wenn subgraph-cli nicht gefunden
        subprocess.CalledProcessError: Wenn CLI-Ausführung fehlschlägt
    """
    cli_path = get_cli_path()
    
    if not cli_path:
        raise RuntimeError(
            "subgraph-cli binary not found. "
            "Set SUBGRAPH_CLI_PATH or in .env: SUBGRAPH_CLI_PATH=/path/to/cli"
        )
    
    # Get timeout from Pydantic Config
    config = _get_config_safe()
    timeout = config.subgraph_timeout if config else 30
    
    # Prepare input JSON
    input_data = {
        "graph_a": graph_a,
        "graph_b": graph_b
    }
    
    try:
        # Rufe C++-CLI-Tool auf (Timeout aus Config)
        result = subprocess.run(
            [cli_path],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=timeout,  # Aus Config gelesen
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            logger.error(f"subgraph-cli failed: {error_msg}")
            return None, f"CLI error: {error_msg}"
        
        # Parse output JSON
        output = json.loads(result.stdout)
        
        if output.get("error"):
            return None, output["error"]
        
        result_str = output.get("result")
        return result_str, None
        
    except subprocess.TimeoutExpired:
        config = _get_config_safe()
        timeout_secs = config.subgraph_timeout if config else 30
        return None, f"Subgraph comparison timed out ({timeout_secs}s)"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON from CLI: {str(e)}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"


def submit_comparison(graph_a: List[List[int]], graph_b: List[List[int]]) -> str:
    """
    Submittet Subgraph-Vergleich an ProcessPoolExecutor.
    
    NICHT blockierend - gibt Future ID zurück für Polling/Callbacks.
    
    Args:
        graph_a: Erste Adjazenzmatrix
        graph_b: Zweite Adjazenzmatrix
        
    Returns:
        Future Objekt für spätere Ergebnisabfrage
    """
    executor = get_executor()
    future = executor.submit(execute_subgraph_comparison, graph_a, graph_b)
    return future


def compare_graphs_async(graph_a: List[List[int]], graph_b: List[List[int]]) -> Tuple[str, Optional[str]]:
    """
    Blockierende Wrapper für C++-Subgraph-Vergleich (für sync Code).
    
    Nutzt ProcessPoolExecutor intern, blockiert aber bis Ergebnis vorliegt.
    Mehrere parallel aufgerufene Instanzen blockieren sich nicht gegenseitig.
    
    Args:
        graph_a: Erste Adjazenzmatrix
        graph_b: Zweite Adjazenzmatrix
        
    Returns:
        Tuple (result_string, error_message)
    """
    future = submit_comparison(graph_a, graph_b)
    return future.result()  # Wartet auf Ergebnis


async def compare_graphs_async_await(graph_a: List[List[int]], graph_b: List[List[int]]) -> Tuple[str, Optional[str]]:
    """
    Async/await wrapper für C++-Subgraph-Vergleich (für async FastAPI).
    
    Ermöglicht nicht-blockierende Warte in FastAPI async Endpoints.
    
    Args:
        graph_a: Erste Adjazenzmatrix
        graph_b: Zweite Adjazenzmatrix
        
    Returns:
        Tuple (result_string, error_message)
    """
    import asyncio
    
    loop = asyncio.get_event_loop()
    
    # Führe sync Funktion in Thread Pool aus
    return await loop.run_in_executor(
        None,
        execute_subgraph_comparison,
        graph_a,
        graph_b
    )


def shutdown_executor():
    """
    Fahrt ProcessPoolExecutor herunter (cleanup).
    
    Sollte beim App-Shutdown aufgerufen werden.
    """
    global _executor
    
    if _executor is not None:
        logger.info("Shutting down ProcessPoolExecutor...")
        _executor.shutdown(wait=True)
        _executor = None
