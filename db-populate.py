#!/usr/bin/env python3
"""
Script zum Generieren von 1 Million biologischen Netzwerken in PostgreSQL
Optimiert für Performance mit Batch-Inserts
"""

import psycopg2
import numpy as np
import hashlib
from typing import List, Tuple
import time
from datetime import datetime
import argparse

# Datenbank-Konfiguration
DB_CONFIG = {
    'dbname': 'gendb',
    'user': 'postgres',
    'password': 'dbpassword',
    'host': 'localhost',
    'port': 5432
}

# Generierungs-Parameter
TOTAL_NETWORKS = 1_000_000
BATCH_SIZE = 5000  # Anzahl Netzwerke pro Batch-Insert
MIN_NODES = 3
MAX_NODES = 20
EDGE_PROBABILITY = 0.3  # Wahrscheinlichkeit für eine Kante

# Biologische Knoten-Namen
NODE_NAMES = [
    # Metabolite
    'Glucose', 'G6P', 'F6P', 'FBP', 'DHAP', 'G3P', 'Pyruvate', 'Lactate',
    'Acetyl-CoA', 'Citrate', 'Isocitrate', 'α-Ketoglutarate', 'Succinate',
    'Fumarate', 'Malate', 'Oxaloacetate', 'ATP', 'ADP', 'NAD', 'NADH',
    # Proteine
    'p53', 'MDM2', 'ATM', 'DNA-PK', 'CHK2', 'BRCA1', 'BRCA2', 'RAD51',
    'Cyclin-D', 'CDK4', 'Rb', 'E2F', 'p21', 'p27', 'Bax', 'Bcl2',
    'Caspase3', 'PARP', 'AKT', 'mTOR', 'PI3K', 'PTEN', 'ERK', 'MEK',
    # Gene
    'TP53', 'MYC', 'KRAS', 'EGFR', 'BRAF', 'PIK3CA', 'APC', 'PTEN',
    'RB1', 'CDKN2A', 'SMAD4', 'STK11', 'NFE2L2', 'KEAP1', 'CTNNB1',
    # Enzyme
    'Hexokinase', 'PFK', 'Aldolase', 'GAPDH', 'PGK', 'Enolase', 'PK',
    'LDH', 'PDH', 'CS', 'IDH', 'KGDH', 'SDH', 'FH', 'MDH'
]

NETWORK_TYPES = ['metabolic', 'protein', 'gene_regulation']
ORGANISMS = ['Homo sapiens', 'Mus musculus', 'E. coli', 'S. cerevisiae', 
             'D. melanogaster', 'C. elegans', 'A. thaliana']


def compute_signatures(matrix: np.ndarray) -> List[int]:
    """Berechnet Spalten-Signaturen für Adjacency Matrix"""
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


def generate_random_network(network_id: int) -> Tuple:
    """Generiert ein zufälliges biologisches Netzwerk"""
    # Zufällige Netzwerk-Eigenschaften
    node_count = np.random.randint(MIN_NODES, MAX_NODES + 1)
    network_type = np.random.choice(NETWORK_TYPES)
    organism = np.random.choice(ORGANISMS)
    
    # Wähle zufällige Knoten-Namen (ohne Wiederholung)
    node_labels = list(np.random.choice(NODE_NAMES, size=node_count, replace=False))
    
    # Generiere Adjacency Matrix (gerichteter Graph)
    adjacency_matrix = (np.random.random((node_count, node_count)) < EDGE_PROBABILITY).astype(int)
    
    # Keine Selbst-Kanten (Diagonale = 0)
    np.fill_diagonal(adjacency_matrix, 0)
    
    edge_count = int(np.sum(adjacency_matrix))
    
    # Berechne Signaturen
    signatures = compute_signatures(adjacency_matrix)
    sig_hash = compute_signature_hash(signatures)
    
    # Name basierend auf ID und Typ
    name = f"{network_type}_{organism.replace(' ', '_')}_{network_id}"
    description = f"Auto-generated {network_type} network with {node_count} nodes"
    
    return (
        # biological_networks Daten
        name, network_type, organism, description, node_count, edge_count,
        # network_matrices Daten
        node_labels, adjacency_matrix.tolist(), signatures, sig_hash
    )


def batch_insert_networks(conn, networks_data: List[Tuple], start_id: int):
    """Fügt einen Batch von Netzwerken in die DB ein"""
    cursor = conn.cursor()
    
    try:
        # Batch-Insert in biological_networks
        network_values = [
            (start_id + i, data[0], data[1], data[2], data[3], data[4], data[5])
            for i, data in enumerate(networks_data)
        ]
        
        cursor.executemany("""
            INSERT INTO biological_networks 
            (network_id, name, network_type, organism, description, node_count, edge_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, network_values)
        
        # Batch-Insert in network_matrices
        matrix_values = [
            (start_id + i, data[6], data[7], data[8], data[9])
            for i, data in enumerate(networks_data)
        ]
        
        cursor.executemany("""
            INSERT INTO network_matrices 
            (network_id, node_labels, adjacency_matrix, signature_array, signature_hash)
            VALUES (%s, %s, %s, %s, %s)
        """, matrix_values)
        
        conn.commit()
        cursor.close()
        
    except Exception as e:
        conn.rollback()
        cursor.close()
        raise e


def get_current_max_id(conn) -> int:
    """Ermittelt die höchste network_id in der DB"""
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(network_id), 0) FROM biological_networks")
    max_id = cursor.fetchone()[0]
    cursor.close()
    return max_id


def clear_generated_networks(conn):
    """Löscht alle auto-generierten Netzwerke (für Tests)"""
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM biological_networks 
        WHERE description LIKE 'Auto-generated%'
    """)
    conn.commit()
    count = cursor.rowcount
    cursor.close()
    return count


def main():
    parser = argparse.ArgumentParser(description='Generate biological networks for Gen-DB')
    parser.add_argument('--clear', action='store_true', help='Clear auto-generated networks before creating new ones')
    parser.add_argument('--count', type=int, default=TOTAL_NETWORKS, help=f'Number of networks to generate (default: {TOTAL_NETWORKS})')
    args = parser.parse_args()
    
    total_networks = args.count
    
    print("=" * 70)
    print("GEN-DB: Generierung von biologischen Netzwerken")
    print("=" * 70)
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Ziel: {total_networks:,} Netzwerke")
    print(f"Batch-Größe: {BATCH_SIZE:,}")
    print(f"Knoten-Range: {MIN_NODES}-{MAX_NODES}")
    print(f"Kanten-Wahrscheinlichkeit: {EDGE_PROBABILITY}")
    print("=" * 70)
    
    # Verbindung zur Datenbank
    print("\n[1/4] Verbinde mit PostgreSQL...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("✓ Verbindung hergestellt")
    except Exception as e:
        print(f"✗ Fehler bei Verbindung: {e}")
        return
    
    # Optional: Löschen vorheriger auto-generierter Netzwerke
    if args.clear:
        print("\n[2/4] Lösche vorherige auto-generierte Netzwerke...")
        deleted = clear_generated_networks(conn)
        print(f"✓ {deleted:,} Netzwerke gelöscht")
    
    # Ermittle Start-ID
    print(f"\n[{'3' if args.clear else '2'}/4] Ermittle nächste verfügbare ID...")
    start_id = get_current_max_id(conn) + 1
    print(f"✓ Start bei network_id = {start_id}")
    
    # Generiere und füge Netzwerke ein
    print(f"\n[{'4' if args.clear else '3'}/4] Generiere {total_networks:,} Netzwerke...")
    total_batches = (total_networks + BATCH_SIZE - 1) // BATCH_SIZE
    
    start_time = time.time()
    networks_created = 0
    
    for batch_num in range(total_batches):
        batch_start_time = time.time()
        
        # Bestimme Batch-Größe (letzte Batch kann kleiner sein)
        current_batch_size = min(BATCH_SIZE, total_networks - networks_created)
        
        # Generiere Netzwerke für diesen Batch
        batch_data = []
        for i in range(current_batch_size):
            network_id = start_id + networks_created + i
            batch_data.append(generate_random_network(network_id))
        
        # Füge Batch in DB ein
        try:
            batch_insert_networks(conn, batch_data, start_id + networks_created)
            networks_created += current_batch_size
            
            batch_time = time.time() - batch_start_time
            elapsed_time = time.time() - start_time
            progress = (networks_created / total_networks) * 100
            rate = networks_created / elapsed_time if elapsed_time > 0 else 0
            eta = (total_networks - networks_created) / rate if rate > 0 else 0
            
            print(f"  Batch {batch_num + 1}/{total_batches}: "
                  f"{networks_created:,}/{total_networks:,} ({progress:.1f}%) | "
                  f"{rate:.0f} networks/s | "
                  f"ETA: {eta/60:.1f} min | "
                  f"Batch-Zeit: {batch_time:.2f}s")
            
        except Exception as e:
            print(f"\n✗ Fehler bei Batch {batch_num + 1}: {e}")
            conn.close()
            return
    
    total_time = time.time() - start_time
    
    # Statistiken
    print(f"\n[4/4] Erstelle Statistiken...")
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM biological_networks")
    total_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT network_type, COUNT(*) 
        FROM biological_networks 
        WHERE network_id >= %s
        GROUP BY network_type
        ORDER BY COUNT(*) DESC
    """, (start_id,))
    type_stats = cursor.fetchall()
    
    cursor.execute("""
        SELECT AVG(node_count), AVG(edge_count) 
        FROM biological_networks
        WHERE network_id >= %s
    """, (start_id,))
    avg_stats = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    # Abschlussbericht
    print("\n" + "=" * 70)
    print("ABSCHLUSSBERICHT")
    print("=" * 70)
    print(f"✓ Erfolgreich {networks_created:,} Netzwerke erstellt")
    print(f"✓ Gesamtzeit: {total_time/60:.2f} Minuten ({total_time:.1f} Sekunden)")
    print(f"✓ Durchsatz: {networks_created/total_time:.0f} Netzwerke/Sekunde")
    print(f"✓ Gesamt in DB: {total_count:,} Netzwerke")
    print(f"\nVerteilung nach Typ:")
    for ntype, count in type_stats:
        print(f"  - {ntype}: {count:,}")
    print(f"\nDurchschnittliche Größe:")
    print(f"  - Knoten: {avg_stats[0]:.1f}")
    print(f"  - Kanten: {avg_stats[1]:.1f}")
    print("\n" + "=" * 70)
    print(f"Ende: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
