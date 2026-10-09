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

from .universal_schema import Structure


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
        subgraph_result: Rohes Ergebnis des Subgraph Algorithmus
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    node_count: int
    edge_count: int
    node_labels: List[str]
    match_type: str  # 'exact' oder 'subgraph'
    subgraph_result: str  # Raw result: 'keep_B', 'equal_keep_A', 'equal_keep_B'


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


# ============================================================================
# Multi-Omics (Mehrschicht-Netzwerke)
# ============================================================================

@dataclass
class OmicsLayer:
    """
    Eine Schicht eines Multi-Omics-Netzwerks (z.B. Transkriptom, Proteom, Metabolom)

    Attributes:
        layer_name: Name der Schicht (innerhalb eines Netzwerks eindeutig)
        adjacency_matrix: Adjazenzmatrix der Schicht (n x n, gleiche Knoten in allen Schichten)
        edge_count: Anzahl Kanten dieser Schicht
    """
    layer_name: str
    adjacency_matrix: List[List[int]]
    edge_count: int


@dataclass
class MultiOmicsNetwork:
    """
    Domain Model für ein Multi-Omics-Netzwerk

    Alle Schichten beziehen sich auf dieselbe, geordnete Knotenmenge (node_labels).

    Attributes:
        network_id: Eindeutige Netzwerk-ID (gleiche ID wie in biological_networks)
        name: Name des Netzwerks
        network_type: Typ (Standard: 'multi_omics')
        organism: Organismus
        description: Beschreibung
        node_labels: Labels der Knoten
        node_count: Anzahl Knoten
        edge_count: Gesamtzahl der Kanten über alle Schichten
        layers: Schichten in ihrer gespeicherten Reihenfolge
        signature_hash: SHA-256 Hash der Signaturen aller Schichten
        created_at: Erstell-Zeitstempel
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    description: str
    node_labels: List[str]
    node_count: int
    edge_count: int
    layers: List[OmicsLayer]
    signature_hash: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class MultiOmicsCreationResult:
    """
    Resultat nach erfolgreicher Erstellung eines Multi-Omics-Netzwerks

    Attributes:
        network_id: ID des neu erstellten Netzwerks
        name: Name
        network_type: Typ
        organism: Organismus
        description: Beschreibung
        node_count: Anzahl Knoten
        edge_count: Gesamtzahl der Kanten über alle Schichten
        layer_names: Namen der gespeicherten Schichten
        signature_hash: Berechneter Hash
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    description: str
    node_count: int
    edge_count: int
    layer_names: List[str]
    signature_hash: str


@dataclass
class MultiOmicsSearchMatch:
    """
    Suchresultat für die Multi-Omics-Suche

    Attributes:
        network_id: Gefundenes Netzwerk
        name: Name des Netzwerks
        network_type: Typ des Netzwerks
        organism: Organismus
        node_count: Anzahl Knoten
        edge_count: Gesamtzahl der Kanten über alle Schichten
        node_labels: Labels der Knoten
        layer_names: Verglichene Schichten (Reihenfolge der Query)
        mode: Verwendeter Modus ('coherent' oder 'independent')
        match_type: Art des Match ('exact' = gleich, 'subgraph' = Query ist enthalten)
        subgraph_result: Rohes Ergebnis ('keep_B', 'equal_keep_A', 'equal_keep_B')
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    node_count: int
    edge_count: int
    node_labels: List[str]
    layer_names: List[str]
    mode: str
    match_type: str
    subgraph_result: str


# ============================================================================
# Universelle Kodierung (beliebige Strukturen eines Schemas)
# ============================================================================

@dataclass
class UniversalStructureCreationResult:
    """
    Resultat nach erfolgreicher Erstellung einer universell kodierten Struktur

    Attributes:
        network_id: ID des neu erstellten Netzwerks
        name: Name
        network_type: Typ
        organism: Organismus
        description: Beschreibung
        schema_name: Name des Schemas
        schema_version: Version des Schemas
        node_count: Anzahl Entitäten |V|
        edge_count: Anzahl aller Relationstupel
        length: Länge des kodierten Stapels (Entitäts- plus Relationsspalten)
        signature_hash: SHA-256 Hash des kodierten Stapels
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    description: str
    schema_name: str
    schema_version: int
    node_count: int
    edge_count: int
    length: int
    signature_hash: str


@dataclass
class UniversalStructureRecord:
    """
    Domain Model einer universell kodierten Struktur

    Attributes:
        network_id: Eindeutige Netzwerk-ID (gleiche ID wie in biological_networks)
        name: Name des Netzwerks
        network_type: Typ des Netzwerks
        organism: Organismus
        description: Beschreibung
        schema_name: Name des Schemas
        schema_version: Version des Schemas
        node_count: Anzahl Entitäten |V|
        edge_count: Anzahl aller Relationstupel
        length: Länge des kodierten Stapels
        entity_names: Entitäten in Spaltenreihenfolge
        structure: die aus dem Stapel zurückgewonnene Struktur
        signature_hash: SHA-256 Hash des kodierten Stapels
        created_at: Erstell-Zeitstempel
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    description: str
    schema_name: str
    schema_version: int
    node_count: int
    edge_count: int
    length: int
    entity_names: List[str]
    structure: Structure
    signature_hash: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class UniversalSearchMatch:
    """
    Suchresultat für die Indexsuche über universell kodierte Strukturen

    Attributes:
        network_id: Gefundenes Netzwerk
        name: Name des Netzwerks
        network_type: Typ des Netzwerks
        organism: Organismus
        node_count: Anzahl Entitäten |V|
        edge_count: Anzahl aller Relationstupel
        schema_name: Name des Schemas
        schema_version: Version des Schemas
        layers: Namen der aktiven Schichten der Anfrage
        mode: Verwendeter Modus ('coherent' oder 'independent')
        match_type: Art des Match ('exact' = gegenseitig enthalten, 'subgraph' = Query ist enthalten)
        subgraph_result: Rohes Ergebnis ('keep_B', 'equal_keep_A', 'equal_keep_B')
    """
    network_id: int
    name: str
    network_type: str
    organism: str
    node_count: int
    edge_count: int
    schema_name: str
    schema_version: int
    layers: List[str]
    mode: str
    match_type: str
    subgraph_result: str
