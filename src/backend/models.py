"""
Domain Models für Gen-DB

Reine Business-Logik-Modelle ohne Framework-Abhängigkeiten.
Diese Modelle repräsentieren die Core-Entities und werden
zwischen allen Layern der Applikation weitergegeben.

Verwendet: Python dataclasses (Standard Library, keine externen Abhängigkeiten)
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class Network:
    """
    Domain Model für ein biologisches Netzwerk
    
    Attributes:
        network_id: Eindeutige Netzwerk-ID
        name: Name des Netzwerks
        network_type: Typ (z.B. 'protein', 'metabolic', 'regulatory')
        organism: Organismus (z.B. 'Human', 'E.coli')
        description: Beschreibung des Netzwerks
        node_labels: Labels der Knoten
        adjacency_matrix: Adjazenzmatrix als Liste von Listen
        node_count: Anzahl Knoten
        edge_count: Anzahl Kanten
        signature_array: Berechnete Spalten-Signaturen
        signature_hash: SHA-256 Hash der Signaturen
        created_at: Erstell-Zeitstempel
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    description: str
    node_labels: List[str]
    adjacency_matrix: List[List[int]]
    node_count: int
    edge_count: int
    signature_array: Optional[List[int]] = None
    signature_hash: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class NetworkSummary:
    """
    Summary View eines Netzwerks (für Listen-Ansichten)
    
    Enthält nur die wichtigsten Informationen ohne Adjazenzmatrix.
    Verwendet für GET /api/networks (Liste).
    
    Attributes:
        network_id: Eindeutige Netzwerk-ID
        name: Name des Netzwerks
        network_type: Typ des Netzwerks
        organism: Organismus
        node_count: Anzahl Knoten
        edge_count: Anzahl Kanten
        signature_hash: Zur Vorberechnung und Optimierung
        created_at: Erstell-Zeitstempel
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    node_count: int
    edge_count: int
    signature_hash: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class SearchMatch:
    """
    Suchresultat für Subgraph-Vergleich
    
    Attributes:
        network_id: Gefundenes Netzwerk
        name: Name des Netzwerks
        network_type: Typ des Netzwerks
        organism: Organismus
        node_count: Anzahl Knoten
        edge_count: Anzahl Kanten
        node_labels: Labels der Knoten
        match_type: Art des Match ('exact' = identisch, 'subgraph' = ist Subgraph)
        subgraph_result: Rohes Ergebnis vom C++-Executor
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    node_count: int
    edge_count: int
    node_labels: List[str]
    match_type: str  # 'exact' oder 'subgraph'
    subgraph_result: str  # Raw result from C++: 'KEEP_B', 'IDENTICAL', etc.


@dataclass
class NetworkCreationResult:
    """
    Resultat nach erfolgreicher Netzwerk-Erstellung
    
    Attributes:
        network_id: ID des neu erstellten Netzwerks
        name: Name
        network_type: Typ
        organism: Organismus
        description: Beschreibung
        node_count: Anzahl Knoten
        edge_count: Anzahl Kanten
        signature_hash: Berechneter Hash
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    description: str
    node_count: int
    edge_count: int
    signature_hash: str
