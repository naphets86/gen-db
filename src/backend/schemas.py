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

from pydantic import BaseModel, ConfigDict, Field
from typing import Dict, List, Literal, Optional, Union


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
        min_length=1,
        description="Labels der Knoten"
    )
    adjacency_matrix: List[List[int]] = Field(
        ...,
        description="Adjazenzmatrix als Liste von Listen (0 oder 1)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Protein Interaction Network",
                "network_type": "protein",
                "organism": "Human",
                "description": "PPI network from BioGrid",
                "node_labels": ["TP53", "BRCA1", "MDM2"],
                "adjacency_matrix": [[0, 1, 1], [1, 0, 0], [1, 0, 0]]
            }
        }
    )


class NetworkSearch(BaseModel):
    """
    Schema für POST /api/networks/search Request
    
    Validiert Subgraph-Such-Anfragen.
    """
    node_labels: List[str] = Field(
        ...,
        min_length=1,
        description="Labels des Such-Subgraph"
    )
    adjacency_matrix: List[List[int]] = Field(
        ...,
        description="Adjazenzmatrix des Such-Subgraph"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "node_labels": ["TP53", "BRCA1"],
                "adjacency_matrix": [[0, 1], [1, 0]]
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
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
    )


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

    model_config = ConfigDict(
        json_schema_extra={
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
    )


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

    model_config = ConfigDict(
        json_schema_extra={
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
    )


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

    model_config = ConfigDict(
        json_schema_extra={
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
    )


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


# ============================================================================
# MULTI-OMICS SCHEMAS
# ============================================================================

class OmicsLayerInput(BaseModel):
    """Eine Schicht eines Multi-Omics-Netzwerks (Request)."""
    layer_name: str = Field(..., min_length=1, max_length=100, description="Name der Schicht (z.B. 'proteome')")
    adjacency_matrix: List[List[int]] = Field(
        ...,
        description="Adjazenzmatrix der Schicht (0 oder 1), n x n über die Knoten des Netzwerks"
    )


class MultiOmicsCreate(BaseModel):
    """
    Schema für POST /api/multiomics Request

    Alle Schichten beziehen sich auf dieselben Knoten (node_labels, gleiche Reihenfolge).
    """
    name: str = Field(..., min_length=1, max_length=255, description="Name des Netzwerks")
    network_type: str = Field(default="multi_omics", min_length=1, description="Typ des Netzwerks")
    organism: str = Field(..., min_length=1, description="Organismus (z.B. 'Human')")
    description: Optional[str] = Field(default="", max_length=1000, description="Optionale Beschreibung")
    node_labels: List[str] = Field(..., min_length=1, description="Labels der Knoten")
    layers: List[OmicsLayerInput] = Field(..., min_length=1, description="Schichten mit Adjazenzmatrizen")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "TP53 Multi-Omics",
                "network_type": "multi_omics",
                "organism": "Human",
                "description": "Transkriptom- und Proteom-Schicht",
                "node_labels": ["TP53", "MDM2", "CDKN1A"],
                "layers": [
                    {"layer_name": "transcriptome", "adjacency_matrix": [[0, 1, 1], [0, 0, 0], [0, 0, 0]]},
                    {"layer_name": "proteome", "adjacency_matrix": [[0, 1, 0], [1, 0, 0], [0, 0, 0]]},
                ],
            }
        }
    )


class MultiOmicsSearch(BaseModel):
    """
    Schema für POST /api/multiomics/search Request

    Gesucht werden Multi-Omics-Netzwerke, die alle genannten Schichten besitzen und die
    Query in diesen Schichten enthalten.
    """
    node_labels: List[str] = Field(..., min_length=1, description="Labels des Such-Subgraph")
    layers: List[OmicsLayerInput] = Field(..., min_length=1, description="Schichten der Query")
    mode: Literal["coherent", "independent"] = Field(
        default="coherent",
        description="'coherent': alle Schichten an derselben Position, 'independent': je Schicht eigene Position"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "node_labels": ["TP53", "MDM2"],
                "layers": [
                    {"layer_name": "transcriptome", "adjacency_matrix": [[0, 1], [0, 0]]},
                    {"layer_name": "proteome", "adjacency_matrix": [[0, 1], [1, 0]]},
                ],
                "mode": "coherent",
            }
        }
    )


class UniversalRelationTypeInput(BaseModel):
    """Definition eines Relationstyps in einem universellen Schema."""
    name: str = Field(..., min_length=1)
    arity: int = Field(default=2, ge=1)
    levels: int = Field(default=1, ge=1)


class UniversalSchemaCreate(BaseModel):
    """Schema für POST /api/universal/schemas."""
    name: str = Field(..., min_length=1)
    version: int = Field(default=1, ge=1)
    coordinates: Literal["register", "local"] = "register"
    features: List[str] = Field(default_factory=list)
    relations: List[UniversalRelationTypeInput] = Field(default_factory=list)


class UniversalRelationInput(BaseModel):
    """Ein typisiertes Relationstupel."""
    entities: List[str] = Field(..., min_length=1)
    weight: int = Field(default=1, ge=1)


class UniversalStructureInput(BaseModel):
    """Gemeinsame Nutzdaten für Erstellung und Suche universeller Strukturen."""
    entities: Union[List[str], Dict[str, List[str]]] = Field(
        ..., min_length=1, description="Entitäten oder Entität-zu-Merkmal-Abbildung"
    )
    relations: Dict[str, List[UniversalRelationInput]] = Field(default_factory=dict)


class UniversalStructureCreate(UniversalStructureInput):
    """Schema für POST /api/universal."""
    schema_name: str = Field(..., min_length=1)
    schema_version: Optional[int] = Field(default=None, ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    network_type: str = Field(default="universal", min_length=1)
    organism: str = Field(..., min_length=1)
    description: Optional[str] = Field(default="", max_length=1000)


class UniversalSearch(UniversalStructureInput):
    """Schema für POST /api/universal/search."""
    schema_name: str = Field(..., min_length=1)
    schema_version: Optional[int] = Field(default=None, ge=1)
    mode: Literal["coherent", "independent"] = "coherent"
    layers: Optional[List[Union[int, str]]] = None
    include_existence: bool = False


class OmicsLayerResponse(BaseModel):
    """Eine Schicht eines Multi-Omics-Netzwerks (Response)."""
    layer_name: str = Field(..., description="Name der Schicht")
    adjacency_matrix: List[List[int]] = Field(..., description="Adjazenzmatrix der Schicht")
    edge_count: int = Field(..., ge=0, description="Anzahl Kanten der Schicht")


class MultiOmicsResponse(BaseModel):
    """Schema für GET /api/multiomics/{network_id} Response."""
    network_id: int = Field(..., description="Eindeutige Netzwerk-ID")
    name: str = Field(..., description="Name des Netzwerks")
    network_type: str = Field(..., description="Typ des Netzwerks")
    organism: str = Field(..., description="Organismus")
    description: str = Field(..., description="Beschreibung")
    node_labels: List[str] = Field(..., description="Knoten-Labels")
    node_count: int = Field(..., ge=0, description="Anzahl Knoten")
    edge_count: int = Field(..., ge=0, description="Gesamtzahl der Kanten über alle Schichten")
    layers: List[OmicsLayerResponse] = Field(..., description="Schichten")
    created_at: Optional[str] = Field(None, description="Erstell-Zeitstempel")


class MultiOmicsCreationResponse(BaseModel):
    """Schema für POST /api/multiomics Response."""
    network_id: int = Field(..., description="ID des neu erstellten Netzwerks")
    name: str = Field(..., description="Name")
    network_type: str = Field(..., description="Typ")
    organism: str = Field(..., description="Organismus")
    description: str = Field(..., description="Beschreibung")
    node_count: int = Field(..., ge=0, description="Anzahl Knoten")
    edge_count: int = Field(..., ge=0, description="Gesamtzahl der Kanten über alle Schichten")
    layer_names: List[str] = Field(..., description="Namen der gespeicherten Schichten")


class MultiOmicsSearchMatchResponse(BaseModel):
    """Ein einzelnes Ergebnis der Multi-Omics-Suche."""
    network_id: int = Field(..., description="Gefundenes Netzwerk")
    name: str = Field(..., description="Name des Netzwerks")
    network_type: str = Field(..., description="Typ des Netzwerks")
    organism: str = Field(..., description="Organismus")
    node_labels: List[str] = Field(..., description="Knoten-Labels")
    node_count: int = Field(..., ge=0, description="Anzahl Knoten")
    edge_count: int = Field(..., ge=0, description="Gesamtzahl der Kanten über alle Schichten")
    layer_names: List[str] = Field(..., description="Verglichene Schichten")
    mode: str = Field(..., description="Verwendeter Modus: 'coherent' oder 'independent'")
    match_type: str = Field(
        ...,
        description="Art des Matches: 'exact' (gleich) oder 'subgraph' (Query ist enthalten)"
    )


class MultiOmicsSingleResponse(BaseModel):
    """Wrapper für ein Multi-Omics-Netzwerk."""
    success: bool = Field(True, description="Erfolgs-Status")
    data: MultiOmicsResponse = Field(..., description="Daten")


class MultiOmicsCreationWrapper(BaseModel):
    """Wrapper für die Erstellung eines Multi-Omics-Netzwerks."""
    success: bool = Field(True, description="Erfolgs-Status")
    data: MultiOmicsCreationResponse = Field(..., description="Erstelltes Netzwerk")


class MultiOmicsSearchResponse(BaseModel):
    """Wrapper für Multi-Omics-Suchergebnisse."""
    success: bool = Field(True, description="Erfolgs-Status")
    data: List[MultiOmicsSearchMatchResponse] = Field(..., description="Gefundene Matches")


class UniversalRelationTypeResponse(BaseModel):
    """Relationstyp eines universellen Schemas."""
    name: str
    arity: int
    levels: int


class UniversalSchemaResponse(BaseModel):
    """Registriertes universelles Schema einschließlich Schichtnamen."""
    schema_id: Optional[int] = None
    name: str
    version: int
    coordinates: str
    features: List[str]
    relations: List[UniversalRelationTypeResponse]
    layer_labels: List[str]


class UniversalSchemaWrapper(BaseModel):
    success: bool = True
    data: UniversalSchemaResponse


class UniversalRelationResponse(BaseModel):
    entities: List[str]
    weight: int


class UniversalStructureResponse(BaseModel):
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
    entities: Dict[str, List[str]]
    relations: Dict[str, List[UniversalRelationResponse]]
    signature_hash: Optional[str] = None
    created_at: Optional[str] = None


class UniversalStructureWrapper(BaseModel):
    success: bool = True
    data: UniversalStructureResponse


class UniversalStructureCreationResponse(BaseModel):
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


class UniversalStructureCreationWrapper(BaseModel):
    success: bool = True
    data: UniversalStructureCreationResponse


class UniversalSearchMatchResponse(BaseModel):
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


class UniversalSearchResponse(BaseModel):
    success: bool = True
    data: List[UniversalSearchMatchResponse]
