"""
CRUD Operations Layer

Verwaltet alle Datenbankoperationen und gibt Domain Models (nicht Dicts) zurück.
Diese Funktionen sind framework-unabhängig und können von überall aufgerufen werden
(REST API, GraphQL, CLI, etc).

Dependencies:
- Models (Domain Models)
- Database (Verbindung)
- Subgraph Executor (C++ Integration)
"""

import logging
import hashlib
import numpy as np
from typing import List, Optional
from .database import get_db_connection, get_db_cursor
from .subgraph_executor import compare_graphs_async
from .models import Network, NetworkSummary, SearchMatch, NetworkCreationResult

logger = logging.getLogger(__name__)


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
    
    Nutzt C++-basierte Subgraph-Executor mit ProcessPoolExecutor für
    parallele nicht-blockierende Ausführung.
    
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

        matches = []
        for candidate in candidates:
            candidate_matrix = candidate['adjacency_matrix']

            # Führe C++-Vergleich aus (non-blocking über ProcessPoolExecutor)
            result, error = compare_graphs_async(query_matrix, candidate_matrix)
            
            if error:
                logger.warning(f"search_subgraph: Comparison error for network {candidate['network_id']}: {error}")
                continue

            # Konvertiere C++-Result-Codes zu Match-Typen
            # KEEP_A (0): Query ist Subgraph von Candidate
            # KEEP_B (1): Candidate ist Subgraph von Query (Match!)
            # KEEP_BOTH (2): Keine Subgraph-Beziehung
            # IDENTICAL (3): Identische Graphen (Match!)

            if result in ['KEEP_B', 'IDENTICAL']:
                match_type = 'exact' if result == 'IDENTICAL' else 'subgraph'
                
                # Konvertiert Dict zu Domain Model
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
