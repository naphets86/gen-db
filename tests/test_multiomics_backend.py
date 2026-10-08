"""
Tests für die Multi-Omics-Anbindung von csubgraph (MultiOmics) über CSUBGRAPH_LIB_PATH

Überprüft:
- Laden über denselben Pfad wie der Einzelvergleich; getrennter Fallback auf Python
- Aufbau des Link-Befehls für den Multi-Omics-Wrapper (ohne echten Compiler)
- Aufruf der Schnittstelle (Schichtstapel als (L, n, n)-Feld) und Abbildung der Ergebnisse
- Optional: Aufruf der echten Bibliothek, wenn CSUBGRAPH_LIB_PATH auf eine
  libsubgraphlib.a mit MultiOmics zeigt (Vergleich mit der Python-Implementierung)
"""

import os
import random
import subprocess

import numpy as np
import pytest

from backend import csubgraph_native, multiomics_python, subgraph_executor
from backend.csubgraph_native import NativeLibraryError, find_static_library
from backend.subgraph_executor import (
    execute_multiomics_comparison,
    get_backend_name,
    get_multiomics_backend_name,
    get_multiomics_native_error,
    reset_backend,
)

CHAIN_3 = [[0, 1, 0], [0, 0, 1], [0, 0, 0]]
CHAIN_4 = [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]
CHAIN_4_EXTRA_EDGE = [[0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]
RING_3 = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]


class FakeConfig:
    def __init__(self, path=None):
        self.csubgraph_lib_path = path
        self.subgraph_max_workers = 2


class FakeOmics:
    """Ersatz für die geladene Multi-Omics-Schnittstelle; liefert feste Antworten."""

    def __init__(self, result="KEEP_B", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def compare(self, a, b, mode="coherent", strategy=0):
        self.calls.append((a.tolist(), b.tolist(), mode))
        if self.error:
            return None, self.error
        return self.result, None


class FakeFunction:
    """Aufrufbares ctypes-Funktionsobjekt mit argtypes/restype."""

    def __init__(self, func):
        self.func = func
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.func(*args)


class FakeDll:
    def __init__(self, abi=1, code=1, message=b""):
        self.calls = []
        self.csub_omics_abi_version = FakeFunction(lambda: abi)

        def _compare(*args):
            self.calls.append(args)
            if code < 0:
                args[-2].value = message
            return code

        self.csub_omics_compare = FakeFunction(_compare)


@pytest.fixture(autouse=True)
def fresh_backend():
    reset_backend()
    yield
    reset_backend()


@pytest.fixture
def fake_lib(tmp_path):
    """Datei, die wie eine libsubgraphlib.a mit MultiOmics aussieht."""
    lib = tmp_path / "libsubgraphlib.a"
    lib.write_bytes(b"!<arch>\n_ZN10MultiOmics15compareLayeredE\n")
    return lib


def use_config(monkeypatch, config):
    monkeypatch.setattr(subgraph_executor, "_get_config_safe", lambda: config)


def use_omics(monkeypatch, native):
    loaded = []

    def _load(setting):
        loaded.append(setting)
        return native

    monkeypatch.setattr(csubgraph_native, "load_multiomics", _load)
    return loaded


class TestLoadMultiOmics:
    def test_missing_library(self, tmp_path):
        with pytest.raises(NativeLibraryError, match="nicht gefunden"):
            csubgraph_native.load_multiomics(str(tmp_path))

    def test_empty_setting(self):
        with pytest.raises(NativeLibraryError, match="nicht gefunden"):
            csubgraph_native.load_multiomics(None)

    def test_old_library_without_multiomics(self, tmp_path):
        lib = tmp_path / "libsubgraphlib.a"
        lib.write_bytes(b"!<arch>\n_ZN13SubgraphAlgorithm12compareGraphsE\n")
        with pytest.raises(NativeLibraryError, match="MultiOmics"):
            csubgraph_native.load_multiomics(str(lib))

    def test_has_multiomics_detection(self, tmp_path, fake_lib):
        assert csubgraph_native._has_multiomics(fake_lib) is True
        other = tmp_path / "other.a"
        other.write_bytes(b"!<arch>\n")
        assert csubgraph_native._has_multiomics(other) is False

    def test_builds_omics_wrapper_and_loads_it(self, monkeypatch, fake_lib):
        built = []
        dll = FakeDll()

        def _build(lib, spec=csubgraph_native.BASE_SHIM):
            built.append((lib, spec))
            return fake_lib.parent / "wrapper.so"

        monkeypatch.setattr(csubgraph_native, "build_shared_library", _build)
        monkeypatch.setattr(csubgraph_native.ctypes, "CDLL", lambda path: dll)
        native = csubgraph_native.load_multiomics(str(fake_lib))
        assert isinstance(native, csubgraph_native.NativeMultiOmics)
        assert built == [(fake_lib.resolve(), csubgraph_native.OMICS_SHIM)]
        assert native.path.endswith("wrapper.so")

    def test_unloadable_wrapper(self, tmp_path):
        broken = tmp_path / "kaputt.so"
        broken.write_bytes(b"kein shared object")
        with pytest.raises(NativeLibraryError, match="nicht ladbar"):
            csubgraph_native.NativeMultiOmics(broken)

    def test_wrapper_without_expected_symbol(self, monkeypatch, tmp_path):
        class NoSymbol:
            def __getattr__(self, name):
                raise AttributeError(name)

        monkeypatch.setattr(csubgraph_native.ctypes, "CDLL", lambda path: NoSymbol())
        with pytest.raises(NativeLibraryError, match="nicht ladbar"):
            csubgraph_native.NativeMultiOmics(tmp_path / "x.so")

    def test_wrong_abi_version(self, monkeypatch, tmp_path):
        monkeypatch.setattr(csubgraph_native.ctypes, "CDLL", lambda path: FakeDll(abi=99))
        with pytest.raises(NativeLibraryError, match="Version 99"):
            csubgraph_native.NativeMultiOmics(tmp_path / "x.so")


class TestNativeMultiOmicsCompare:
    @pytest.fixture
    def native(self, monkeypatch, tmp_path):
        self.dll = FakeDll(code=1)
        monkeypatch.setattr(csubgraph_native.ctypes, "CDLL", lambda path: self.dll)
        return csubgraph_native.NativeMultiOmics(tmp_path / "x.so")

    def test_result_name_and_arguments(self, native):
        a = np.array([CHAIN_3, RING_3])
        b = np.array([CHAIN_4, CHAIN_4])
        assert native.compare(a, b, "independent") == ("KEEP_B", None)
        args = self.dll.calls[0]
        # Schichtzahl, Knotenzahl, Modus (1 = unabhängig), Strategie (0 = Bigramm)
        assert (args[1], args[2], args[4], args[5]) == (2, 3, 2, 4)
        assert (args[6], args[7]) == (1, csubgraph_native.OMICS_STRATEGY_BIGRAM)

    def test_default_mode_is_coherent(self, native):
        native.compare(np.array([CHAIN_3]), np.array([CHAIN_4]))
        assert self.dll.calls[0][6] == 0

    def test_dynamic_strategy_is_passed(self, native):
        native.compare(np.array([CHAIN_3]), np.array([CHAIN_4]), "coherent",
                       csubgraph_native.OMICS_STRATEGY_DYNAMIC)
        assert self.dll.calls[0][7] == 1

    @pytest.mark.parametrize(
        "code, name",
        [(0, "KEEP_A"), (1, "KEEP_B"), (2, "KEEP_BOTH"), (3, "IDENTICAL"),
         (4, "EQUAL_KEEP_A"), (5, "EQUAL_KEEP_B")],
    )
    def test_all_result_codes(self, monkeypatch, tmp_path, code, name):
        monkeypatch.setattr(csubgraph_native.ctypes, "CDLL", lambda path: FakeDll(code=code))
        native = csubgraph_native.NativeMultiOmics(tmp_path / "x.so")
        assert native.compare(np.array([CHAIN_3]), np.array([CHAIN_3])) == (name, None)

    def test_unknown_code(self, monkeypatch, tmp_path):
        monkeypatch.setattr(csubgraph_native.ctypes, "CDLL", lambda path: FakeDll(code=42))
        native = csubgraph_native.NativeMultiOmics(tmp_path / "x.so")
        result, error = native.compare(np.array([CHAIN_3]), np.array([CHAIN_3]))
        assert result is None and "unknown result" in error

    def test_library_error_text_is_returned(self, monkeypatch, tmp_path):
        dll = FakeDll(code=-1, message=b"Validation error: bad")
        monkeypatch.setattr(csubgraph_native.ctypes, "CDLL", lambda path: dll)
        native = csubgraph_native.NativeMultiOmics(tmp_path / "x.so")
        assert native.compare(np.array([CHAIN_3]), np.array([CHAIN_3])) == (
            None, "csubgraph error: Validation error: bad"
        )

    def test_unknown_mode(self, native):
        result, error = native.compare(np.array([CHAIN_3]), np.array([CHAIN_3]), "weird")
        assert result is None and "unknown mode" in error
        assert self.dll.calls == []

    def test_wrong_dimensions(self, native):
        result, error = native.compare(np.array(CHAIN_3), np.array([CHAIN_3]))
        assert result is None and "shape (layers, n, n)" in error
        assert self.dll.calls == []


class TestOmicsBackendSelection:
    def test_python_when_path_not_set(self, monkeypatch):
        loaded = use_omics(monkeypatch, FakeOmics())
        use_config(monkeypatch, FakeConfig(path=None))
        assert get_multiomics_backend_name() == "python"
        assert loaded == []

    def test_python_when_path_empty(self, monkeypatch):
        loaded = use_omics(monkeypatch, FakeOmics())
        use_config(monkeypatch, FakeConfig(path="  "))
        assert get_multiomics_backend_name() == "python"
        assert loaded == []

    def test_python_when_no_config(self, monkeypatch):
        use_config(monkeypatch, None)
        assert get_multiomics_backend_name() == "python"

    def test_python_when_library_not_found(self, monkeypatch, tmp_path, caplog):
        use_config(monkeypatch, FakeConfig(path=str(tmp_path)))
        with caplog.at_level("WARNING"):
            assert get_multiomics_backend_name() == "python"
        assert "falling back to Python" in caplog.text
        assert "nicht gefunden" in get_multiomics_native_error()

    def test_csubgraph_when_library_loaded(self, monkeypatch, fake_lib):
        loaded = use_omics(monkeypatch, FakeOmics())
        use_config(monkeypatch, FakeConfig(path=str(fake_lib)))
        assert get_multiomics_backend_name() == "csubgraph"
        assert loaded == [str(fake_lib)]
        assert get_multiomics_native_error() is None

    def test_resolved_only_once(self, monkeypatch, fake_lib):
        loaded = use_omics(monkeypatch, FakeOmics())
        use_config(monkeypatch, FakeConfig(path=str(fake_lib)))
        assert get_multiomics_backend_name() == "csubgraph"
        use_config(monkeypatch, FakeConfig(path=None))
        assert get_multiomics_backend_name() == "csubgraph"
        assert len(loaded) == 1

    def test_reset_resolves_again(self, monkeypatch, fake_lib):
        loaded = use_omics(monkeypatch, FakeOmics())
        use_config(monkeypatch, FakeConfig(path=str(fake_lib)))
        get_multiomics_backend_name()
        reset_backend()
        get_multiomics_backend_name()
        assert len(loaded) == 2

    def test_old_library_keeps_single_comparison_on_cpp(self, monkeypatch, tmp_path, caplog):
        """Ohne MultiOmics in der Bibliothek bleibt der Einzelvergleich bei C++."""
        lib = tmp_path / "libsubgraphlib.a"
        lib.write_bytes(b"!<arch>\n")
        monkeypatch.setattr(csubgraph_native, "load", lambda setting: object())
        use_config(monkeypatch, FakeConfig(path=str(lib)))
        with caplog.at_level("WARNING"):
            assert get_backend_name() == "csubgraph"
            assert get_multiomics_backend_name() == "python"
        assert "MultiOmics" in get_multiomics_native_error()
        assert "multi-omics" in caplog.text


class TestCsubgraphMultiOmicsComparison:
    @pytest.fixture(autouse=True)
    def configured(self, monkeypatch, fake_lib):
        self.native = FakeOmics()
        use_omics(monkeypatch, self.native)
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
        assert execute_multiomics_comparison([CHAIN_3], [CHAIN_4]) == (expected, None)

    def test_identical_keeps_a_with_more_edges_over_all_layers(self):
        self.native.result = "IDENTICAL"
        a = [CHAIN_4_EXTRA_EDGE, CHAIN_4]
        b = [CHAIN_4, CHAIN_4]
        assert execute_multiomics_comparison(a, b) == ("equal_keep_A", None)

    def test_identical_keeps_b_with_more_edges_over_all_layers(self):
        self.native.result = "IDENTICAL"
        assert execute_multiomics_comparison([CHAIN_4, CHAIN_4], [CHAIN_4_EXTRA_EDGE, CHAIN_4]) == (
            "equal_keep_B", None
        )

    def test_stacks_and_mode_passed_to_library(self):
        execute_multiomics_comparison([CHAIN_3, RING_3], [CHAIN_4, CHAIN_4], "independent")
        assert self.native.calls == [([CHAIN_3, RING_3], [CHAIN_4, CHAIN_4], "independent")]

    def test_python_implementation_not_used(self, monkeypatch):
        def _fail(*args, **kwargs):
            raise AssertionError("Python-Implementierung darf nicht genutzt werden")

        monkeypatch.setattr(multiomics_python, "compare_layered", _fail)
        assert execute_multiomics_comparison([CHAIN_3], [CHAIN_4]) == ("keep_B", None)

    def test_invalid_stack_rejected_before_library(self):
        result, error = execute_multiomics_comparison([[[0, 1]]], [CHAIN_4])
        assert result is None and "Invalid layer stack" in error
        assert self.native.calls == []

    def test_library_error_is_returned(self):
        self.native.error = "csubgraph error: Validation error: x"
        assert execute_multiomics_comparison([CHAIN_3], [CHAIN_4]) == (
            None, "csubgraph error: Validation error: x"
        )

    def test_unknown_result(self):
        self.native.result = "WAT"
        result, error = execute_multiomics_comparison([CHAIN_3], [CHAIN_4])
        assert result is None and "unknown result" in error

    def test_single_comparison_still_independent_of_omics(self, monkeypatch):
        """Der Einzelvergleich nutzt weiter seinen eigenen Pfad (Python-Fallback ohne csubgraph)."""
        assert get_backend_name() == "python"


class TestBuildOmicsWrapper:
    """Link-Befehl und Cache des Multi-Omics-Wrappers, ohne echten Compiler."""

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

    def test_command_links_omics_shim(self, build_env):
        lib, commands = build_env
        target = csubgraph_native.build_shared_library(lib, csubgraph_native.OMICS_SHIM)
        assert target.name.startswith("csubgraph_omics_shim_")
        command = commands[0]
        assert str(csubgraph_native.OMICS_SHIM_SOURCE) in command
        assert str(csubgraph_native.SHIM_SOURCE) not in command
        assert str(lib) in command
        assert "-shared" in command

    def test_bundled_headers_used_when_library_has_none_nearby(self, build_env):
        lib, commands = build_env
        csubgraph_native.build_shared_library(lib, csubgraph_native.OMICS_SHIM)
        command = commands[0]
        assert command[command.index("-I") + 1] == str(csubgraph_native.BUNDLED_HEADER_DIR)
        assert (csubgraph_native.BUNDLED_HEADER_DIR / csubgraph_native.OMICS_HEADER_NAME).is_file()

    def test_header_next_to_library_is_preferred(self, build_env):
        lib, commands = build_env
        for name in (csubgraph_native.HEADER_NAME, csubgraph_native.OMICS_HEADER_NAME):
            (lib.parent / name).write_text("// Kopie neben der Bibliothek")
        csubgraph_native.build_shared_library(lib, csubgraph_native.OMICS_SHIM)
        command = commands[0]
        assert command[command.index("-I") + 1] == str(lib.parent)

    def test_directory_needs_both_headers(self, build_env):
        lib, _ = build_env
        (lib.parent / csubgraph_native.HEADER_NAME).write_text("// nur ein Header")
        found = csubgraph_native._find_header_dir(lib, csubgraph_native.OMICS_SHIM.headers)
        assert found == csubgraph_native.BUNDLED_HEADER_DIR
        assert csubgraph_native._find_header_dir(lib) == lib.parent

    def test_wrappers_are_cached_separately(self, build_env):
        lib, commands = build_env
        base = csubgraph_native.build_shared_library(lib)
        omics = csubgraph_native.build_shared_library(lib, csubgraph_native.OMICS_SHIM)
        assert base != omics
        assert csubgraph_native.build_shared_library(lib, csubgraph_native.OMICS_SHIM) == omics
        assert len(commands) == 2

    def test_failed_build_raises_with_compiler_output(self, build_env, monkeypatch):
        lib, _ = build_env

        def _run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "undefined reference to MultiOmics")

        monkeypatch.setattr(csubgraph_native.subprocess, "run", _run)
        with pytest.raises(NativeLibraryError, match="undefined reference"):
            csubgraph_native.build_shared_library(lib, csubgraph_native.OMICS_SHIM)


def _has_real_multiomics_library():
    lib = find_static_library(os.environ.get("CSUBGRAPH_LIB_PATH"))
    return bool(lib) and csubgraph_native._has_multiomics(lib)


@pytest.mark.skipif(
    not _has_real_multiomics_library(),
    reason="CSUBGRAPH_LIB_PATH zeigt nicht auf eine libsubgraphlib.a mit MultiOmics",
)
class TestRealMultiOmicsLibrary:
    """Ruft die echte Bibliothek auf (benötigt Compiler und gesetzten CSUBGRAPH_LIB_PATH)."""

    @pytest.fixture
    def native(self):
        return csubgraph_native.load_multiomics(os.environ["CSUBGRAPH_LIB_PATH"])

    @pytest.mark.parametrize(
        "a, b, expected",
        [
            ([CHAIN_3], [CHAIN_4], "KEEP_B"),
            ([CHAIN_4], [CHAIN_3], "KEEP_A"),
            ([CHAIN_4], [CHAIN_4], "IDENTICAL"),
            ([[[0, 1], [1, 0]]], [CHAIN_4], "KEEP_BOTH"),
        ],
    )
    def test_results(self, native, a, b, expected):
        assert native.compare(np.array(a), np.array(b)) == (expected, None)

    def test_invalid_layer_count_reports_error(self, native):
        result, error = native.compare(np.array([CHAIN_3]), np.array([CHAIN_3, CHAIN_3]))
        assert result is None and "same number of layers" in error

    def test_non_binary_matrix_reports_error(self, native):
        result, error = native.compare(np.array([[[0, 2], [0, 0]]]), np.array([CHAIN_3]))
        assert result is None and "Validation error" in error

    def test_more_than_63_nodes_reports_error(self, native):
        big = np.zeros((1, 64, 64), dtype=int)
        result, error = native.compare(big, big)
        assert result is None and "Validation error" in error

    @pytest.mark.parametrize("mode", ["coherent", "independent"])
    @pytest.mark.parametrize("strategy", [0, 1])
    def test_matches_python_implementation(self, native, mode, strategy):
        rng = random.Random(7)
        names = {"KEEP_A", "KEEP_B", "KEEP_BOTH", "IDENTICAL", "EQUAL_KEEP_A", "EQUAL_KEEP_B"}
        seen = set()
        for _ in range(200):
            layers = rng.randint(1, 3)
            na = rng.randint(2, 6)
            nb = na if rng.random() < 0.5 else rng.randint(2, 6)

            def make(n):
                result = []
                for _ in range(layers):
                    columns = [rng.choice([1, 2, 3, 5]) % (1 << n) for _ in range(n)]
                    result.append([[(columns[j] >> i) & 1 for j in range(n)] for i in range(n)])
                return result

            a, b = make(na), make(nb)
            expected = multiomics_python.compare_layered(a, b, mode)
            assert native.compare(np.array(a), np.array(b), mode, strategy) == (expected, None)
            seen.add(expected)
        assert seen <= names and len(seen) >= 3

    def test_execute_uses_library(self, monkeypatch):
        use_config(monkeypatch, FakeConfig(path=os.environ["CSUBGRAPH_LIB_PATH"]))
        assert get_multiomics_backend_name() == "csubgraph"
        assert execute_multiomics_comparison([CHAIN_3], [CHAIN_4]) == ("keep_B", None)
