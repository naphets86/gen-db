"""
Subgraph Executor Module

Verwaltet die parallele Ausführung des Subgraph Algorithmus mittels
ProcessPoolExecutor. Der Algorithmus ist CPU-gebunden, daher laufen die
Vergleiche in separaten Prozessen und blockieren den Webserver nicht.

ALGORITHMUS-AUSWAHL (pro Prozess einmal aufgelöst):
1. C++-Implementierung (https://github.com/naphets86/csubgraph): Wird genutzt,
   wenn CSUBGRAPH_LIB_PATH (.env) auf ``libsubgraphlib.a`` oder einen Ordner mit
   dieser Datei zeigt (Projektordner, ``build/``). Die statische Bibliothek wird
   über einen kleinen C-Wrapper zu einer DLL/.so gelinkt (siehe
   csubgraph_native.py) und direkt im Worker-Prozess aufgerufen, ohne
   Prozessstart und ohne JSON je Vergleich.
2. Python-Implementierung (Dependency aus pyproject.toml,
   https://github.com/naphets86/subgraph), ausschließlich über ihre öffentliche
   API: ``Subgraph().compare_graphs(A, B)``. Wird genutzt, wenn
   CSUBGRAPH_LIB_PATH nicht gesetzt ist. Ist er gesetzt, aber die Bibliothek
   nicht nutzbar (fehlt, kein Compiler, Build/Ladefehler), gibt es eine Warnung
   im Log und ebenfalls den Python-Fallback.

Rückgabewerte (A = Query, B = Kandidat). Beide Algorithmen liefern dieselben
Werte; die C++-Ergebnisse werden dafür umgesetzt (KEEP_B -> keep_B, ...,
IDENTICAL -> equal_keep_A/equal_keep_B nach Kantenanzahl):
- "keep_B":        A ist in B enthalten
- "keep_A":        B ist in A enthalten
- "keep_both":     keine Teilgraph-Beziehung
- "equal_keep_A":  strukturell gleich, A hat mehr Kanten (oder gleich viele)
- "equal_keep_B":  strukturell gleich, B hat mehr Kanten

KONFIGURATION VIA PYDANTIC:
- Anzahl Worker über Config.subgraph_max_workers (SUBGRAPH_MAX_WORKERS)
- Pfad zu libsubgraphlib.a über Config.csubgraph_lib_path (CSUBGRAPH_LIB_PATH)
"""

import logging
import os
import threading
from concurrent.futures import ProcessPoolExecutor, Future
from typing import List, Optional, Sequence, Tuple

import numpy as np
from subgraph import Subgraph

from . import csubgraph_native

logger = logging.getLogger(__name__)

# Globaler ProcessPoolExecutor
_executor: Optional[ProcessPoolExecutor] = None
_executor_lock = threading.Lock()

# Standard-Anzahl von Worker-Prozessen (max(cpu_count, 2))
DEFAULT_MAX_WORKERS = max(os.cpu_count() or 2, 2)

# Anzahl Vergleiche pro Task bei Batch-Verarbeitung (reduziert IPC-Overhead)
DEFAULT_CHUNKSIZE = 256

# Pro Prozess einmal erzeugte Instanz des Algorithmus
_algorithm: Optional[Subgraph] = None

# Pro Prozess einmal geladene C++-Bibliothek (None = Python-Fallback)
_native: Optional[csubgraph_native.NativeSubgraph] = None
_native_resolved = False
_native_error: Optional[str] = None

# Übersetzung der C++-Ergebnisse in die Rückgabewerte des Python-Algorithmus
_CSUBGRAPH_RESULTS = {
    "KEEP_A": "keep_A",
    "KEEP_B": "keep_B",
    "KEEP_BOTH": "keep_both",
    "EQUAL_KEEP_A": "equal_keep_A",
    "EQUAL_KEEP_B": "equal_keep_B",
}

Matrix = List[List[int]]
ComparisonResult = Tuple[Optional[str], Optional[str]]


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


def _get_native() -> Optional[csubgraph_native.NativeSubgraph]:
    """Lädt die C++-Bibliothek einmal pro Prozess (None = Python nutzen)."""
    global _native, _native_resolved, _native_error

    if not _native_resolved:
        config = _get_config_safe()
        setting = getattr(config, "csubgraph_lib_path", None) if config else None
        _native_resolved = True
        _native = None
        _native_error = None

        if setting and setting.strip():
            try:
                _native = csubgraph_native.load(setting)
            except csubgraph_native.NativeLibraryError as e:
                _native_error = str(e)
                logger.warning(
                    f"CSUBGRAPH_LIB_PATH={setting!r} not usable ({e}), "
                    "falling back to Python implementation"
                )

    return _native


def get_native_error() -> Optional[str]:
    """Grund, warum die C++-Bibliothek trotz gesetztem Pfad nicht genutzt wird (sonst None)."""
    _get_native()
    return _native_error


def reset_backend() -> None:
    """Verwirft den aufgelösten Algorithmus (neue Auflösung beim nächsten Vergleich)."""
    global _native, _native_resolved, _native_error, _algorithm

    _native = None
    _native_resolved = False
    _native_error = None
    _algorithm = None


def get_backend_name() -> str:
    """Gibt \"csubgraph\" oder \"python\" zurück (je nach aufgelöstem Algorithmus)."""
    return "csubgraph" if _get_native() else "python"


def _compare_with_csubgraph(native: csubgraph_native.NativeSubgraph,
                            matrix_a: np.ndarray, matrix_b: np.ndarray) -> ComparisonResult:
    """Vergleicht zwei Matrizen über die eingebundene C++-Bibliothek (direkter Funktionsaufruf)."""
    result, error = native.compare(matrix_a, matrix_b)
    if error:
        return None, error

    if result == "IDENTICAL":
        # Wie der Python-Algorithmus: A behalten, wenn A mindestens so viele Kanten hat
        return ("equal_keep_A" if matrix_a.sum() >= matrix_b.sum() else "equal_keep_B"), None
    if result in _CSUBGRAPH_RESULTS:
        return _CSUBGRAPH_RESULTS[result], None
    return None, f"csubgraph returned unknown result: {result!r}"


def _compare_with_python(matrix_a: np.ndarray, matrix_b: np.ndarray) -> ComparisonResult:
    """Vergleicht zwei Matrizen mit der Python-Implementierung (Fallback)."""
    global _algorithm

    if _algorithm is None:
        _algorithm = Subgraph()

    decision, _kept = _algorithm.compare_graphs(matrix_a, matrix_b)
    return decision, None


def get_executor(max_workers: Optional[int] = None) -> ProcessPoolExecutor:
    """
    Gibt globalen ProcessPoolExecutor zurück (Singleton).

    Reihenfolge für max_workers:
    1. Übergebener Parameter
    2. Config.subgraph_max_workers
    3. DEFAULT_MAX_WORKERS (cpu_count)

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
                # C++-Bibliothek vor dem Start der Worker einmalig bauen/laden, damit
                # nicht alle Worker gleichzeitig den Build anstoßen
                _get_native()
                _executor = ProcessPoolExecutor(max_workers=max_workers)
                logger.info(f"ProcessPoolExecutor initialized with {max_workers} workers")

    return _executor


def execute_subgraph_comparison(graph_a: Matrix, graph_b: Matrix) -> ComparisonResult:
    """
    Vergleicht zwei Graphen mit dem Subgraph Algorithmus.

    Nutzt csubgraph (C++-Bibliothek, wenn über CSUBGRAPH_LIB_PATH verfügbar), sonst die
    Python-Implementierung. Wird im Worker-Prozess ausgeführt. Fehler werden nicht geworfen, sondern
    als Fehlertext zurückgegeben, damit ein defekter Kandidat nicht die
    gesamte Suche abbricht.

    Args:
        graph_a: Erste Adjazenzmatrix (Query) als Liste von Listen
        graph_b: Zweite Adjazenzmatrix (Kandidat) als Liste von Listen

    Returns:
        Tuple (decision, error_message). Bei Erfolg ist error_message None.
    """
    try:
        matrix_a = np.array(graph_a, dtype=int)
        matrix_b = np.array(graph_b, dtype=int)

        for name, matrix in (("graph_a", matrix_a), ("graph_b", matrix_b)):
            if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[0] != matrix.shape[1]:
                return None, f"Invalid adjacency matrix: {name} must be a non-empty square matrix"

        native = _get_native()
        if native:
            return _compare_with_csubgraph(native, matrix_a, matrix_b)

        return _compare_with_python(matrix_a, matrix_b)

    except Exception as e:
        return None, f"Unexpected error: {str(e)}"


def _compare_to_query(query: Matrix, candidate: Matrix) -> ComparisonResult:
    """Hilfsfunktion für Batch-Verarbeitung (muss auf Modulebene liegen)."""
    return execute_subgraph_comparison(query, candidate)


def submit_comparison(graph_a: Matrix, graph_b: Matrix) -> Future:
    """
    Submittet einen Subgraph-Vergleich an den ProcessPoolExecutor.

    NICHT blockierend - gibt ein Future zurück.

    Args:
        graph_a: Erste Adjazenzmatrix
        graph_b: Zweite Adjazenzmatrix

    Returns:
        Future, dessen Ergebnis ein Tuple (decision, error_message) ist
    """
    executor = get_executor()
    return executor.submit(execute_subgraph_comparison, graph_a, graph_b)


def compare_graphs_async(graph_a: Matrix, graph_b: Matrix) -> ComparisonResult:
    """
    Blockierender Wrapper für einen einzelnen Vergleich (für sync Code).

    Args:
        graph_a: Erste Adjazenzmatrix
        graph_b: Zweite Adjazenzmatrix

    Returns:
        Tuple (decision, error_message)
    """
    return submit_comparison(graph_a, graph_b).result()


def compare_many(
    query: Matrix,
    candidates: Sequence[Matrix],
    chunksize: int = DEFAULT_CHUNKSIZE,
) -> List[ComparisonResult]:
    """
    Vergleicht eine Query-Matrix mit vielen Kandidaten parallel.

    Verteilt die Kandidaten in Chunks auf alle Worker. Die Reihenfolge der
    Ergebnisse entspricht der Reihenfolge von ``candidates``.

    Args:
        query: Adjazenzmatrix der Query
        candidates: Adjazenzmatrizen der Kandidaten
        chunksize: Anzahl Vergleiche pro Task

    Returns:
        Liste von (decision, error_message) pro Kandidat
    """
    if not candidates:
        return []

    executor = get_executor()
    return list(
        executor.map(
            _compare_to_query,
            [query] * len(candidates),
            candidates,
            chunksize=max(1, chunksize),
        )
    )


async def compare_graphs_async_await(graph_a: Matrix, graph_b: Matrix) -> ComparisonResult:
    """
    Async/await Wrapper für FastAPI-Endpoints.

    Führt den Vergleich im ProcessPoolExecutor aus, ohne den Event-Loop
    zu blockieren.

    Args:
        graph_a: Erste Adjazenzmatrix
        graph_b: Zweite Adjazenzmatrix

    Returns:
        Tuple (decision, error_message)
    """
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        get_executor(), execute_subgraph_comparison, graph_a, graph_b
    )


def shutdown_executor():
    """
    Fährt ProcessPoolExecutor herunter (cleanup).

    Sollte beim App-Shutdown aufgerufen werden.
    """
    global _executor

    if _executor is not None:
        logger.info("Shutting down ProcessPoolExecutor...")
        _executor.shutdown(wait=True)
        _executor = None
