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
"""

import logging
import hashlib
import numpy as np
from typing import Dict, List, Optional, Sequence
from .database import get_db_connection, get_db_cursor
from .subgraph_executor import compare_many, compare_many_multiomics
from .models import (
    Network, NetworkSummary, SearchMatch, NetworkCreationResult,
    OmicsLayer, MultiOmicsNetwork, MultiOmicsCreationResult, MultiOmicsSearchMatch,
)
from . import multiomics_python

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
