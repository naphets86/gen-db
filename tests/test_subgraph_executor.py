"""
Tests für Subgraph Executor

Überprüft:
- Einzelne Vergleiche über die API des Subgraph Algorithmus
- Parallele Verarbeitung (Futures, Batch)
- Fehlerbehandlung
"""

import asyncio
from concurrent.futures import Future

import pytest

from backend import subgraph_executor
from backend.subgraph_executor import (
    execute_subgraph_comparison,
    submit_comparison,
    compare_graphs_async,
    compare_graphs_async_await,
    compare_many,
    get_executor,
    shutdown_executor,
)

CHAIN_4 = [
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
    [0, 0, 0, 0],
]
CHAIN_2 = [[0, 1], [0, 0]]
CHAIN_4_EXTRA_EDGE = [
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
    [0, 0, 0, 0],
]

KEEP_B = ("keep_B", None)


@pytest.fixture(autouse=True)
def cleanup():
    """Executor nach jedem Test herunterfahren"""
    yield
    shutdown_executor()


class TestExecuteComparison:
    """Direkte Aufrufe (ohne Prozess-Pool)"""

    def test_identical_graphs(self):
        result, error = execute_subgraph_comparison(CHAIN_4, CHAIN_4)
        assert error is None
        assert result in ("equal_keep_A", "equal_keep_B")

    def test_query_contained_in_larger_candidate(self):
        """Kleinere Query A ist in größerem B enthalten -> keep_B"""
        result, error = execute_subgraph_comparison(CHAIN_2, CHAIN_4)
        assert error is None
        assert result == "keep_B"

    def test_candidate_contained_in_larger_query(self):
        """Kleineres B ist in größerem A enthalten -> keep_A"""
        result, error = execute_subgraph_comparison(CHAIN_4, CHAIN_2)
        assert error is None
        assert result == "keep_A"

    def test_same_size_with_extra_edge_is_mutually_contained(self):
        """Gleich große Graphen mit zusätzlicher Kante: Algorithmus liefert equal_keep_B"""
        result, error = execute_subgraph_comparison(CHAIN_4, CHAIN_4_EXTRA_EDGE)
        assert error is None
        assert result == "equal_keep_B"

    def test_no_relationship(self):
        a = [[0, 1], [0, 0]]
        b = [[0, 0], [0, 0]]
        result, error = execute_subgraph_comparison(a, b)
        assert error is None
        assert result in ("keep_A", "keep_B", "keep_both", "equal_keep_A", "equal_keep_B")

    def test_empty_matrix_returns_error(self):
        result, error = execute_subgraph_comparison([], CHAIN_4)
        assert result is None
        assert error is not None

    def test_non_square_matrix_returns_error(self):
        result, error = execute_subgraph_comparison([[0, 1, 0], [1, 0, 0]], CHAIN_4)
        assert result is None
        assert "square" in error

    def test_non_numeric_matrix_returns_error(self):
        result, error = execute_subgraph_comparison([["x"]], CHAIN_4)
        assert result is None
        assert error.startswith("Unexpected error")

    def test_algorithm_instance_is_reused(self, monkeypatch):
        monkeypatch.setattr(subgraph_executor, "_algorithm", None)
        execute_subgraph_comparison(CHAIN_4, CHAIN_4)
        first = subgraph_executor._algorithm
        execute_subgraph_comparison(CHAIN_4, CHAIN_4)
        assert first is not None
        assert subgraph_executor._algorithm is first


class TestExecutorPool:
    """Prozess-Pool, Futures und Batch"""

    def test_get_executor_is_singleton(self):
        assert get_executor(2) is get_executor(2)

    def test_get_executor_uses_config_workers(self, monkeypatch):
        class FakeConfig:
            subgraph_max_workers = 3

        monkeypatch.setattr(subgraph_executor, "_get_config_safe", lambda: FakeConfig())
        assert get_executor()._max_workers == 3

    def test_get_executor_falls_back_to_default_workers(self, monkeypatch):
        monkeypatch.setattr(subgraph_executor, "_get_config_safe", lambda: None)
        assert get_executor()._max_workers == subgraph_executor.DEFAULT_MAX_WORKERS

    def test_get_config_safe_returns_none_on_error(self, monkeypatch):
        def broken():
            raise RuntimeError("no config")

        monkeypatch.setattr("backend.config.get_config", broken)
        assert subgraph_executor._get_config_safe() is None

    def test_submit_comparison_returns_future(self):
        future = submit_comparison(CHAIN_2, CHAIN_4)
        assert isinstance(future, Future)
        assert future.result(timeout=30) == KEEP_B

    def test_compare_graphs_async_blocks_until_result(self):
        assert compare_graphs_async(CHAIN_2, CHAIN_4) == KEEP_B

    def test_multiple_futures_in_parallel(self):
        futures = [submit_comparison(CHAIN_2, CHAIN_4) for _ in range(5)]
        assert all(f.result(timeout=30) == ("keep_B", None) for f in futures)

    def test_bad_input_does_not_affect_other_futures(self):
        good1 = submit_comparison(CHAIN_2, CHAIN_4)
        bad = submit_comparison([], CHAIN_4)
        good2 = submit_comparison(CHAIN_2, CHAIN_4)

        assert good1.result(timeout=30) == ("keep_B", None)
        assert good2.result(timeout=30) == ("keep_B", None)
        result, error = bad.result(timeout=30)
        assert result is None and error is not None

    def test_compare_many_keeps_order(self):
        candidates = [CHAIN_4, CHAIN_2, [], CHAIN_4]
        outcomes = compare_many(CHAIN_2, candidates, chunksize=2)

        assert len(outcomes) == 4
        assert outcomes[0] == KEEP_B
        assert outcomes[1][0] in ("equal_keep_A", "equal_keep_B")
        assert outcomes[2][0] is None and outcomes[2][1] is not None
        assert outcomes[3] == KEEP_B

    def test_compare_many_empty(self):
        assert compare_many(CHAIN_4, []) == []

    def test_compare_many_invalid_chunksize_is_clamped(self):
        assert compare_many(CHAIN_2, [CHAIN_4], chunksize=0) == [KEEP_B]

    def test_async_await_wrapper(self):
        result = asyncio.run(compare_graphs_async_await(CHAIN_2, CHAIN_4))
        assert result == KEEP_B

    def test_shutdown_is_idempotent(self):
        get_executor(2)
        shutdown_executor()
        shutdown_executor()
        assert subgraph_executor._executor is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
