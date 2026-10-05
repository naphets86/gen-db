"""
Tests für die Algorithmus-Auswahl im Subgraph Executor

Überprüft:
- Auffinden der csubgraph-CLI über CSUBGRAPH_PATH (Datei oder Ordner)
- csubgraph wird bevorzugt, Ergebnisse werden auf das Python-Format abgebildet
- Fallback auf die Python-Implementierung (nicht konfiguriert, nicht gefunden,
  nicht startbar)
- Fehlerbehandlung der CLI (Validierungsfehler, Timeout, ungültige Ausgabe)
"""

import json
import subprocess

import pytest

from backend import subgraph_executor
from backend.subgraph_executor import (
    execute_subgraph_comparison,
    find_csubgraph_cli,
    get_backend_name,
    reset_backend,
)

CHAIN_2 = [[0, 1], [0, 0]]
CHAIN_4 = [[0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]
CHAIN_4_EXTRA_EDGE = [[0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 0, 1], [0, 0, 0, 0]]


class FakeConfig:
    def __init__(self, path=None, timeout=5.0):
        self.csubgraph_path = path
        self.csubgraph_timeout = timeout
        self.subgraph_max_workers = 2


@pytest.fixture(autouse=True)
def fresh_backend():
    """Jeder Test löst den Algorithmus neu auf."""
    reset_backend()
    yield
    reset_backend()


@pytest.fixture
def fake_cli(tmp_path):
    """Datei, die wie das subgraph-cli-Executable aussieht."""
    cli = tmp_path / "subgraph-cli"
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    return cli


def use_config(monkeypatch, config):
    monkeypatch.setattr(subgraph_executor, "_get_config_safe", lambda: config)


def fake_run(monkeypatch, stdout="", stderr="", returncode=0, calls=None):
    def _run(args, **kwargs):
        if calls is not None:
            calls.append((args, json.loads(kwargs["input"])))
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    monkeypatch.setattr(subgraph_executor.subprocess, "run", _run)


def cli_answer(result):
    return json.dumps({"result": result, "result_code": 0, "error": None})


class TestFindCli:
    def test_empty_setting_returns_none(self):
        assert find_csubgraph_cli(None) is None
        assert find_csubgraph_cli("") is None
        assert find_csubgraph_cli("   ") is None

    def test_missing_path_returns_none(self, tmp_path):
        assert find_csubgraph_cli(str(tmp_path / "gibt-es-nicht")) is None

    def test_direct_file(self, fake_cli):
        assert find_csubgraph_cli(str(fake_cli)) == str(fake_cli.resolve())

    def test_build_folder(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        cli = build / "subgraph-cli"
        cli.write_text("")
        cli.chmod(0o755)
        assert find_csubgraph_cli(str(tmp_path)) == str(cli.resolve())

    def test_release_subfolder(self, tmp_path):
        release = tmp_path / "build" / "Release"
        release.mkdir(parents=True)
        cli = release / "subgraph-cli"
        cli.write_text("")
        cli.chmod(0o755)
        assert find_csubgraph_cli(str(tmp_path)) == str(cli.resolve())

    def test_folder_without_executable(self, tmp_path):
        assert find_csubgraph_cli(str(tmp_path)) is None


class TestBackendSelection:
    def test_python_when_path_not_set(self, monkeypatch):
        use_config(monkeypatch, FakeConfig(path=None))
        assert get_backend_name() == "python"

    def test_python_when_no_config(self, monkeypatch):
        use_config(monkeypatch, None)
        assert get_backend_name() == "python"

    def test_python_when_path_invalid(self, monkeypatch, tmp_path, caplog):
        use_config(monkeypatch, FakeConfig(path=str(tmp_path)))
        with caplog.at_level("WARNING"):
            assert get_backend_name() == "python"
        assert "falling back to Python" in caplog.text

    def test_csubgraph_when_path_valid(self, monkeypatch, fake_cli):
        use_config(monkeypatch, FakeConfig(path=str(fake_cli)))
        assert get_backend_name() == "csubgraph"

    def test_resolved_only_once(self, monkeypatch, fake_cli):
        use_config(monkeypatch, FakeConfig(path=str(fake_cli)))
        assert get_backend_name() == "csubgraph"
        use_config(monkeypatch, FakeConfig(path=None))
        assert get_backend_name() == "csubgraph"


class TestCsubgraphComparison:
    @pytest.fixture(autouse=True)
    def configured(self, monkeypatch, fake_cli):
        use_config(monkeypatch, FakeConfig(path=str(fake_cli)))
        self.cli = fake_cli

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
    def test_result_mapping(self, monkeypatch, cpp_result, expected):
        fake_run(monkeypatch, stdout=cli_answer(cpp_result))
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == (expected, None)

    def test_identical_keeps_a_with_more_edges(self, monkeypatch):
        fake_run(monkeypatch, stdout=cli_answer("IDENTICAL"))
        assert execute_subgraph_comparison(CHAIN_4_EXTRA_EDGE, CHAIN_4) == ("equal_keep_A", None)

    def test_identical_keeps_b_with_more_edges(self, monkeypatch):
        fake_run(monkeypatch, stdout=cli_answer("IDENTICAL"))
        assert execute_subgraph_comparison(CHAIN_4, CHAIN_4_EXTRA_EDGE) == ("equal_keep_B", None)

    def test_sends_matrices_as_json_to_cli(self, monkeypatch):
        calls = []
        fake_run(monkeypatch, stdout=cli_answer("KEEP_B"), calls=calls)
        execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        args, payload = calls[0]
        assert args == [str(self.cli.resolve())]
        assert payload == {"graph_a": CHAIN_2, "graph_b": CHAIN_4}

    def test_python_algorithm_not_used(self, monkeypatch):
        fake_run(monkeypatch, stdout=cli_answer("KEEP_B"))
        execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert subgraph_executor._algorithm is None

    def test_invalid_matrix_rejected_before_cli(self, monkeypatch):
        calls = []
        fake_run(monkeypatch, stdout=cli_answer("KEEP_B"), calls=calls)
        result, error = execute_subgraph_comparison([[0, 1]], CHAIN_4)
        assert result is None and "Invalid adjacency matrix" in error
        assert calls == []

    def test_cli_error_on_stderr(self, monkeypatch):
        err = json.dumps({"result": None, "result_code": -1, "error": "Validation error: x"})
        fake_run(monkeypatch, stderr=err, returncode=1)
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == (
            None, "csubgraph error: Validation error: x"
        )

    def test_cli_invalid_output(self, monkeypatch):
        fake_run(monkeypatch, stdout="kein json", returncode=0)
        result, error = execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert result is None and "invalid output" in error

    def test_cli_unknown_result(self, monkeypatch):
        fake_run(monkeypatch, stdout=cli_answer("WAT"))
        result, error = execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert result is None and "unknown result" in error

    def test_cli_timeout(self, monkeypatch):
        def _run(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        monkeypatch.setattr(subgraph_executor.subprocess, "run", _run)
        result, error = execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert result is None and "timeout" in error

    def test_unstartable_cli_falls_back_to_python(self, monkeypatch, caplog):
        def _run(args, **kwargs):
            raise OSError("exec format error")

        monkeypatch.setattr(subgraph_executor.subprocess, "run", _run)
        with caplog.at_level("WARNING"):
            result = execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert result == ("keep_B", None)
        assert "falling back to Python" in caplog.text
        assert get_backend_name() == "python"


class TestPythonFallback:
    def test_python_result_without_csubgraph(self, monkeypatch):
        use_config(monkeypatch, FakeConfig(path=None))
        assert execute_subgraph_comparison(CHAIN_2, CHAIN_4) == ("keep_B", None)
        assert subgraph_executor._algorithm is not None
