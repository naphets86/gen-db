"""
Tests für die Auswertung der Subgraph-Ergebnisse in crud.search_subgraph.

Ohne Datenbank: Verbindung und Cursor werden durch Fakes ersetzt, der
Subgraph Algorithmus selbst läuft echt (Dependency ``subgraph``).
"""

from contextlib import contextmanager

import pytest

from backend import crud
from backend.subgraph_executor import shutdown_executor

CHAIN_2 = [[0, 1], [0, 0]]
CHAIN_4 = [
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
    [0, 0, 0, 0],
]
EXTRA_EDGE_4 = [
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
    [0, 0, 0, 0],
]


def _row(network_id, matrix, name=None):
    return {
        'network_id': network_id,
        'name': name or f'net_{network_id}',
        'network_type': 'test',
        'organism': 'Test',
        'node_count': len(matrix),
        'edge_count': sum(sum(r) for r in matrix),
        'node_labels': [f'n{i}' for i in range(len(matrix))],
        'adjacency_matrix': matrix,
    }


class _FakeCursor:
    executed = []

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        _FakeCursor.executed.append((sql, params))

    def fetchall(self):
        return self._rows


@pytest.fixture(autouse=True)
def cleanup_executor():
    _FakeCursor.executed = []
    yield
    shutdown_executor()


@pytest.fixture
def fake_db(monkeypatch):
    def install(rows):
        @contextmanager
        def fake_connection():
            yield object()

        monkeypatch.setattr(crud, 'get_db_connection', fake_connection)
        monkeypatch.setattr(crud, 'get_db_cursor', lambda _conn: _FakeCursor(rows))

    return install


def test_larger_candidate_containing_query_is_subgraph_match(fake_db):
    fake_db([_row(1, CHAIN_4)])

    matches = crud.search_subgraph(CHAIN_2, ['a', 'b'])

    assert len(matches) == 1
    assert matches[0].network_id == 1
    assert matches[0].match_type == 'subgraph'
    assert matches[0].subgraph_result == 'keep_B'


def test_identical_candidate_is_exact_match(fake_db):
    fake_db([_row(1, CHAIN_4)])

    matches = crud.search_subgraph(CHAIN_4, ['a', 'b', 'c', 'd'])

    assert len(matches) == 1
    assert matches[0].match_type == 'exact'
    assert matches[0].subgraph_result.startswith('equal_')


def test_exact_match_type_follows_algorithm_decision(fake_db):
    """Ob 'exact' vorliegt, entscheidet der Subgraph Algorithmus (equal_keep_*)"""
    fake_db([_row(1, EXTRA_EDGE_4)])

    matches = crud.search_subgraph(CHAIN_4, ['a', 'b', 'c', 'd'])

    assert len(matches) == 1
    assert matches[0].subgraph_result == 'equal_keep_B'
    assert matches[0].match_type == 'exact'


def test_no_relationship_is_not_a_match(fake_db):
    fake_db([_row(1, [[0, 0], [0, 0]])])

    assert crud.search_subgraph(CHAIN_2, ['a', 'b']) == []


def test_failed_comparison_is_skipped_and_others_still_match(fake_db, caplog):
    broken = _row(1, CHAIN_4)
    broken['adjacency_matrix'] = []
    fake_db([broken, _row(2, CHAIN_4)])

    with caplog.at_level('WARNING'):
        matches = crud.search_subgraph(CHAIN_2, ['a', 'b'])

    assert [m.network_id for m in matches] == [2]
    assert '1 of 2 comparisons failed' in caplog.text


def test_no_candidates_returns_empty_list(fake_db):
    fake_db([])

    assert crud.search_subgraph(CHAIN_2, ['a', 'b']) == []


def test_sql_preselection_uses_query_node_and_edge_count(fake_db):
    """Die SQL-Vorauswahl schließt Kandidaten mit zu wenig Knoten/Kanten im Vorfeld aus"""
    fake_db([])

    crud.search_subgraph(CHAIN_4, ['a', 'b', 'c', 'd'])

    sql, params = _FakeCursor.executed[0]
    assert 'node_count >= %s' in sql and 'edge_count >= %s' in sql
    assert params == (4, 3)
