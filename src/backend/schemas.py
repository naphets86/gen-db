"""
Pydantic Schemas für API Request/Response Validation

Diese Schemas sind NUR für HTTP Input/Output Validation zuständig.
Sie sind direkt mit FastAPI Endpoints verbunden.

Verwendung:
- Eingehende Requests validieren (Auto)
- Ausgehende Responses strukturieren (Auto JSON-Serialisierung)
- Dokumentation/OpenAPI Schema generieren (Auto)

Verwendet: pydantic.BaseModel
"""

from pydantic import BaseModel, Field
from typing import List, Optional


# ============================================================================
# REQUEST SCHEMAS (Input Validation)
# ============================================================================

class NetworkCreate(BaseModel):
    """
    Schema für POST /api/networks Request
    
    Validiert eingehende Anfragen zum Erstellen von Netzwerken.
    Pydantic konvertiert JSON zu diesem Modell und validiert alle Felder.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Name des Netzwerks")
    network_type: str = Field(..., min_length=1, description="Typ des Netzwerks (z.B. 'protein')")
    organism: str = Field(..., min_length=1, description="Organismus (z.B. 'Human')")
    description: Optional[str] = Field(
        default="",
        max_length=1000,
        description="Optionale Beschreibung"
    )
    node_labels: List[str] = Field(
        ...,
        min_items=1,
        description="Labels der Knoten"
    )
    adjacency_matrix: List[List[int]] = Field(
        ...,
        description="Adjazenzmatrix als Liste von Listen (0 oder 1)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Protein Interaction Network",
                "network_type": "protein",
                "organism": "Human",
                "description": "PPI network from BioGrid",
                "node_labels": ["TP53", "BRCA1", "MDM2"],
                "adjacency_matrix": [[0, 1, 1], [1, 0, 0], [1, 0, 0]]
            }
        }


class NetworkSearch(BaseModel):
    """
    Schema für POST /api/networks/search Request
    
    Validiert Subgraph-Such-Anfragen.
    """
    node_labels: List[str] = Field(
        ...,
        min_items=1,
        description="Labels des Such-Subgraph"
    )
    adjacency_matrix: List[List[int]] = Field(
        ...,
        description="Adjazenzmatrix des Such-Subgraph"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "node_labels": ["TP53", "BRCA1"],
                "adjacency_matrix": [[0, 1], [1, 0]]
            }
        }


# ============================================================================
# RESPONSE SCHEMAS (Output Validation)
# ============================================================================

class NetworkResponse(BaseModel):
    """
    Schema für GET /api/networks/{network_id} Response
    
    Vollständige Netzwerk-Information mit Adjazenzmatrix.
    """
    network_id: int = Field(..., description="Eindeutige Netzwerk-ID")
    name: str = Field(..., description="Name des Netzwerks")
    network_type: str = Field(..., description="Typ des Netzwerks")
    organism: str = Field(..., description="Organismus")
    description: str = Field(..., description="Beschreibung")
    node_labels: List[str] = Field(..., description="Knoten-Labels")
    adjacency_matrix: List[List[int]] = Field(..., description="Adjazenzmatrix")
    node_count: int = Field(..., ge=0, description="Anzahl Knoten")
    edge_count: int = Field(..., ge=0, description="Anzahl Kanten")
    signature_array: Optional[List[int]] = Field(None, description="Spalten-Signaturen")
    created_at: Optional[str] = Field(None, description="Erstell-Zeitstempel")

    class Config:
        json_schema_extra = {
            "example": {
                "network_id": 1,
                "name": "Protein Interaction Network",
                "network_type": "protein",
                "organism": "Human",
                "description": "PPI network",
                "node_labels": ["TP53", "BRCA1", "MDM2"],
                "adjacency_matrix": [[0, 1, 1], [1, 0, 0], [1, 0, 0]],
                "node_count": 3,
                "edge_count": 2,
                "created_at": "2024-01-15T10:30:00"
            }
        }


class NetworkSummaryResponse(BaseModel):
    """
    Schema für GET /api/networks Response (Liste)
    
    Vereinfachte Netzwerk-Information ohne Adjazenzmatrix.
    Verwendet für Listen-Views um Bandbreite zu sparen.
    """
    network_id: int = Field(..., description="Eindeutige Netzwerk-ID")
    name: str = Field(..., description="Name des Netzwerks")
    network_type: str = Field(..., description="Typ des Netzwerks")
    organism: str = Field(..., description="Organismus")
    node_count: int = Field(..., ge=0, description="Anzahl Knoten")
    edge_count: int = Field(..., ge=0, description="Anzahl Kanten")
    created_at: Optional[str] = Field(None, description="Erstell-Zeitstempel")

    class Config:
        json_schema_extra = {
            "example": {
                "network_id": 1,
                "name": "Protein Interaction Network",
                "network_type": "protein",
                "organism": "Human",
                "node_count": 3,
                "edge_count": 2,
                "created_at": "2024-01-15T10:30:00"
            }
        }


class SearchMatchResponse(BaseModel):
    """
    Schema für POST /api/networks/search Response (Match)
    
    Ein einzelnes Suchresultat.
    """
    network_id: int = Field(..., description="Gefundenes Netzwerk")
    name: str = Field(..., description="Name des Netzwerks")
    network_type: str = Field(..., description="Typ des Netzwerks")
    organism: str = Field(..., description="Organismus")
    node_labels: List[str] = Field(..., description="Knoten-Labels")
    node_count: int = Field(..., ge=0, description="Anzahl Knoten")
    edge_count: int = Field(..., ge=0, description="Anzahl Kanten")
    match_type: str = Field(
        ...,
        description="Art des Matches: 'exact' (identisch) oder 'subgraph' (ist Subgraph)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "network_id": 5,
                "name": "Full PPI Network",
                "network_type": "protein",
                "organism": "Human",
                "node_labels": ["TP53", "BRCA1", "MDM2", "RAD51"],
                "node_count": 4,
                "edge_count": 3,
                "match_type": "subgraph"
            }
        }


class NetworkCreationResponse(BaseModel):
    """
    Schema für POST /api/networks Response
    
    Resultat nach erfolgreicher Erstellung.
    """
    network_id: int = Field(..., description="ID des neu erstellten Netzwerks")
    name: str = Field(..., description="Name")
    network_type: str = Field(..., description="Typ")
    organism: str = Field(..., description="Organismus")
    description: str = Field(..., description="Beschreibung")
    node_count: int = Field(..., ge=0, description="Anzahl Knoten")
    edge_count: int = Field(..., ge=0, description="Anzahl Kanten")

    class Config:
        json_schema_extra = {
            "example": {
                "network_id": 123,
                "name": "New Network",
                "network_type": "protein",
                "organism": "Human",
                "description": "Created via API",
                "node_count": 3,
                "edge_count": 2
            }
        }


# ============================================================================
# WRAPPER RESPONSES (für Konsistenz mit API)
# ============================================================================

class ListResponse(BaseModel):
    """Wrapper für List-Responses"""
    success: bool = Field(True, description="Erfolgs-Status")
    data: List[NetworkSummaryResponse] = Field(..., description="Daten")
    count: int = Field(..., ge=0, description="Anzahl Einträge")


class SingleResponse(BaseModel):
    """Wrapper für Single-Item-Responses"""
    success: bool = Field(True, description="Erfolgs-Status")
    data: NetworkResponse = Field(..., description="Daten")


class SearchResponse(BaseModel):
    """Wrapper für Search-Responses"""
    success: bool = Field(True, description="Erfolgs-Status")
    data: List[SearchMatchResponse] = Field(..., description="Gefundene Matches")


class CreationResponse(BaseModel):
    """Wrapper für Creation-Responses"""
    success: bool = Field(True, description="Erfolgs-Status")
    data: NetworkCreationResponse = Field(..., description="Erstelle Netzwerk Info")


class DeleteResponse(BaseModel):
    """Wrapper für Delete-Responses"""
    success: bool = Field(True, description="Erfolgs-Status")
    message: str = Field(..., description="Status-Nachricht")


class HealthResponse(BaseModel):
    """Schema für Health-Check Response"""
    status: str = Field(..., description="Status der Applikation")
    database: str = Field(..., description="Status der Datenbankverbindung")


class ErrorResponse(BaseModel):
    """Schema für Error Responses"""
    detail: str = Field(..., description="Fehler-Beschreibung")
