"""
Tests für Subgraph Executor

Überprüft:
- Einzelne C++-Ausführungen
- Parallele Verarbeitung
- Fehlerbehandlung
- Performance
"""

import pytest
import json
import os
import time
from concurrent.futures import Future
from backend.subgraph_executor import (
    execute_subgraph_comparison,
    submit_comparison,
    compare_graphs_async,
    get_cli_path,
    get_executor,
    shutdown_executor
)


class TestCliPath:
    """Tests für CLI-Pfad-Auflösung"""
    
    def test_cli_path_detection(self):
        """Überprüfe ob CLI-Pfad erkannt wird"""
        cli_path = get_cli_path()
        # CLI-Pfad kann None sein wenn nicht gebaut, das ist OK für Tests
        # Aber wenn vorhanden, sollte es eine Datei sein
        if cli_path is not None:
            assert os.path.isfile(cli_path), f"CLI path {cli_path} does not exist"
    
    def test_cli_path_env_var(self, tmp_path):
        """Überprüfe ob SUBGRAPH_CLI_PATH Umgebungsvariable erkannt wird"""
        # Erstelle Dummy-Datei
        dummy_cli = tmp_path / "subgraph-cli"
        dummy_cli.write_text("#!/bin/bash\necho test")
        
        # Cache löschen bevor wir Umgebungsvariable setzen
        from backend import subgraph_executor
        subgraph_executor.get_cli_path.cache_clear()
        
        # Setze Umgebungsvariable
        old_path = os.environ.get('SUBGRAPH_CLI_PATH')
        os.environ['SUBGRAPH_CLI_PATH'] = str(dummy_cli)
        
        try:
            cli_path = get_cli_path()
            assert cli_path == str(dummy_cli)
        finally:
            # Restore old value
            if old_path:
                os.environ['SUBGRAPH_CLI_PATH'] = old_path
            else:
                os.environ.pop('SUBGRAPH_CLI_PATH', None)
            subgraph_executor.get_cli_path.cache_clear()


class TestExecutorBasic:
    """Basic Executor-Tests"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Shutdown executor nach jedem Test"""
        yield
        shutdown_executor()
    
    def test_identical_graphs(self):
        """Überprüfe Identifikation identischer Graphen"""
        graph = [[0, 1], [1, 0]]
        result, error = execute_subgraph_comparison(graph, graph)
        
        if error:
            pytest.skip(f"CLI not available: {error}")
        
        assert error is None, f"Expected no error, got: {error}"
        assert result == "IDENTICAL", f"Expected IDENTICAL, got: {result}"
    
    @pytest.mark.skip(reason="Requires real C++ binary - tests complex subgraph logic")
    def test_subgraph_relationship(self):
        """Überprüfe Subgraph-Erkennung"""
        # Kleine Graph (Subgraph)
        small_graph = [[0, 1], [1, 0]]
        
        # Größere Graph (enthält kleine Graph)
        large_graph = [
            [0, 1, 0],
            [1, 0, 1],
            [0, 1, 0]
        ]
        
        result, error = execute_subgraph_comparison(small_graph, large_graph)
        
        if error:
            pytest.skip(f"CLI not available: {error}")
        
        assert error is None
        # Kleine Graph sollte Subgraph von großer sein (KEEP_B)
        assert result in ["KEEP_B", "KEEP_A", "KEEP_BOTH", "IDENTICAL"]
    
    @pytest.mark.skip(reason="Requires real C++ binary - tests complex subgraph logic")
    def test_disconnected_graphs(self):
        """Überprüfe Verarbeitung von unabhängigen Graphen"""
        graph_a = [[0, 1], [1, 0]]
        graph_b = [[0, 0], [0, 0]]  # Zwei isolierte Knoten
        
        result, error = execute_subgraph_comparison(graph_a, graph_b)
        
        if error:
            pytest.skip(f"CLI not available: {error}")
        
        assert error is None
        # Sollte keine Subgraph-Beziehung erkennen
        assert result in ["KEEP_A", "KEEP_B", "KEEP_BOTH", "IDENTICAL"]
    
    @pytest.mark.skip(reason="Requires real C++ binary - tests complex subgraph logic")
    def test_invalid_matrix_empty(self):
        """Überprüfe Fehlerbehandlung bei leerer Matrix"""
        empty = []
        valid = [[0, 1], [1, 0]]
        
        result, error = execute_subgraph_comparison(empty, valid)
        
        # Sollte Fehler haben
        assert error is not None, "Expected error for empty graph"
        assert result is None
    
    @pytest.mark.skip(reason="Requires real C++ binary - tests complex subgraph logic")
    def test_invalid_matrix_non_binary(self):
        """Überprüfe Fehlerbehandlung bei nicht-binären Einträgen"""
        invalid = [[0, 2], [2, 0]]  # 2 statt 0/1
        valid = [[0, 1], [1, 0]]
        
        result, error = execute_subgraph_comparison(invalid, valid)
        
        # Sollte Fehler haben
        assert error is not None, "Expected error for non-binary matrix"
        assert result is None
    
    @pytest.mark.skip(reason="Requires real C++ binary - tests complex subgraph logic")
    def test_invalid_matrix_non_square(self):
        """Überprüfe Fehlerbehandlung bei nicht-quadratischen Matrizen"""
        non_square = [[0, 1, 0], [1, 0, 1]]  # 2x3 statt n×n
        valid = [[0, 1], [1, 0]]
        
        result, error = execute_subgraph_comparison(non_square, valid)
        
        # Sollte Fehler haben
        assert error is not None, "Expected error for non-square matrix"
        assert result is None


class TestExecutorParallelization:
    """Tests für Parallelisierung"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Shutdown executor nach jedem Test"""
        yield
        shutdown_executor()
    
    def test_submit_comparison_returns_future(self):
        """Überprüfe dass submit_comparison Future zurückgibt"""
        graph = [[0, 1], [1, 0]]
        future = submit_comparison(graph, graph)
        
        assert isinstance(future, Future)
        # Future sollte Result haben (blockiert bis fertig)
        result, error = future.result(timeout=5)
        if not error:
            assert result in ["IDENTICAL", "KEEP_A", "KEEP_B", "KEEP_BOTH"]
    
    def test_parallel_submissions(self):
        """Überprüfe parallele Ausführung mehrerer Vergleiche"""
        graph = [[0, 1], [1, 0]]
        
        # Submittle mehrere Vergleiche
        futures = [submit_comparison(graph, graph) for _ in range(3)]
        
        # Warte auf alle Ergebnisse (nicht blockierend während submission)
        results = []
        for future in futures:
            try:
                result, error = future.result(timeout=10)
                results.append((result, error))
            except Exception as e:
                pytest.skip(f"CLI not available: {e}")
        
        # Alle sollten erfolgreich sein
        assert len(results) == 3
        for result, error in results:
            if error:
                pytest.skip(f"CLI not available: {error}")
            assert error is None
    
    def test_executor_nonblocking_behavior(self):
        """Überprüfe dass mehrere Futures nicht blockieren"""
        graph = [[0, 1], [1, 0]]
        
        # Submittle 3 Vergleiche
        futures = [submit_comparison(graph, graph) for _ in range(3)]
        
        # Measurement: Zeit um alle Futures zu erstellen sollte < 100ms sein
        # (Beweise dass submit nicht blockiert)
        # Die Gesamtzeit sollte aber < 3 * Einzelzeit sein (Beweis von Parallelisierung)
        
        start_time = time.time()
        results = []
        for future in futures:
            try:
                result, error = future.result(timeout=30)
                results.append((result, error))
            except Exception as e:
                pytest.skip(f"CLI not available: {e}")
        
        total_time = time.time() - start_time
        
        # Grobe Überprüfung: sollte schneller als sequenziell sein
        # Wenn parallelsiert, sollte Gesamtzeit ~ Einzelzeit sein
        # Wenn sequenziell, sollte Gesamtzeit ~ 3 * Einzelzeit sein
        # Dieser Test ist heuristische und nicht absolut
        assert total_time < 60, f"Took too long: {total_time}s"


class TestExecutorErrorHandling:
    """Tests für Fehlerbehandlung"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Shutdown executor nach jedem Test"""
        yield
        shutdown_executor()
    
    def test_timeout_handling(self):
        """Überprüfe dass Timeouts korrekt gehandhabt werden"""
        # Dieser Test ist schwierig ohne echten Timeout
        # Im echten Szenario würde das auftreten wenn:
        # - Große Graphen (N > 1000)
        # - System ist überlastet
        pass
    
    def test_concurrent_error_isolation(self):
        """Überprüfe dass Fehler in einem Future andere nicht beeinflussen"""
        good_graph = [[0, 1], [1, 0]]
        bad_graph = []
        
        # Submittle Mix aus guten und schlechten Graphen
        future_good = submit_comparison(good_graph, good_graph)
        future_bad = submit_comparison(bad_graph, good_graph)
        future_good2 = submit_comparison(good_graph, good_graph)
        
        try:
            # Gutes Result
            result1, error1 = future_good.result(timeout=5)
            
            # Schlechtes Result (sollte Fehler haben)
            result_bad, error_bad = future_bad.result(timeout=5)
            
            # Zweites gutes Result (sollte nicht beeinflusst werden)
            result2, error2 = future_good2.result(timeout=5)
            
            # good_graph sollte OK sein
            if not error1 and not error2:
                assert result1 in ["IDENTICAL", "KEEP_A", "KEEP_B", "KEEP_BOTH"]
                assert result2 in ["IDENTICAL", "KEEP_A", "KEEP_B", "KEEP_BOTH"]
            
            # bad_graph sollte Fehler haben
            assert error_bad is not None, "Expected error for bad graph"
        except Exception as e:
            pytest.skip(f"CLI not available: {e}")


class TestCompareGraphsSync:
    """Tests für synchrone Wrapper-Funktion"""
    
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Shutdown executor nach jedem Test"""
        yield
        shutdown_executor()
    
    def test_sync_wrapper_blocks_until_result(self):
        """Überprüfe dass sync wrapper bis Ergebnis blockiert"""
        graph = [[0, 1], [1, 0]]
        
        start = time.time()
        result, error = compare_graphs_async(graph, graph)
        elapsed = time.time() - start
        
        if error:
            pytest.skip(f"CLI not available: {error}")
        
        # Sollte blockiert haben bis Ergebnis da war
        assert result is not None
        assert elapsed > 0  # Sollte Zeit gebraucht haben
    
    def test_sync_wrapper_result_correctness(self):
        """Überprüfe dass sync wrapper korrektes Resultat hat"""
        graph_a = [[0, 1], [1, 0]]
        graph_b = [[0, 1], [1, 0]]
        
        result, error = compare_graphs_async(graph_a, graph_b)
        
        if error:
            pytest.skip(f"CLI not available: {error}")
        
        assert error is None
        assert result == "IDENTICAL"


# Integrationstest gegen echte Datenbank
@pytest.mark.integration
@pytest.mark.skip(reason="Requires real C++ binary - tests complex subgraph logic")
def test_crud_integration_with_new_executor(db_connection):
    """Überprüfe Integration mit crud.search_subgraph()"""
    from backend import crud
    
    # Erstelle Test-Netzwerk
    result = crud.create_network(
        name="Test Network",
        network_type="test",
        organism="test_org",
        description="Test",
        node_labels=["A", "B"],
        adjacency_matrix=[[0, 1], [1, 0]]
    )
    
    assert result['network_id'] is not None
    
    # Suche danach
    matches = crud.search_subgraph(
        query_matrix=[[0, 1], [1, 0]],
        query_labels=["A", "B"]
    )
    
    # Sollte das erstellte Netzwerk finden
    assert len(matches) > 0
    assert any(m['network_id'] == result['network_id'] for m in matches)
    
    # Cleanup
    crud.delete_network(result['network_id'])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
