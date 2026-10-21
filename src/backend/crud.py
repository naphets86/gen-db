"""
CRUD Operations Layer

Verwaltet alle Datenbankoperationen und gibt Domain Models (nicht Dicts) zurück.
Diese Funktionen sind framework-unabhängig und können von überall aufgerufen werden
(REST API, GraphQL, CLI, etc).

Dependencies:
- Models (Domain Models)
- Database (Verbindung)
- Subgraph Executor (Subgraph Algorithmus; C++ über CSUBGRAPH_LIB_PATH, sonst Python-Dependency)
- Multi-Omics (Mehrschicht-Netzwerke, siehe multiomics_python und MultiOmics in csubgraph)
- Universelle Kodierung (beliebige Strukturen eines Schemas als Stapel, Suche über den
  invertierten Paarindex, siehe universal_core, universal_schema und universal_index)
"""

import json
import logging
import hashlib
import numpy as np
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union
from .database import get_db_connection, get_db_cursor
from .subgraph_executor import compare_many, compare_many_multiomics
from .models import (
    Network, NetworkSummary, SearchMatch, NetworkCreationResult,
    OmicsLayer, MultiOmicsNetwork, MultiOmicsCreationResult, MultiOmicsSearchMatch,
    UniversalStructureCreationResult, UniversalStructureRecord, UniversalSearchMatch,
)
from . import multiomics_python
from .universal_core import MODES as UNIVERSAL_MODES
from .universal_core import Stack, compare_stacks, cyclic_pairs, linear_pairs
from .universal_schema import (
    LocalCoordinates, QueryCoordinates, RegisterCoordinates, Schema, SchemaEncoder, Structure,
    resolve_active_layers,
)

logger = logging.getLogger(__name__)

# Ergebnisse des Subgraph Algorithmus, die als Treffer gelten
MATCH_RESULTS = frozenset({'keep_B', 'equal_keep_A', 'equal_keep_B'})


def compute_signatures(matrix: np.ndarray) -> List[int]:
    """Berechnet Spalten-Signaturen fuer Adjacency Matrix"""
    n = matrix.shape[0]
    signatures = []
    for col in range(n):
        row_sig = sum(2**i for i in range(n) if matrix[i, col] == 1)
        col_weight = col * (2**n)
        signatures.append(row_sig + col_weight)
    return signatures


def compute_signature_hash(signatures: List[int]) -> str:
    """Berechnet SHA-256 Hash der Signatur-Sequenz"""
    sig_str = str(signatures).encode()
    return hashlib.sha256(sig_str).hexdigest()


def create_network(
    name: str,
    network_type: str,
    organism: str,
    description: str,
    node_labels: List[str],
    adjacency_matrix: List[List[int]]
) -> NetworkCreationResult:
    """
    Erstellt neues biologisches Netzwerk
    
    Args:
        name: Name des Netzwerks
        network_type: Typ (z.B. 'protein', 'metabolic')
        organism: Organismus (z.B. 'Human')
        description: Beschreibung
        node_labels: Labels der Knoten
        adjacency_matrix: Adjazenzmatrix
        
    Returns:
        NetworkCreationResult mit den Details des erstellten Netzwerks
        
    Raises:
        Exception: Bei Datenbankfehler
    """
    logger.info(f"create_network: name={name} type={network_type} organism={organism}")
    
    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)

        matrix_np = np.array(adjacency_matrix, dtype=int)
        node_count = len(node_labels)
        edge_count = int(np.sum(matrix_np))

        signatures = compute_signatures(matrix_np)
        sig_hash = compute_signature_hash(signatures)

        cursor.execute("""
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING network_id
        """, (name, network_type, organism, description, node_count, edge_count))

        network_id = cursor.fetchone()['network_id']

        cursor.execute("""
            INSERT INTO network_matrices
            (network_id, node_labels, adjacency_matrix, signature_array, signature_hash)
            VALUES (%s, %s, %s, %s, %s)
        """, (network_id, node_labels, adjacency_matrix, signatures, sig_hash))

        logger.info(f"create_network: Created network_id={network_id} nodes={node_count} edges={edge_count}")
        
        # Gibt Domain Model zurück!
        return NetworkCreationResult(
            network_id=network_id,
            name=name,
            network_type=network_type,
            organism=organism,
            description=description,
            node_count=node_count,
            edge_count=edge_count,
            signature_hash=sig_hash
        )


def get_all_networks(limit: int = 33, random_sample: bool = True) -> List[NetworkSummary]:
    """
    Holt Netzwerk-Zusammenfassungen aus der DB
    
    Args:
        limit: Maximale Anzahl zurückgegebener Netzwerke (default: 33)
        random_sample: Wenn True, werden zufällige Netzwerke geladen (default: True)
        
    Returns:
        Liste von NetworkSummary Domain Models
        
    Raises:
        Exception: Bei Datenbankfehler
    """
    logger.info(f"get_all_networks: limit={limit} random_sample={random_sample}")
    
    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)

        if random_sample:
            cursor.execute("""
                SELECT bn.*, nm.node_labels, nm.signature_hash
                FROM biological_networks bn
                LEFT JOIN network_matrices nm ON bn.network_id = nm.network_id
                ORDER BY RANDOM()
                LIMIT %s
            """, (limit,))
        else:
            cursor.execute("""
                SELECT bn.*, nm.node_labels, nm.signature_hash
                FROM biological_networks bn
                LEFT JOIN network_matrices nm ON bn.network_id = nm.network_id
                ORDER BY bn.created_at DESC
                LIMIT %s
            """, (limit,))

        results = cursor.fetchall()
        logger.info(f"get_all_networks: Fetched {len(results)} records")
        
        # Konvertiert Dicts zu Domain Models
        return [
            NetworkSummary(
                network_id=row['network_id'],
                name=row['name'],
                network_type=row['network_type'],
                organism=row['organism'],
                node_count=row['node_count'],
                edge_count=row['edge_count'],
                signature_hash=row.get('signature_hash'),
                created_at=str(row.get('created_at')) if row.get('created_at') else None
            )
            for row in results
        ]


def get_network_by_id(network_id: int) -> Optional[Network]:
    """
    Holt spezifisches Netzwerk mit kompletter Matrix
    
    Args:
        network_id: ID des Netzwerks
        
    Returns:
        Network Domain Model oder None wenn nicht gefunden
        
    Raises:
        Exception: Bei Datenbankfehler
    """
    logger.info(f"get_network_by_id: network_id={network_id}")
    
    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)
        cursor.execute("""
            SELECT bn.*, nm.node_labels, nm.adjacency_matrix, nm.signature_array, nm.signature_hash
            FROM biological_networks bn
            JOIN network_matrices nm ON bn.network_id = nm.network_id
            WHERE bn.network_id = %s
        """, (network_id,))
        
        result = cursor.fetchone()
        
        if result:
            logger.info(f"get_network_by_id: Found network '{result['name']}'")
            # Konvertiert Dict zu Domain Model
            return Network(
                network_id=result['network_id'],
                name=result['name'],
                network_type=result['network_type'],
                organism=result['organism'],
                description=result['description'],
                node_labels=result['node_labels'],
                adjacency_matrix=result['adjacency_matrix'],
                node_count=result['node_count'],
                edge_count=result['edge_count'],
                signature_array=result.get('signature_array'),
                signature_hash=result.get('signature_hash'),
                created_at=str(result.get('created_at')) if result.get('created_at') else None
            )
        else:
            logger.warning(f"get_network_by_id: network_id={network_id} not found")
            return None


def search_subgraph(
    query_matrix: List[List[int]],
    query_labels: List[str]
) -> List[SearchMatch]:
    """
    Sucht in DB nach Netzwerken, die query_matrix enthalten könnten
    
    Nutzt den Subgraph Algorithmus (Python-Dependency) über einen
    ProcessPoolExecutor, der alle Kandidaten parallel vergleicht.
    
    Args:
        query_matrix: Adjazenzmatrix des Such-Subgraph
        query_labels: Knoten-Labels des Such-Subgraph
        
    Returns:
        Liste von SearchMatch Domain Models
        
    Raises:
        Exception: Bei Datenbankfehler oder Verarbeitungsfehler
    """
    logger.info(f"search_subgraph: Starting search for subgraph with {len(query_labels)} nodes")
    
    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)

        query_np = np.array(query_matrix, dtype=int)
        query_node_count = query_np.shape[0]
        query_edge_count = int(np.sum(query_np))

        # Finde Kandidaten die mindestens so viele Knoten/Kanten haben
        cursor.execute("""
            SELECT bn.network_id, bn.name, bn.network_type, bn.organism,
                   bn.node_count, bn.edge_count,
                   nm.node_labels, nm.adjacency_matrix
            FROM biological_networks bn
            JOIN network_matrices nm ON bn.network_id = nm.network_id
            WHERE bn.node_count >= %s AND bn.edge_count >= %s
            ORDER BY bn.node_count ASC
        """, (query_node_count, query_edge_count))

        candidates = cursor.fetchall()
        logger.info(f"search_subgraph: {len(candidates)} candidates for query (n={query_node_count}, e={query_edge_count})")

        # Query = A, Kandidat = B. Alle Kandidaten parallel vergleichen.
        outcomes = compare_many(
            query_matrix,
            [candidate['adjacency_matrix'] for candidate in candidates]
        )

        # Ergebnisse des Subgraph Algorithmus (A = Query, B = Kandidat):
        # keep_B       : Query ist in Kandidat enthalten (Match!)
        # equal_keep_* : Der Algorithmus erkennt Query und Kandidat als gleich (exakter Match!)
        # keep_A       : Kandidat ist in Query enthalten (kein Match)
        # keep_both    : Keine Subgraph-Beziehung (kein Match)
        matches = []
        failed = 0
        for candidate, (result, error) in zip(candidates, outcomes):
            if error:
                failed += 1
                logger.warning(f"search_subgraph: Comparison error for network {candidate['network_id']}: {error}")
                continue

            if result in MATCH_RESULTS:
                match_type = 'exact' if result.startswith('equal_') else 'subgraph'

                match = SearchMatch(
                    network_id=candidate['network_id'],
                    name=candidate['name'],
                    network_type=candidate['network_type'],
                    organism=candidate['organism'],
                    node_count=candidate['node_count'],
                    edge_count=candidate['edge_count'],
                    node_labels=candidate['node_labels'],
                    match_type=match_type,
                    subgraph_result=result
                )
                matches.append(match)

        if failed:
            logger.warning(f"search_subgraph: {failed} of {len(candidates)} comparisons failed")

        logger.info(f"search_subgraph: Found {len(matches)} matches")
        return matches


def delete_network(network_id: int) -> bool:
    """
    Löscht Netzwerk aus DB (CASCADE löscht auch Matrix)
    
    Args:
        network_id: ID des zu löschenden Netzwerks
        
    Returns:
        True wenn erfolgreich gelöscht, False wenn nicht gefunden
        
    Raises:
        Exception: Bei Datenbankfehler
    """
    logger.info(f"delete_network: network_id={network_id}")
    
    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)
        cursor.execute("""
            DELETE FROM biological_networks WHERE network_id = %s
            RETURNING network_id
        """, (network_id,))
        
        deleted = cursor.fetchone() is not None
        
        if deleted:
            logger.info(f"delete_network: network_id={network_id} deleted successfully")
        else:
            logger.warning(f"delete_network: network_id={network_id} not found")
            
        return deleted


# ============================================================================
# Multi-Omics (Mehrschicht-Netzwerke)
# ============================================================================

def validate_multiomics_input(
    node_labels: Sequence[str],
    layer_names: Sequence[str],
    layer_matrices: Sequence[List[List[int]]]
) -> None:
    """
    Prüft die Eingabe für Multi-Omics-Netzwerke und -Suchen.

    Raises:
        ValueError: Namen und Matrizen passen nicht zusammen, Schichtnamen doppelt,
            Schichten nicht quadratisch/binär/gleich groß, mehr als 63 Knoten oder die
            Zahl der Knoten-Labels weicht von der Matrixgröße ab
    """
    if len(layer_names) != len(layer_matrices):
        raise ValueError("layer names and layer matrices must have the same length")
    if len(set(layer_names)) != len(layer_names):
        raise ValueError("layer names must be unique")
    multiomics_python.validate_layer_stack(layer_matrices, "layers")
    if len(layer_matrices[0]) != len(node_labels):
        raise ValueError("number of node labels must equal the size of the adjacency matrices")


def create_multiomics_network(
    name: str,
    network_type: str,
    organism: str,
    description: str,
    node_labels: List[str],
    layer_names: List[str],
    layer_matrices: List[List[List[int]]]
) -> MultiOmicsCreationResult:
    """
    Erstellt ein Multi-Omics-Netzwerk (mehrere Schichten über denselben Knoten)

    Metadaten liegen wie bei jedem Netzwerk in biological_networks (edge_count = Summe über
    alle Schichten), die Knoten-Labels in omics_networks und je Schicht eine Zeile in
    omics_layers (Matrix und Zeilenkomponenten).

    Args:
        name: Name des Netzwerks
        network_type: Typ (z.B. 'multi_omics')
        organism: Organismus
        description: Beschreibung
        node_labels: Labels der Knoten (für alle Schichten gleich)
        layer_names: Namen der Schichten (eindeutig)
        layer_matrices: Adjazenzmatrix je Schicht, gleiche Reihenfolge wie layer_names

    Returns:
        MultiOmicsCreationResult mit den Details des erstellten Netzwerks

    Raises:
        ValueError: Bei ungültiger Eingabe (siehe validate_multiomics_input)
        Exception: Bei Datenbankfehler
    """
    validate_multiomics_input(node_labels, layer_names, layer_matrices)
    logger.info(
        f"create_multiomics_network: name={name} type={network_type} "
        f"organism={organism} layers={len(layer_names)}"
    )

    node_count = len(node_labels)
    edge_count = multiomics_python.total_edges(layer_matrices)
    components = [list(multiomics_python.row_components(matrix)) for matrix in layer_matrices]
    sig_hash = compute_signature_hash(components)

    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)

        cursor.execute("""
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING network_id
        """, (name, network_type, organism, description, node_count, edge_count))

        network_id = cursor.fetchone()['network_id']

        cursor.execute("""
            INSERT INTO omics_networks
            (network_id, node_labels, layer_count, signature_hash)
            VALUES (%s, %s, %s, %s)
        """, (network_id, node_labels, len(layer_names), sig_hash))

        for index, (layer_name, matrix, row_comps) in enumerate(zip(layer_names, layer_matrices, components)):
            cursor.execute("""
                INSERT INTO omics_layers
                (network_id, layer_index, layer_name, adjacency_matrix, row_components, edge_count)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (network_id, index, layer_name, matrix, row_comps, multiomics_python.total_edges([matrix])))

        logger.info(
            f"create_multiomics_network: Created network_id={network_id} "
            f"nodes={node_count} edges={edge_count} layers={len(layer_names)}"
        )

        return MultiOmicsCreationResult(
            network_id=network_id,
            name=name,
            network_type=network_type,
            organism=organism,
            description=description,
            node_count=node_count,
            edge_count=edge_count,
            layer_names=list(layer_names),
            signature_hash=sig_hash
        )


def get_multiomics_network_by_id(network_id: int) -> Optional[MultiOmicsNetwork]:
    """
    Holt ein Multi-Omics-Netzwerk mit allen Schichten

    Args:
        network_id: ID des Netzwerks

    Returns:
        MultiOmicsNetwork Domain Model oder None, wenn nicht vorhanden (auch wenn die ID
        zu einem Netzwerk ohne Schichten gehört)

    Raises:
        Exception: Bei Datenbankfehler
    """
    logger.info(f"get_multiomics_network_by_id: network_id={network_id}")

    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)
        cursor.execute("""
            SELECT bn.*, om.node_labels, om.signature_hash
            FROM biological_networks bn
            JOIN omics_networks om ON bn.network_id = om.network_id
            WHERE bn.network_id = %s
        """, (network_id,))

        result = cursor.fetchone()
        if not result:
            logger.warning(f"get_multiomics_network_by_id: network_id={network_id} not found")
            return None

        cursor.execute("""
            SELECT layer_name, adjacency_matrix, edge_count
            FROM omics_layers
            WHERE network_id = %s
            ORDER BY layer_index ASC
        """, (network_id,))
        layers = [
            OmicsLayer(
                layer_name=row['layer_name'],
                adjacency_matrix=row['adjacency_matrix'],
                edge_count=row['edge_count']
            )
            for row in cursor.fetchall()
        ]

        logger.info(f"get_multiomics_network_by_id: Found network '{result['name']}' with {len(layers)} layers")
        return MultiOmicsNetwork(
            network_id=result['network_id'],
            name=result['name'],
            network_type=result['network_type'],
            organism=result['organism'],
            description=result['description'],
            node_labels=result['node_labels'],
            node_count=result['node_count'],
            edge_count=result['edge_count'],
            layers=layers,
            signature_hash=result.get('signature_hash'),
            created_at=str(result.get('created_at')) if result.get('created_at') else None
        )


def search_multiomics(
    layer_names: List[str],
    layer_matrices: List[List[List[int]]],
    query_labels: List[str],
    mode: str = 'coherent'
) -> List[MultiOmicsSearchMatch]:
    """
    Sucht Multi-Omics-Netzwerke, die die Query-Schichten enthalten

    Kandidaten sind Netzwerke, die alle Schichten der Query (nach Name) besitzen und
    mindestens so viele Knoten haben. Eine Vorauswahl nach der Kantenzahl gibt es hier
    bewusst nicht: Nach der Relation des Algorithmus können Graphen mit mehr Kanten in
    Graphen mit weniger Kanten enthalten sein, die Kantenzahl wäre daher kein sicheres
    Ausschlusskriterium. Die Kandidaten werden parallel mit MultiOmics (C++ über
    CSUBGRAPH_LIB_PATH, sonst Python) verglichen.

    Args:
        layer_names: Namen der Query-Schichten
        layer_matrices: Adjazenzmatrix je Query-Schicht (gleiche Reihenfolge)
        query_labels: Knoten-Labels der Query
        mode: 'coherent' (alle Schichten an derselben Position) oder 'independent'

    Returns:
        Liste von MultiOmicsSearchMatch Domain Models

    Raises:
        ValueError: Bei ungültiger Eingabe oder unbekanntem Modus
        Exception: Bei Datenbankfehler oder Verarbeitungsfehler
    """
    if mode not in multiomics_python.MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {multiomics_python.MODES}")
    validate_multiomics_input(query_labels, layer_names, layer_matrices)
    query_node_count = len(layer_matrices[0])
    logger.info(
        f"search_multiomics: Starting search with {query_node_count} nodes, "
        f"{len(layer_names)} layers, mode={mode}"
    )

    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)

        cursor.execute("""
            SELECT bn.network_id, bn.name, bn.network_type, bn.organism,
                   bn.node_count, bn.edge_count, om.node_labels,
                   ol.layer_name, ol.adjacency_matrix
            FROM biological_networks bn
            JOIN omics_networks om ON om.network_id = bn.network_id
            JOIN omics_layers ol ON ol.network_id = bn.network_id AND ol.layer_name = ANY(%s)
            WHERE bn.node_count >= %s
              AND (SELECT COUNT(*) FROM omics_layers sel
                   WHERE sel.network_id = bn.network_id AND sel.layer_name = ANY(%s)) = %s
            ORDER BY bn.node_count ASC, bn.network_id ASC
        """, (layer_names, query_node_count, layer_names, len(layer_names)))

        # Eine Zeile je (Netzwerk, Schicht) -> ein Kandidat je Netzwerk
        candidates: Dict[int, dict] = {}
        for row in cursor.fetchall():
            candidate = candidates.setdefault(row['network_id'], {'meta': row, 'layers': {}})
            candidate['layers'][row['layer_name']] = row['adjacency_matrix']
        candidate_list = list(candidates.values())
        logger.info(
            f"search_multiomics: {len(candidate_list)} candidates for query "
            f"(n={query_node_count}, layers={len(layer_names)})"
        )

        # Query = A, Kandidat = B, Schichten in der Reihenfolge der Query
        outcomes = compare_many_multiomics(
            layer_matrices,
            [[candidate['layers'][name] for name in layer_names] for candidate in candidate_list],
            mode
        )

        matches = []
        failed = 0
        for candidate, (result, error) in zip(candidate_list, outcomes):
            meta = candidate['meta']
            if error:
                failed += 1
                logger.warning(
                    f"search_multiomics: Comparison error for network {meta['network_id']}: {error}"
                )
                continue

            if result in MATCH_RESULTS:
                matches.append(MultiOmicsSearchMatch(
                    network_id=meta['network_id'],
                    name=meta['name'],
                    network_type=meta['network_type'],
                    organism=meta['organism'],
                    node_count=meta['node_count'],
                    edge_count=meta['edge_count'],
                    node_labels=meta['node_labels'],
                    layer_names=list(layer_names),
                    mode=mode,
                    match_type='exact' if result.startswith('equal_') else 'subgraph',
                    subgraph_result=result
                ))

        if failed:
            logger.warning(f"search_multiomics: {failed} of {len(candidate_list)} comparisons failed")

        logger.info(f"search_multiomics: Found {len(matches)} matches")
        return matches


# ============================================================================
# Universelle Kodierung (beliebige Strukturen eines Schemas, Indexsuche)
# ============================================================================

# Übersetzung der Ergebnisse von universal_core.compare_stacks (A = Query, B = gespeicherte
# Struktur) in die Werte der übrigen Suchen; nur diese gelten als Treffer.
UNIVERSAL_MATCH_RESULTS = {
    'KEEP_B': 'keep_B',
    'EQUAL_KEEP_A': 'equal_keep_A',
    'EQUAL_KEEP_B': 'equal_keep_B',
    'IDENTICAL': 'equal_keep_A',
}


def component_hash(component: Iterable[int]) -> str:
    """Eindeutiger kurzer Schlüssel einer Komponente (SHA-256 der sortierten Elemente)."""
    return hashlib.sha256(",".join(str(member) for member in sorted(component)).encode()).hexdigest()


def stack_signature_hash(stack: Stack) -> str:
    """SHA-256 Hash des kodierten Stapels (stabil, unabhängig von der Mengenreihenfolge)."""
    return hashlib.sha256(json.dumps(stack.to_lists(), separators=(",", ":")).encode()).hexdigest()


def register_universal_schema(schema: Schema) -> int:
    """
    Legt ein Schema an (idempotent) und gibt seine ID zurück.

    Ist unter Name und Version bereits ein *anderes* Schema gespeichert, wird abgelehnt: Die
    Schichtanordnung eines Schemas ändert sich nie, Änderungen bekommen eine neue Version.

    Raises:
        ValueError: Name und Version sind mit abweichender Definition bereits vergeben
        Exception: Bei Datenbankfehler
    """
    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)
        cursor.execute("""
            SELECT schema_id, definition FROM universal_schemas
            WHERE name = %s AND version = %s
        """, (schema.name, schema.version))
        row = cursor.fetchone()
        if row:
            if Schema.from_dict(row['definition']) != schema:
                raise ValueError(
                    f"schema {schema.name!r} version {schema.version} is already registered "
                    "with a different definition"
                )
            return row['schema_id']

        cursor.execute("""
            INSERT INTO universal_schemas (name, version, layer_count, definition)
            VALUES (%s, %s, %s, %s::jsonb)
            RETURNING schema_id
        """, (schema.name, schema.version, schema.layer_count, json.dumps(schema.to_dict())))
        schema_id = cursor.fetchone()['schema_id']
        logger.info(
            f"register_universal_schema: schema_id={schema_id} name={schema.name} "
            f"version={schema.version} layers={schema.layer_count}"
        )
        return schema_id


def get_universal_schema(name: str, version: Optional[int] = None) -> Optional[Schema]:
    """
    Holt ein Schema (ohne Version die neueste).

    Returns:
        Schema oder None, wenn nicht vorhanden
    """
    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)
        loaded = _load_schema(cursor, name, version, required=False)
        return loaded[1] if loaded else None


def _load_schema(cursor, name: str, version: Optional[int],
                 required: bool = True) -> Optional[Tuple[int, Schema]]:
    """Lädt (schema_id, Schema); ohne Version die neueste. Fehlt es: ValueError oder None."""
    if version is None:
        cursor.execute("""
            SELECT schema_id, definition FROM universal_schemas
            WHERE name = %s ORDER BY version DESC LIMIT 1
        """, (name,))
    else:
        cursor.execute("""
            SELECT schema_id, definition FROM universal_schemas
            WHERE name = %s AND version = %s
        """, (name, version))
    row = cursor.fetchone()
    if not row:
        if required:
            raise ValueError(f"unknown schema {name!r}" + (f" version {version}" if version else ""))
        return None
    return row['schema_id'], Schema.from_dict(row['definition'])


def _register_entities(cursor, names: Sequence[str]) -> Dict[str, int]:
    """Vergibt Koordinaten für neue Entitäten (bestehende bleiben unverändert) und liefert alle."""
    unique = list(dict.fromkeys(names))
    if not unique:
        return {}
    cursor.execute("""
        INSERT INTO entity_register (entity)
        SELECT unnest(%s::text[])
        ON CONFLICT (entity) DO NOTHING
    """, (unique,))
    return _lookup_entities(cursor, unique)


def _lookup_entities(cursor, names: Sequence[str]) -> Dict[str, int]:
    """Koordinaten der bereits registrierten Entitäten (vergibt nichts)."""
    unique = list(dict.fromkeys(names))
    if not unique:
        return {}
    cursor.execute("""
        SELECT entity, coordinate FROM entity_register WHERE entity = ANY(%s)
    """, (unique,))
    return {row['entity']: row['coordinate'] for row in cursor.fetchall()}


def _next_free_coordinate(cursor) -> int:
    """Kleinste Koordinate oberhalb aller vergebenen."""
    cursor.execute("SELECT COALESCE(MAX(coordinate), -1) + 1 AS next_free FROM entity_register")
    return cursor.fetchone()['next_free']


def _encoder(cursor, schema: Schema, structure: Structure, write: bool) -> SchemaEncoder:
    """Kodierer mit dem Koordinatensystem des Schemas (Schreiben vergibt, Suchen liest nur)."""
    names = list(structure.entities)
    if schema.coordinates == "local":
        return SchemaEncoder(schema, LocalCoordinates(names))
    if write:
        return SchemaEncoder(schema, RegisterCoordinates(_register_entities(cursor, names), frozen=True))
    known = RegisterCoordinates(_lookup_entities(cursor, names), frozen=True)
    return SchemaEncoder(schema, QueryCoordinates(known, _next_free_coordinate(cursor)))


def _store_components(cursor, schema_id: int, stack: Stack) -> Dict[Tuple[int, str], int]:
    """Legt alle Komponenten des Stapels im Wörterbuch an und liefert ihre Zahlen je (Schicht, Hash)."""
    distinct = {(layer_index, component_hash(component)): component
                for layer_index, layer in enumerate(stack.layers) for component in layer}
    payload = [[layer_index, digest, sorted(component)]
               for (layer_index, digest), component in sorted(distinct.items())]
    cursor.execute("""
        INSERT INTO universal_components (schema_id, layer_index, members_hash, members)
        SELECT %s, (e->>0)::int, e->>1, ARRAY(SELECT jsonb_array_elements_text(e->2)::bigint)
        FROM jsonb_array_elements(%s::jsonb) AS e
        ON CONFLICT (schema_id, layer_index, members_hash) DO NOTHING
    """, (schema_id, json.dumps(payload)))
    return _component_ids(cursor, schema_id, [digest for _, digest in distinct])


def _component_ids(cursor, schema_id: int, digests: Sequence[str]) -> Dict[Tuple[int, str], int]:
    """Zahlen der im Wörterbuch vorhandenen Komponenten je (Schicht, Hash)."""
    cursor.execute("""
        SELECT layer_index, members_hash, component_id FROM universal_components
        WHERE schema_id = %s AND members_hash = ANY(%s)
    """, (schema_id, list(dict.fromkeys(digests))))
    return {(row['layer_index'], row['members_hash']): row['component_id']
            for row in cursor.fetchall()}


def _pair_columns(stack: Stack, ids: Mapping[Tuple[int, str], int]) -> Tuple[List, List, List, List]:
    """Indexeinträge (Schicht, Art, erstes, zweites Element) aller zyklischen und linearen Paare."""
    layer_indices: List[int] = []
    kinds: List[str] = []
    firsts: List[int] = []
    seconds: List[int] = []
    for layer_index, layer in enumerate(stack.layers):
        sequence = [ids[(layer_index, component_hash(component))] for component in layer]
        for kind, pairs in (('cyc', cyclic_pairs(sequence)), ('lin', linear_pairs(sequence))):
            for first, second in sorted(pairs):
                layer_indices.append(layer_index)
                kinds.append(kind)
                firsts.append(first)
                seconds.append(second)
    return layer_indices, kinds, firsts, seconds


def create_universal_structure(
    schema_name: str,
    name: str,
    network_type: str,
    organism: str,
    description: str,
    entities: Union[Mapping[str, Iterable[str]], Iterable[str]],
    relations: Optional[Mapping[str, Any]] = None,
    schema_version: Optional[int] = None
) -> UniversalStructureCreationResult:
    """
    Kodiert eine Struktur nach ihrem Schema und legt sie samt Indexeinträgen an

    Metadaten liegen wie bei jedem Netzwerk in biological_networks (node_count = Entitäten,
    edge_count = Summe aller Relationstupel), der Stapel in universal_structures, die Komponenten im
    Wörterbuch (universal_components) und die zyklischen und linearen Paare im Paarindex
    (universal_pairs). Alles geschieht in einer Transaktion.

    Args:
        schema_name: Name des registrierten Schemas
        name: Name des Netzwerks
        network_type: Typ (z.B. 'regulatory')
        organism: Organismus
        description: Beschreibung
        entities: Entität -> Merkmale oder nur eine Folge von Entitäten (bei lokalen
            Koordinaten bestimmt die Reihenfolge die Koordinaten)
        relations: Relationstyp -> {Tupel: Gewicht} oder Folge von Tupeln (Gewicht 1)
        schema_version: Version des Schemas (Standard: die neueste)

    Returns:
        UniversalStructureCreationResult mit den Details des erstellten Netzwerks

    Raises:
        ValueError: Unbekanntes Schema oder ungültige Struktur (siehe Structure.build)
        Exception: Bei Datenbankfehler
    """
    logger.info(f"create_universal_structure: name={name} schema={schema_name} organism={organism}")

    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)

        schema_id, schema = _load_schema(cursor, schema_name, schema_version)
        structure = Structure.build(schema, entities, relations)
        encoder = _encoder(cursor, schema, structure, write=True)
        stack = encoder.encode(structure)

        node_count = len(structure.entities)
        edge_count = sum(len(rows) for rows in structure.relations.values())
        entity_names = sorted(structure.entities, key=encoder.coordinates)
        sig_hash = stack_signature_hash(stack)

        cursor.execute("""
            INSERT INTO biological_networks
            (name, network_type, organism, description, node_count, edge_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING network_id
        """, (name, network_type, organism, description, node_count, edge_count))
        network_id = cursor.fetchone()['network_id']

        ids = _store_components(cursor, schema_id, stack)

        cursor.execute("""
            INSERT INTO universal_structures
            (network_id, schema_id, length, entity_names, layers, signature_hash)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
        """, (network_id, schema_id, stack.length, entity_names,
              json.dumps(stack.to_lists(), separators=(",", ":")), sig_hash))

        layer_indices, kinds, firsts, seconds = _pair_columns(stack, ids)
        if layer_indices:
            cursor.execute("""
                INSERT INTO universal_pairs
                (schema_id, layer_index, kind, first_id, second_id, network_id, length)
                SELECT %s, t.layer_index, t.kind, t.first_id, t.second_id, %s, %s
                FROM unnest(%s::int[], %s::text[], %s::bigint[], %s::bigint[])
                     AS t(layer_index, kind, first_id, second_id)
            """, (schema_id, network_id, stack.length, layer_indices, kinds, firsts, seconds))

        logger.info(
            f"create_universal_structure: Created network_id={network_id} nodes={node_count} "
            f"edges={edge_count} length={stack.length} pairs={len(layer_indices)}"
        )

        return UniversalStructureCreationResult(
            network_id=network_id,
            name=name,
            network_type=network_type,
            organism=organism,
            description=description,
            schema_name=schema.name,
            schema_version=schema.version,
            node_count=node_count,
            edge_count=edge_count,
            length=stack.length,
            signature_hash=sig_hash
        )


def get_universal_structure_by_id(network_id: int) -> Optional[UniversalStructureRecord]:
    """
    Holt eine universell kodierte Struktur und gewinnt sie aus ihrem Stapel zurück

    Args:
        network_id: ID des Netzwerks

    Returns:
        UniversalStructureRecord oder None, wenn nicht vorhanden (auch wenn die ID zu einem
        Netzwerk ohne Stapel gehört)

    Raises:
        ValueError: Der gespeicherte Stapel liegt nicht im Bild der Kodierung seines Schemas
        Exception: Bei Datenbankfehler
    """
    logger.info(f"get_universal_structure_by_id: network_id={network_id}")

    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)
        cursor.execute("""
            SELECT bn.*, us.length, us.entity_names, us.layers, us.signature_hash,
                   sc.name AS schema_name, sc.version AS schema_version, sc.definition
            FROM biological_networks bn
            JOIN universal_structures us ON us.network_id = bn.network_id
            JOIN universal_schemas sc ON sc.schema_id = us.schema_id
            WHERE bn.network_id = %s
        """, (network_id,))

        row = cursor.fetchone()
        if not row:
            logger.warning(f"get_universal_structure_by_id: network_id={network_id} not found")
            return None

        schema = Schema.from_dict(row['definition'])
        stack = Stack.of(row['layers'])
        existence = stack.layers[schema.layout[("ex",)]]
        assigned = {entity: next(iter(existence[column]))
                    for column, entity in enumerate(row['entity_names'])}
        structure = SchemaEncoder(schema, RegisterCoordinates(assigned, frozen=True)).decode(stack)

        logger.info(f"get_universal_structure_by_id: Found network '{row['name']}'")
        return UniversalStructureRecord(
            network_id=row['network_id'],
            name=row['name'],
            network_type=row['network_type'],
            organism=row['organism'],
            description=row['description'],
            schema_name=row['schema_name'],
            schema_version=row['schema_version'],
            node_count=row['node_count'],
            edge_count=row['edge_count'],
            length=row['length'],
            entity_names=list(row['entity_names']),
            structure=structure,
            signature_hash=row.get('signature_hash'),
            created_at=str(row.get('created_at')) if row.get('created_at') else None
        )


def search_universal(
    schema_name: str,
    entities: Union[Mapping[str, Iterable[str]], Iterable[str]],
    relations: Optional[Mapping[str, Any]] = None,
    mode: str = 'coherent',
    layers: Optional[Sequence[Union[int, str]]] = None,
    include_existence: bool = False,
    schema_version: Optional[int] = None
) -> List[UniversalSearchMatch]:
    """
    Sucht Strukturen desselben Schemas, die die Query enthalten (Indexsuche)

    Die Query wird mit dem Koordinatensystem des Schemas kodiert. Je aktiver Schicht werden
    die Listen der zyklischen Paare zu den linearen Paaren der Query gelesen (Länge der
    gespeicherten Struktur >= Länge der Query) und über alle aktiven Schichten geschnitten.
    Das ist im Modus 'independent' bereits das Ergebnis, ohne Einzelvergleich über die
    Datenbank; es werden nur die Treffer geladen. Im Modus 'coherent' werden diese Kandidaten
    zusätzlich kohärent verifiziert. Eine Vorauswahl nach Knoten- oder Kantenzahl gibt es nicht
    (kein Kantenfilter für diese Relation, siehe Kapitel Universelle Kodierung).

    Args:
        schema_name: Name des registrierten Schemas
        entities: Entitäten der Query (Entität -> Merkmale oder Folge von Entitäten)
        relations: Relationen der Query (Relationstyp -> Tupel/Gewichte)
        mode: 'coherent' (alle aktiven Schichten an derselben Position) oder 'independent'
        layers: aktive Schichten (Indizes oder Namen aus Schema.layer_labels); Standard: alle
            nichtleeren Schichten der Query außer der Existenzschicht
        include_existence: Existenzschicht ohne explizite Auswahl zu den aktiven zählen
        schema_version: Version des Schemas (Standard: die neueste)

    Returns:
        Liste von UniversalSearchMatch Domain Models, sortiert nach Entitätenzahl und ID

    Raises:
        ValueError: Unbekannter Modus oder Schema, ungültige Query oder Schichtauswahl
        Exception: Bei Datenbankfehler
    """
    if mode not in UNIVERSAL_MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {UNIVERSAL_MODES}")
    logger.info(f"search_universal: Starting search schema={schema_name} mode={mode}")

    with get_db_connection() as conn:
        cursor = get_db_cursor(conn)

        schema_id, schema = _load_schema(cursor, schema_name, schema_version)
        structure = Structure.build(schema, entities, relations)
        query = _encoder(cursor, schema, structure, write=False).encode(structure)
        indices = resolve_active_layers(schema, query, layers, include_existence)

        digests = [component_hash(component) for index in indices
                   for component in query.layers[index]]
        ids = _component_ids(cursor, schema_id, digests)

        candidate_sets: List[Set[int]] = []
        for layer_index in indices:
            sequence = [ids.get((layer_index, component_hash(component)))
                        for component in query.layers[layer_index]]
            pairs = sorted(pair for pair in linear_pairs(sequence) if None not in pair)
            reached: Set[int] = set()
            if pairs:
                cursor.execute("""
                    SELECT DISTINCT network_id FROM universal_pairs
                    WHERE schema_id = %s AND layer_index = %s AND kind = 'cyc'
                      AND length >= %s AND (first_id, second_id) IN %s
                """, (schema_id, layer_index, query.length, tuple(pairs)))
                reached = {row['network_id'] for row in cursor.fetchall()}
            candidate_sets.append(reached)
        candidates = set.intersection(*candidate_sets)
        logger.info(
            f"search_universal: {len(candidates)} candidates for query "
            f"(length={query.length}, layers={len(indices)})"
        )
        if not candidates:
            return []

        cursor.execute("""
            SELECT bn.network_id, bn.name, bn.network_type, bn.organism,
                   bn.node_count, bn.edge_count, us.layers
            FROM biological_networks bn
            JOIN universal_structures us ON us.network_id = bn.network_id
            WHERE bn.network_id = ANY(%s)
            ORDER BY bn.node_count ASC, bn.network_id ASC
        """, (sorted(candidates),))

        layer_names = [schema.layer_labels[index] for index in indices]
        matches = []
        for row in cursor.fetchall():
            result = compare_stacks(query, Stack.of(row['layers']), mode, indices)
            if result in UNIVERSAL_MATCH_RESULTS:
                subgraph_result = UNIVERSAL_MATCH_RESULTS[result]
                matches.append(UniversalSearchMatch(
                    network_id=row['network_id'],
                    name=row['name'],
                    network_type=row['network_type'],
                    organism=row['organism'],
                    node_count=row['node_count'],
                    edge_count=row['edge_count'],
                    schema_name=schema.name,
                    schema_version=schema.version,
                    layers=layer_names,
                    mode=mode,
                    match_type='exact' if subgraph_result.startswith('equal_') else 'subgraph',
                    subgraph_result=subgraph_result
                ))

        logger.info(f"search_universal: Found {len(matches)} matches")
        return matches
