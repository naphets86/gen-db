"""
Tests für die Algorithmus-Auswahl im Subgraph Executor

Überprüft:
- Auffinden von libsubgraphlib.a über CSUBGRAPH_LIB_PATH (Datei oder Ordner)
- csubgraph wird genutzt, wenn der Pfad gesetzt ist; Ergebnisse werden auf das
  Python-Format abgebildet
- Python-Implementierung, wenn der Pfad nicht gesetzt ist, sowie Fallback mit
  Warnung, wenn die Bibliothek nicht nutzbar ist
- Aufbau des Link-Befehls für die Wrapper-Bibliothek (ohne echten Compiler)
- Optional: Aufruf der echten Bibliothek, wenn CSUBGRAPH_LIB_PATH gesetzt ist
"""

import os
import subprocess

import numpy as np
import pytest

from backend import csubgraph_native, subgraph_executor
from backend.csubgraph_native import NativeLibraryError, find_static_library
from backend.subgraph_executor import (
    execute_subgraph_comparison,
    get_backend_name,
    get_native_error,
    reset_backend,
)

CHAIN_2 = [[0, 1], [0, 0]]
CHAIN_4 = [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]
CHAIN_4_EXTRA_EDGE = [[0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]


class FakeConfig:
    def __init__(self, path=None):
        self.csubgraph_lib_path = path
        self.subgraph_max_workers = 2


class FakeNative:
    """Ersatz für die geladene Bibliothek; liefert feste Antworten und merkt sich die Aufrufe."""

    def __init__(self, result="KEEP_B", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def compare(self, a, b):
        self.calls.append((a.tolist(), b.tolist()))
        if self.error:
            return None, self.error
        return self.result, None


@pytest.fixture(autouse=True)
def fresh_backend():
    """Jeder Test löst den Algorithmus neu auf."""
    reset_backend()
    yield
    reset_backend()


@pytest.fixture
def fake_lib(tmp_path):
    """Datei, die wie libsubgraphlib.a aussieht."""
    lib = tmp_path / "libsubgraphlib.a"
    lib.write_bytes(b"!<arch>\n")
    return lib


def use_config(monkeypatch, config):
    monkeypatch.setattr(subgraph_executor, "_get_config_safe", lambda: config)


def use_native(monkeypatch, native):
    """csubgraph_native.load liefert das Ersatzobjekt (kein Compiler nötig)."""
    loaded = []

    def _load(setting):
        loaded.append(setting)
        return native

    monkeypatch.setattr(csubgraph_native, "load", _load)
    return loaded


class TestFindStaticLibrary:
    def test_empty_setting_returns_none(self):
        assert find_static_library(None) is None
        assert find_static_library("") is None
        assert find_static_library("   ") is None

    def test_missing_path_returns_none(self, tmp_path):
        assert find_static_library(str(tmp_path / "gibt-es-nicht")) is None

    def test_direct_file(self, fake_lib):
        assert find_static_library(str(fake_lib)) == fake_lib.resolve()

    def test_project_folder(self, fake_lib):
        assert find_static_library(str(fake_lib.parent)) == fake_lib.resolve()

    def test_build_folder(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        lib = build / "libsubgraphlib.a"
        lib.write_bytes(b"")
        assert find_static_library(str(tmp_path)) == lib.resolve()

    def test_release_subfolder(self, tmp_path):
        release = tmp_path / "build" / "Release"
        release.mkdir(parents=True)
        lib = release / "libsubgraphlib.a"
        lib.write_bytes(b"")
        assert find_static_library(str(tmp_path)) == lib.resolve()

    def test_folder_without_library(self, tmp_path):
        assert find_static_library(str(tmp_path)) is None


class TestBackendSelection:
    def test_python_when_path_not_set(self, monkeypatch):
        loaded = use_native(monkeypatch, FakeNative())
        use_config(monkeypatch, FakeConfig(path=None))
        assert get_backend_name() == "python"
        assert loaded == []

    def test_python_when_path_empty(self, monkeypatch):
        loaded = use_native(monkeypatch, FakeNative())
        use_config(monkeypatch, FakeConfig(path="  "))
        assert get_backend_name() == "python"
        assert loaded == []

    def test_python_when_no_config(self, monkeypatch):
        use_config(monkeypatch, None)
        assert get_backend_name() == "python"

    def test_python_when_library_not_found(self, monkeypatch, tmp_path, caplog):
        use_config(monkeypatch, FakeConfig(path=str(tmp_path)))
        with caplog.at_level("WARNING"):
            assert get_backend_name() == "python"
        assert "falling back to Python" in caplog.text
        assert "nicht gefunden" in get_native_error()

    def test_python_when_build_fails(self, monkeypatch, fake_lib, caplog):
        def _load(setting):
            raise NativeLibraryError("kein C++-Compiler gefunden")

        monkeypatch.setattr(csubgraph_native, "load", _load)
        use_config(monkeypatch, FakeConfig(path=str(fake_lib)))
        with caplog.at_level("WARNING"):
            assert get_backend_name() == "python"
        assert "kein C++-Compiler" in caplog.text
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == ("keep_B", None)

    def test_csubgraph_when_library_loaded(self, monkeypatch, fake_lib):
        loaded = use_native(monkeypatch, FakeNative())
        use_config(monkeypatch, FakeConfig(path=str(fake_lib)))
        assert get_backend_name() == "csubgraph"
        assert loaded == [str(fake_lib)]
        assert get_native_error() is None

    def test_resolved_only_once(self, monkeypatch, fake_lib):
        loaded = use_native(monkeypatch, FakeNative())
        use_config(monkeypatch, FakeConfig(path=str(fake_lib)))
        assert get_backend_name() == "csubgraph"
        use_config(monkeypatch, FakeConfig(path=None))
        assert get_backend_name() == "csubgraph"
        assert len(loaded) == 1


class TestCsubgraphComparison:
    @pytest.fixture(autouse=True)
    def configured(self, monkeypatch, fake_lib):
        self.native = FakeNative()
        use_native(monkeypatch, self.native)
        use_config(monkeypatch, FakeConfig(path=str(fake_lib)))

    @pytest.mark.parametrize(
        "cpp_result, expected",
        [
            ("KEEP_A", "keep_A"),
            ("KEEP_B", "keep_B"),
            ("KEEP_BOTH", "keep_both"),
            ("EQUAL_KEEP_A", "equal_keep_A"),
            ("EQUAL_KEEP_B", "equal_keep_B"),
        ],
    )
    def test_result_mapping(self, cpp_result, expected):
        self.native.result = cpp_result
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == (expected, None)

    def test_identical_keeps_a_with_more_edges(self):
        self.native.result = "IDENTICAL"
        assert execute_subgraph_comparison(CHAIN_4_EXTRA_EDGE, CHAIN_4) == ("equal_keep_A", None)

    def test_identical_keeps_b_with_more_edges(self):
        self.native.result = "IDENTICAL"
        assert execute_subgraph_comparison(CHAIN_4, CHAIN_4_EXTRA_EDGE) == ("equal_keep_B", None)

    def test_matrices_passed_to_library(self):
        execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert self.native.calls == [(CHAIN_2, CHAIN_4)]

    def test_python_algorithm_not_used(self):
        execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert subgraph_executor._algorithm is None

    def test_invalid_matrix_rejected_before_library(self):
        result, error = execute_subgraph_comparison([[0, 1]], CHAIN_4)
        assert result is None and "Invalid adjacency matrix" in error
        assert self.native.calls == []

    def test_library_error_is_returned(self):
        self.native.error = "csubgraph error: Validation error: x"
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == (
            None, "csubgraph error: Validation error: x"
        )

    def test_unknown_result(self):
        self.native.result = "WAT"
        result, error = execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert result is None and "unknown result" in error


class TestPythonFallback:
    def test_python_result_without_csubgraph(self, monkeypatch):
        use_config(monkeypatch, FakeConfig(path=None))
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == ("keep_B", None)
        assert subgraph_executor._algorithm is not None


class TestBuildSharedLibrary:
    """Link-Befehl und Cache der Wrapper-Bibliothek, ohne echten Compiler."""

    @pytest.fixture
    def build_env(self, monkeypatch, tmp_path, fake_lib):
        monkeypatch.setenv("GENDB_NATIVE_CACHE", str(tmp_path / "cache"))
        monkeypatch.setattr(csubgraph_native, "_find_compiler", lambda: "g++")
        commands = []

        def _run(command, **kwargs):
            commands.append(command)
            with open(command[command.index("-o") + 1], "wb") as handle:
                handle.write(b"fake shared library")
            return subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr(csubgraph_native.subprocess, "run", _run)
        return fake_lib, commands

    def test_command_links_static_library(self, build_env):
        lib, commands = build_env
        target = csubgraph_native.build_shared_library(lib)
        assert target.is_file()
        command = commands[0]
        assert str(csubgraph_native.SHIM_SOURCE) in command
        assert str(lib) in command
        assert "-shared" in command
        assert "-lgcov" not in command  # Attrappe ohne Coverage-Instrumentierung

    def test_coverage_runtime_linked_when_library_instrumented(self, build_env):
        lib, commands = build_env
        lib.write_bytes(b"!<arch>\n__gcov_init\n")
        csubgraph_native.build_shared_library(lib)
        assert "-lgcov" in commands[0]

    def test_result_is_cached(self, build_env):
        lib, commands = build_env
        first = csubgraph_native.build_shared_library(lib)
        second = csubgraph_native.build_shared_library(lib)
        assert first == second
        assert len(commands) == 1

    def test_changed_library_is_rebuilt(self, build_env):
        lib, commands = build_env
        first = csubgraph_native.build_shared_library(lib)
        lib.write_bytes(b"!<arch>\nanders")
        second = csubgraph_native.build_shared_library(lib)
        assert first != second
        assert len(commands) == 2

    def test_failed_build_raises_with_compiler_output(self, build_env, monkeypatch):
        lib, _ = build_env

        def _run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "undefined reference to x")

        monkeypatch.setattr(csubgraph_native.subprocess, "run", _run)
        with pytest.raises(NativeLibraryError, match="undefined reference"):
            csubgraph_native.build_shared_library(lib)

    def test_missing_compiler_raises(self, monkeypatch):
        monkeypatch.delenv("CXX", raising=False)
        monkeypatch.setattr(csubgraph_native.shutil, "which", lambda name: None)
        with pytest.raises(NativeLibraryError, match="Compiler"):
            csubgraph_native._find_compiler()


@pytest.mark.skipif(
    not find_static_library(os.environ.get("CSUBGRAPH_LIB_PATH")),
    reason="CSUBGRAPH_LIB_PATH zeigt nicht auf eine libsubgraphlib.a",
)
class TestRealLibrary:
    """Ruft die echte Bibliothek auf (benötigt Compiler und gesetzten CSUBGRAPH_LIB_PATH)."""

    @pytest.fixture
    def native(self):
        return csubgraph_native.load(os.environ["CSUBGRAPH_LIB_PATH"])

    @pytest.mark.parametrize(
        "a, b, expected",
        [
            (CHAIN_2, CHAIN_4, "KEEP_B"),
            (CHAIN_4, CHAIN_2, "KEEP_A"),
            (CHAIN_4, CHAIN_4, "IDENTICAL"),
            ([[0, 1], [1, 0]], CHAIN_4, "KEEP_BOTH"),
        ],
    )
    def test_results(self, native, a, b, expected):
        assert native.compare(np.array(a), np.array(b)) == (expected, None)

    def test_execute_uses_library(self, monkeypatch):
        use_config(monkeypatch, FakeConfig(path=os.environ["CSUBGRAPH_LIB_PATH"]))
        assert get_backend_name() == "csubgraph"
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == ("keep_B", None)
