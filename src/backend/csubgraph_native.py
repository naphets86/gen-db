"""
Anbindung der statischen C++-Bibliothek ``libsubgraphlib.a`` (csubgraph).

Python kann eine statische Bibliothek nicht direkt laden. Dieses Modul linkt
sie deshalb beim ersten Gebrauch mit einem kleinen C-Wrapper
(``native/csubgraph_shim.cpp``) zu einer gemeinsam genutzten Bibliothek
(``.dll``/``.so``) und ruft diese per ``ctypes`` im selben Prozess auf. Es gibt
keinen Prozessstart und keine JSON-Kodierung je Vergleich.

Voraussetzungen:
- ein C++-Compiler (``g++``, bei Windows derselbe MinGW-w64 wie beim Bauen der
  Bibliothek) im ``PATH`` oder über die Umgebungsvariable ``CXX``
- die Bibliothek muss mit demselben Compiler gebaut sein

Die gelinkte Bibliothek wird in einem Cache-Ordner abgelegt und nur neu gebaut,
wenn sich ``libsubgraphlib.a``, der Wrapper oder der Header ändern.

Multi-Omics: Die Mehrschicht-Erweiterung (``MultiOmics.h``) wird über einen zweiten
Wrapper (``native/csubgraph_omics_shim.cpp``) angebunden, der getrennt gebaut und
geladen wird. Dieselbe Einstellung ``CSUBGRAPH_LIB_PATH`` findet die Bibliothek; enthält
eine ältere ``libsubgraphlib.a`` die Klasse ``MultiOmics`` nicht, bleibt der
Einzelvergleich über ``NativeSubgraph`` nutzbar und nur Multi-Omics fällt auf Python zurück.
"""

import ctypes
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

NATIVE_DIR = Path(__file__).resolve().parent / "native"
SHIM_SOURCE = NATIVE_DIR / "csubgraph_shim.cpp"
BUNDLED_HEADER_DIR = NATIVE_DIR
HEADER_NAME = "SubgraphAlgorithm.h"
LIB_NAME = "libsubgraphlib.a"
SHIM_ABI_VERSION = 1
OMICS_SHIM_SOURCE = NATIVE_DIR / "csubgraph_omics_shim.cpp"
OMICS_HEADER_NAME = "MultiOmics.h"
OMICS_SHIM_ABI_VERSION = 1
ERROR_BUFFER_SIZE = 512
BUILD_TIMEOUT = 300

# Modus und Strategie der Multi-Omics-Schnittstelle (wie MultiOmics::Mode / ::Strategy)
OMICS_MODES = {"coherent": 0, "independent": 1}
OMICS_STRATEGY_BIGRAM = 0
OMICS_STRATEGY_DYNAMIC = 1

# result_code der Bibliothek (wie in Cli.cpp)
RESULT_NAMES = {
    0: "KEEP_A",
    1: "KEEP_B",
    2: "KEEP_BOTH",
    3: "IDENTICAL",
    4: "EQUAL_KEEP_A",
    5: "EQUAL_KEEP_B",
}


class NativeLibraryError(Exception):
    """Bibliothek nicht auffindbar, nicht baubar oder nicht ladbar (-> Fallback auf Python)."""


@dataclass(frozen=True)
class ShimSpec:
    """Beschreibt einen C-Wrapper: Quelle, Schnittstellenversion und benötigte Header."""

    source: Path
    abi: int
    headers: Tuple[str, ...]
    label: str


BASE_SHIM = ShimSpec(SHIM_SOURCE, SHIM_ABI_VERSION, (HEADER_NAME,), "csubgraph_shim")
OMICS_SHIM = ShimSpec(
    OMICS_SHIM_SOURCE, OMICS_SHIM_ABI_VERSION, (HEADER_NAME, OMICS_HEADER_NAME), "csubgraph_omics_shim"
)


def find_static_library(path_setting: Optional[str]) -> Optional[Path]:
    """
    Löst CSUBGRAPH_LIB_PATH auf.

    Args:
        path_setting: Pfad zu ``libsubgraphlib.a`` oder zu einem Ordner, der sie enthält
            (csubgraph-Projektordner oder ``build/``)

    Returns:
        Absoluter Pfad zur Bibliothek oder None (leere Einstellung oder nichts gefunden)
    """
    if not path_setting or not path_setting.strip():
        return None

    base = Path(path_setting.strip()).expanduser()
    if base.is_file():
        return base.resolve()

    for sub in ("", "build", "build/Release", "Release"):
        candidate = base / sub / LIB_NAME
        if candidate.is_file():
            return candidate.resolve()
    return None


def _find_header_dir(lib: Path, headers: Sequence[str] = (HEADER_NAME,)) -> Path:
    """Header neben der Bibliothek (Projektordner), sonst die mitgelieferte Kopie."""
    for directory in (lib.parent, lib.parent.parent, lib.parent.parent / "include"):
        if all((directory / name).is_file() for name in headers):
            return directory
    return BUNDLED_HEADER_DIR


def _has_multiomics(lib: Path) -> bool:
    """Enthält das Archiv die Klasse ``MultiOmics``? (ältere Builds kennen sie noch nicht)"""
    return b"MultiOmics" in lib.read_bytes()


def _has_coverage_instrumentation(lib: Path) -> bool:
    """csubgraph wird per CMake mit --coverage gebaut; dann braucht der Link libgcov."""
    return b"__gcov_init" in lib.read_bytes()


def _find_compiler() -> str:
    candidates = [os.environ.get("CXX"), "g++", "c++", "clang++"]
    for name in candidates:
        if name and shutil.which(name):
            return shutil.which(name)
    raise NativeLibraryError(
        "kein C++-Compiler gefunden (g++ in den PATH legen oder Umgebungsvariable CXX setzen)"
    )


def _shared_suffix() -> str:
    return ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"


def _cache_path(lib: Path, header_dir: Path, spec: ShimSpec = BASE_SHIM) -> Path:
    digest = hashlib.sha256()
    digest.update(lib.read_bytes())
    digest.update(spec.source.read_bytes())
    for name in spec.headers:
        digest.update((header_dir / name).read_bytes())
    digest.update(str(spec.abi).encode())
    cache_dir = Path(os.environ.get("GENDB_NATIVE_CACHE") or Path(tempfile.gettempdir()) / "gen-db-csubgraph")
    return cache_dir / f"{spec.label}_{digest.hexdigest()[:16]}{_shared_suffix()}"


def build_shared_library(lib: Path, spec: ShimSpec = BASE_SHIM) -> Path:
    """
    Linkt ``libsubgraphlib.a`` und den Wrapper zu einer ladbaren Bibliothek.

    Bereits gebaute, passende Ergebnisse werden wiederverwendet. Der Build läuft
    in eine temporäre Datei und wird atomar umbenannt, damit parallel startende
    Worker-Prozesse sich nicht gegenseitig eine halbe Datei laden lassen.

    Args:
        lib: Pfad zu ``libsubgraphlib.a``
        spec: Wrapper, der gelinkt wird (Standard: Einzelvergleich; ``OMICS_SHIM``: Multi-Omics)

    Raises:
        NativeLibraryError: Compiler fehlt oder Build schlägt fehl
    """
    header_dir = _find_header_dir(lib, spec.headers)
    target = _cache_path(lib, header_dir, spec)
    if target.is_file():
        return target

    compiler = _find_compiler()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.stem}.{os.getpid()}.tmp{target.suffix}")

    command = [compiler, "-std=c++17", "-O2", "-shared", "-I", str(header_dir), str(spec.source)]
    if sys.platform != "win32":
        command.insert(2, "-fPIC")
    # Die Bibliothek ist der gesamte Archivinhalt, nicht nur das, was der Wrapper direkt braucht
    command += ["-Wl,--whole-archive", str(lib), "-Wl,--no-whole-archive"] if sys.platform != "darwin" \
        else ["-Wl,-force_load," + str(lib)]
    if _has_coverage_instrumentation(lib):
        command.append("-lgcov")  # nur die Laufzeit, den Wrapper selbst nicht instrumentieren
    if sys.platform == "win32":
        # Keine MinGW-Laufzeit-DLLs nachladen müssen (libstdc++-6.dll usw.)
        command += ["-static-libgcc", "-static-libstdc++", "-static"]
    command += ["-o", str(temp)]

    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise NativeLibraryError(f"Build der Wrapper-Bibliothek nicht möglich: {e}") from e
    if proc.returncode != 0:
        temp.unlink(missing_ok=True)
        raise NativeLibraryError(
            f"Build der Wrapper-Bibliothek fehlgeschlagen ({' '.join(command)}):\n{proc.stderr.strip()}"
        )

    try:
        os.replace(temp, target)
    except OSError:
        # Anderer Prozess war schneller und hat die Datei schon geladen (Windows)
        temp.unlink(missing_ok=True)
        if not target.is_file():
            raise
    logger.info("Built csubgraph wrapper library: %s", target)
    return target


class NativeSubgraph:
    """Geladene Bibliothek; ``compare`` entspricht einem Aufruf von SubgraphAlgorithm::compareGraphs."""

    def __init__(self, shared_library: Path):
        try:
            self._dll = ctypes.CDLL(str(shared_library))
            self._dll.csub_abi_version.restype = ctypes.c_int
            abi = self._dll.csub_abi_version()
        except (OSError, AttributeError) as e:
            raise NativeLibraryError(f"Wrapper-Bibliothek nicht ladbar: {e}") from e
        if abi != SHIM_ABI_VERSION:
            raise NativeLibraryError(f"Wrapper-Version {abi} statt {SHIM_ABI_VERSION}")

        int_ptr = ctypes.POINTER(ctypes.c_int)
        self._dll.csub_compare.argtypes = [
            int_ptr, ctypes.c_int, int_ptr, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
        ]
        self._dll.csub_compare.restype = ctypes.c_int
        self.path = str(shared_library)

    def compare(self, matrix_a: np.ndarray, matrix_b: np.ndarray) -> Tuple[Optional[str], Optional[str]]:
        """
        Returns:
            (Ergebnisname wie ``KEEP_A``/``IDENTICAL``, None) oder (None, Fehlertext)
        """
        a = np.ascontiguousarray(matrix_a, dtype=np.intc)
        b = np.ascontiguousarray(matrix_b, dtype=np.intc)
        error = ctypes.create_string_buffer(ERROR_BUFFER_SIZE)
        code = self._dll.csub_compare(
            a.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), a.shape[0],
            b.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), b.shape[0],
            error, ERROR_BUFFER_SIZE,
        )
        if code < 0:
            return None, f"csubgraph error: {error.value.decode('utf-8', 'replace')}"
        name = RESULT_NAMES.get(code)
        if name is None:
            return None, f"csubgraph returned unknown result: {code!r}"
        return name, None


class NativeMultiOmics:
    """Geladene Multi-Omics-Schnittstelle; ``compare`` entspricht MultiOmics::compareLayered."""

    def __init__(self, shared_library: Path):
        try:
            self._dll = ctypes.CDLL(str(shared_library))
            self._dll.csub_omics_abi_version.restype = ctypes.c_int
            abi = self._dll.csub_omics_abi_version()
        except (OSError, AttributeError) as e:
            raise NativeLibraryError(f"Multi-Omics-Wrapper nicht ladbar: {e}") from e
        if abi != OMICS_SHIM_ABI_VERSION:
            raise NativeLibraryError(f"Multi-Omics-Wrapper-Version {abi} statt {OMICS_SHIM_ABI_VERSION}")

        int_ptr = ctypes.POINTER(ctypes.c_int)
        self._dll.csub_omics_compare.argtypes = [
            int_ptr, ctypes.c_int, ctypes.c_int,
            int_ptr, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int,
            ctypes.c_char_p, ctypes.c_int,
        ]
        self._dll.csub_omics_compare.restype = ctypes.c_int
        self.path = str(shared_library)

    def compare(self, layers_a: np.ndarray, layers_b: np.ndarray, mode: str = "coherent",
                strategy: int = OMICS_STRATEGY_BIGRAM) -> Tuple[Optional[str], Optional[str]]:
        """
        Args:
            layers_a: Schichtstapel der Form (L, n, n)
            layers_b: Schichtstapel der Form (L, m, m)
            mode: ``"coherent"`` oder ``"independent"``
            strategy: ``OMICS_STRATEGY_BIGRAM`` (schnell) oder ``OMICS_STRATEGY_DYNAMIC``

        Returns:
            (Ergebnisname wie ``KEEP_A``/``IDENTICAL``, None) oder (None, Fehlertext)
        """
        if mode not in OMICS_MODES:
            return None, f"csubgraph error: unknown mode {mode!r}"
        a = np.ascontiguousarray(layers_a, dtype=np.intc)
        b = np.ascontiguousarray(layers_b, dtype=np.intc)
        if a.ndim != 3 or b.ndim != 3:
            return None, "csubgraph error: layer stacks must have shape (layers, n, n)"
        error = ctypes.create_string_buffer(ERROR_BUFFER_SIZE)
        code = self._dll.csub_omics_compare(
            a.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), a.shape[0], a.shape[1],
            b.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), b.shape[0], b.shape[1],
            OMICS_MODES[mode], strategy,
            error, ERROR_BUFFER_SIZE,
        )
        if code < 0:
            return None, f"csubgraph error: {error.value.decode('utf-8', 'replace')}"
        name = RESULT_NAMES.get(code)
        if name is None:
            return None, f"csubgraph returned unknown result: {code!r}"
        return name, None


def load_multiomics(path_setting: Optional[str]) -> NativeMultiOmics:
    """
    Findet, baut und lädt die Multi-Omics-Schnittstelle (gleiche Einstellung wie ``load``).

    Raises:
        NativeLibraryError: Bibliothek fehlt, enthält ``MultiOmics`` nicht (neu bauen),
            oder Build/Laden scheitert
    """
    lib = find_static_library(path_setting)
    if lib is None:
        raise NativeLibraryError(f"{LIB_NAME} nicht gefunden (CSUBGRAPH_LIB_PATH={path_setting!r})")
    if not _has_multiomics(lib):
        raise NativeLibraryError(
            f"{lib} enthält keine MultiOmics-Klasse (csubgraph mit MultiOmics.cpp neu bauen)"
        )
    return NativeMultiOmics(build_shared_library(lib, OMICS_SHIM))


def load(path_setting: Optional[str]) -> NativeSubgraph:
    """
    Findet, baut und lädt die Bibliothek.

    Raises:
        NativeLibraryError: mit lesbarer Ursache, wenn etwas davon scheitert
    """
    lib = find_static_library(path_setting)
    if lib is None:
        raise NativeLibraryError(f"{LIB_NAME} nicht gefunden (CSUBGRAPH_LIB_PATH={path_setting!r})")
    return NativeSubgraph(build_shared_library(lib))
