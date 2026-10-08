"""
Tests für die Multi-Omics-Funktionen in crud.py (ohne Datenbank)

Verbindung und Cursor werden durch Fakes ersetzt, die ausgeführte SQL-Befehle und
Parameter festhalten. Die Multi-Omics-Vergleiche selbst laufen echt über den
Subgraph Executor (Python-Implementierung bzw. csubgraph, je nach CSUBGRAPH_LIB_PATH).
"""

from contextlib import contextmanager

import pytest

from backend import crud, subgraph_executor
from backend.models import MultiOmicsCreationResult, MultiOmicsNetwork, MultiOmicsSearchMatch
from backend.subgraph_executor import shutdown_executor


def matrix(columns):
    n = len(columns)
    return [[(columns[j] >> i) & 1 for j in range(n)] for i in range(n)]


TRANSCRIPTOME = matrix([1, 2, 3])
PROTEOME = matrix([4, 5, 6])
LABELS = ['TP53', 'MDM2', 'ATM']


class _FakeCursor:
    def __init__(self, fetchall_rows=None, fetchone_rows=None):
        self.executed = []
        self._all = list(fetchall_rows or [])
        self._one = list(fetchone_rows or [])

    def execute(self, sql, params=None):
        self.executed.append((' '.join(sql.split()), params))

    def fetchall(self):
        return self._all.pop(0) if self._all else []

    def fetchone(self):
        return self._one.pop(0) if self._one else None


@pytest.fixture(autouse=True)
def cleanup_executor(monkeypatch):
    class _Config:
        csubgraph_lib_path = None
        subgraph_max_workers = 2

    monkeypatch.setattr(subgraph_executor, '_get_config_safe', lambda: _Config())
    subgraph_executor.reset_backend()
    yield
    shutdown_executor()
    subgraph_executor.reset_backend()


@pytest.fixture
def fake_db(monkeypatch):
    def install(fetchall_rows=None, fetchone_rows=None):
        cursor = _FakeCursor(fetchall_rows, fetchone_rows)

        @contextmanager
        def fake_connection():
            yield object()

        monkeypatch.setattr(crud, 'get_db_connection', fake_connection)
        monkeypatch.setattr(crud, 'get_db_cursor', lambda _conn: cursor)
        return cursor

    return install


def _candidate_rows(network_id, layers, name=None, node_labels=None):
    """Zeilen wie sie die Suchabfrage liefert: eine je (Netzwerk, Schicht)."""
    n = len(next(iter(layers.values())))
    return [
        {
            'network_id': network_id,
            'name': name or f'omics_{network_id}',
            'network_type': 'multi_omics',
            'organism': 'Test',
            'node_count': n,
            'edge_count': sum(sum(sum(r) for r in m) for m in layers.values()),
            'node_labels': node_labels or [f'n{i}' for i in range(n)],
            'layer_name': layer_name,
            'adjacency_matrix': adjacency,
        }
        for layer_name, adjacency in layers.items()
    ]


class TestValidateInput:
    def test_valid_input(self):
        crud.validate_multiomics_input(LABELS, ['t', 'p'], [TRANSCRIPTOME, PROTEOME])

    def test_names_and_matrices_must_match(self):
        with pytest.raises(ValueError, match='same length'):
            crud.validate_multiomics_input(LABELS, ['t'], [TRANSCRIPTOME, PROTEOME])

    def test_layer_names_must_be_unique(self):
        with pytest.raises(ValueError, match='unique'):
            crud.validate_multiomics_input(LABELS, ['t', 't'], [TRANSCRIPTOME, PROTEOME])

    def test_at_least_one_layer(self):
        with pytest.raises(ValueError, match='at least one layer'):
            crud.validate_multiomics_input(LABELS, [], [])

    def test_matrices_must_be_square_binary_and_equal_in_size(self):
        with pytest.raises(ValueError, match='square'):
            crud.validate_multiomics_input(LABELS, ['t'], [[[0, 1, 0], [0, 0, 1]]])
        with pytest.raises(ValueError, match='only 0 and 1'):
            crud.validate_multiomics_input(LABELS, ['t'], [[[0, 1, 0], [0, 0, 1], [0, 0, 2]]])
        with pytest.raises(ValueError, match='layer 1'):
            crud.validate_multiomics_input(LABELS, ['t', 'p'], [TRANSCRIPTOME, matrix([1, 2])])

    def test_label_count_must_equal_matrix_size(self):
        with pytest.raises(ValueError, match='node labels'):
            crud.validate_multiomics_input(['a', 'b'], ['t'], [TRANSCRIPTOME])

    def test_more_than_63_nodes_rejected(self):
        big = [[0] * 64 for _ in range(64)]
        with pytest.raises(ValueError, match='at most 63'):
            crud.validate_multiomics_input(['x'] * 64, ['t'], [big])


class TestCreateMultiOmicsNetwork:
    def _create(self, fake_db, **overrides):
        cursor = fake_db(fetchone_rows=[{'network_id': 7}])
        arguments = dict(
            name='TP53 Multi-Omics', network_type='multi_omics', organism='Human',
            description='zwei Schichten', node_labels=LABELS,
            layer_names=['transcriptome', 'proteome'], layer_matrices=[TRANSCRIPTOME, PROTEOME],
        )
        arguments.update(overrides)
        return cursor, crud.create_multiomics_network(**arguments)

    def test_returns_creation_result(self, fake_db):
        _, result = self._create(fake_db)
        assert isinstance(result, MultiOmicsCreationResult)
        assert result.network_id == 7
        assert result.node_count == 3
        assert result.layer_names == ['transcriptome', 'proteome']
        assert result.edge_count == sum(sum(r) for r in TRANSCRIPTOME) + sum(sum(r) for r in PROTEOME)
        assert len(result.signature_hash) == 64

    def test_writes_network_metadata_and_one_row_per_layer(self, fake_db):
        cursor, result = self._create(fake_db)
        statements = [sql for sql, _ in cursor.executed]
        assert 'INSERT INTO biological_networks' in statements[0]
        assert 'INSERT INTO omics_networks' in statements[1]
        assert all('INSERT INTO omics_layers' in sql for sql in statements[2:])
        assert len(statements) == 4

    def test_parameters_of_inserts(self, fake_db):
        cursor, result = self._create(fake_db)
        meta = cursor.executed[0][1]
        assert meta == ('TP53 Multi-Omics', 'multi_omics', 'Human', 'zwei Schichten', 3, result.edge_count)
        assert cursor.executed[1][1] == (7, LABELS, 2, result.signature_hash)
        first_layer = cursor.executed[2][1]
        assert first_layer[:4] == (7, 0, 'transcriptome', TRANSCRIPTOME)
        assert first_layer[4] == [1, 2, 3]  # Zeilenkomponenten = Spaltenbitmuster
        assert first_layer[5] == sum(sum(r) for r in TRANSCRIPTOME)
        assert cursor.executed[3][1][:3] == (7, 1, 'proteome')

    def test_hash_depends_on_all_layers(self, fake_db):
        _, first = self._create(fake_db)
        _, second = self._create(fake_db, layer_matrices=[TRANSCRIPTOME, matrix([4, 5, 7])])
        assert first.signature_hash != second.signature_hash

    def test_invalid_input_does_not_touch_database(self, fake_db):
        cursor = fake_db()
        with pytest.raises(ValueError):
            crud.create_multiomics_network(
                'n', 'multi_omics', 'Human', '', LABELS, ['t', 't'], [TRANSCRIPTOME, PROTEOME]
            )
        assert cursor.executed == []


class TestGetMultiOmicsNetwork:
    def test_found(self, fake_db):
        header = {
            'network_id': 7, 'name': 'TP53 Multi-Omics', 'network_type': 'multi_omics',
            'organism': 'Human', 'description': 'd', 'node_count': 3, 'edge_count': 6,
            'node_labels': LABELS, 'signature_hash': 'abc', 'created_at': '2026-10-07 10:00:00',
        }
        layers = [
            {'layer_name': 'transcriptome', 'adjacency_matrix': TRANSCRIPTOME, 'edge_count': 3},
            {'layer_name': 'proteome', 'adjacency_matrix': PROTEOME, 'edge_count': 3},
        ]
        cursor = fake_db(fetchall_rows=[layers], fetchone_rows=[header])

        network = crud.get_multiomics_network_by_id(7)

        assert isinstance(network, MultiOmicsNetwork)
        assert network.name == 'TP53 Multi-Omics'
        assert network.node_labels == LABELS
        assert [layer.layer_name for layer in network.layers] == ['transcriptome', 'proteome']
        assert network.layers[1].adjacency_matrix == PROTEOME
        assert network.signature_hash == 'abc'
        assert network.created_at == '2026-10-07 10:00:00'
        assert 'ORDER BY layer_index' in cursor.executed[1][0]
        assert cursor.executed[0][1] == (7,)

    def test_optional_fields_may_be_missing(self, fake_db):
        header = {
            'network_id': 1, 'name': 'x', 'network_type': 'multi_omics', 'organism': 'o',
            'description': '', 'node_count': 3, 'edge_count': 0, 'node_labels': LABELS,
        }
        fake_db(fetchone_rows=[header])
        network = crud.get_multiomics_network_by_id(1)
        assert network.signature_hash is None and network.created_at is None
        assert network.layers == []

    def test_not_found(self, fake_db, caplog):
        cursor = fake_db()
        with caplog.at_level('WARNING'):
            assert crud.get_multiomics_network_by_id(99) is None
        assert 'not found' in caplog.text
        assert len(cursor.executed) == 1


class TestSearchMultiOmics:
    QUERY_LAYERS = ['transcriptome', 'proteome']
    QUERY_MATRICES = [matrix([1, 2, 3]), matrix([4, 5, 6])]
    QUERY_LABELS = ['a', 'b', 'c']
    # Größerer Kandidat, der die Query in beiden Schichten an derselben Position enthält
    CONTAINING = {'transcriptome': matrix([1, 2, 3, 0]), 'proteome': matrix([4, 5, 6, 0])}

    def _search(self, fake_db, rows, **overrides):
        cursor = fake_db(fetchall_rows=[rows])
        arguments = dict(
            layer_names=self.QUERY_LAYERS,
            layer_matrices=self.QUERY_MATRICES,
            query_labels=self.QUERY_LABELS,
        )
        arguments.update(overrides)
        return cursor, crud.search_multiomics(**arguments)

    def test_candidate_containing_query_in_all_layers_is_subgraph_match(self, fake_db):
        _, matches = self._search(fake_db, _candidate_rows(1, self.CONTAINING))
        assert len(matches) == 1
        match = matches[0]
        assert isinstance(match, MultiOmicsSearchMatch)
        assert (match.network_id, match.match_type, match.subgraph_result) == (1, 'subgraph', 'keep_B')
        assert match.layer_names == self.QUERY_LAYERS
        assert match.mode == 'coherent'
        assert match.node_count == 4

    def test_equal_candidate_is_exact_match(self, fake_db):
        stack = dict(zip(self.QUERY_LAYERS, self.QUERY_MATRICES))
        _, matches = self._search(fake_db, _candidate_rows(1, stack))
        assert len(matches) == 1
        assert matches[0].match_type == 'exact'
        assert matches[0].subgraph_result.startswith('equal_')

    def test_unrelated_candidate_is_not_a_match(self, fake_db):
        rows = _candidate_rows(1, {'transcriptome': matrix([2, 1, 0]), 'proteome': matrix([6, 5, 4])})
        _, matches = self._search(fake_db, rows)
        assert matches == []

    def test_no_candidates(self, fake_db):
        _, matches = self._search(fake_db, [])
        assert matches == []

    def test_layers_are_compared_in_query_order(self, fake_db):
        """Die Zeilen liefern die Schichten in beliebiger Reihenfolge; verglichen wird nach Name."""
        reversed_stack = dict(reversed(list(self.CONTAINING.items())))
        _, matches = self._search(fake_db, _candidate_rows(1, reversed_stack))
        assert [m.network_id for m in matches] == [1]

    def test_mode_is_used(self, fake_db):
        # Schicht 1 passt an Position 0, Schicht 2 an Position 1 -> nur unabhängig ein Treffer
        rows = _candidate_rows(1, {'transcriptome': matrix([1, 2, 0]), 'proteome': matrix([0, 5, 6])})
        _, coherent = self._search(fake_db, rows, mode='coherent')
        _, independent = self._search(fake_db, rows, mode='independent')
        assert coherent == []
        assert [m.mode for m in independent] == ['independent']

    def test_candidates_grouped_by_network_in_database_order(self, fake_db):
        second = {'transcriptome': matrix([1, 2, 3, 0, 0]), 'proteome': matrix([4, 5, 6, 0, 0])}
        rows = (
            _candidate_rows(5, self.CONTAINING, name='first')
            + _candidate_rows(2, second, name='second')
        )
        _, matches = self._search(fake_db, rows)
        assert [(m.network_id, m.name) for m in matches] == [(5, 'first'), (2, 'second')]
        assert matches[1].node_count == 5

    def test_sql_filters_on_node_count_and_layer_names_but_not_on_edges(self, fake_db):
        cursor, _ = self._search(fake_db, [])
        sql, params = cursor.executed[0]
        assert 'bn.node_count >= %s' in sql
        assert 'ANY(%s)' in sql
        assert 'edge_count >=' not in sql
        assert params == (self.QUERY_LAYERS, 3, self.QUERY_LAYERS, 2)

    def test_failed_comparison_is_skipped_and_others_still_match(self, fake_db, caplog):
        good = _candidate_rows(2, self.CONTAINING)
        broken = _candidate_rows(1, {'transcriptome': matrix([1, 2, 3, 0]), 'proteome': []})
        with caplog.at_level('WARNING'):
            _, matches = self._search(fake_db, broken + good)
        assert [m.network_id for m in matches] == [2]
        assert 'Comparison error for network 1' in caplog.text
        assert '1 of 2 comparisons failed' in caplog.text

    def test_unknown_mode_rejected(self, fake_db):
        cursor = fake_db()
        with pytest.raises(ValueError, match='unknown mode'):
            crud.search_multiomics(['t'], [TRANSCRIPTOME], LABELS, mode='weird')
        assert cursor.executed == []

    def test_invalid_query_rejected_before_database(self, fake_db):
        cursor = fake_db()
        with pytest.raises(ValueError, match='node labels'):
            crud.search_multiomics(['t'], [TRANSCRIPTOME], ['a'])
        assert cursor.executed == []

    def test_comparison_results_are_passed_to_executor_with_mode(self, fake_db, monkeypatch):
        calls = []

        def _fake_compare(query, candidates, mode):
            calls.append((query, candidates, mode))
            return [('keep_B', None)] * len(candidates)

        monkeypatch.setattr(crud, 'compare_many_multiomics', _fake_compare)
        _, matches = self._search(fake_db, _candidate_rows(1, self.CONTAINING), mode='independent')
        assert len(matches) == 1
        assert calls[0][0] == self.QUERY_MATRICES
        assert calls[0][1] == [[self.CONTAINING['transcriptome'], self.CONTAINING['proteome']]]
        assert calls[0][2] == 'independent'
