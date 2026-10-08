"""
FastAPI Application für Gen-DB

Orchestriert die verschiedenen Layer der Applikation:
- Config: Umgebungsvariablen
- CRUD: Business Logic
- Schemas: HTTP Input/Output Validation
- Models: Domain Models (interne Repräsentation)

Verantwortlichkeiten:
- HTTP Endpoints definieren
- Request-Schemas validieren (automatisch via Pydantic)
- CRUD aufrufen mit primitiven Werten
- Domain Models zu Response-Schemas mappen
- Response-Schemas validieren und zu JSON serialisieren (automatisch)

Diese Datei hat KEINE Business Logic!
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Config
from .config import get_config

# Domain Models
from .models import (
    Network, NetworkSummary, SearchMatch, NetworkCreationResult,
    MultiOmicsNetwork, MultiOmicsCreationResult, MultiOmicsSearchMatch,
)

# API Schemas
from .schemas import (
    NetworkCreate, NetworkSearch,
    NetworkResponse, NetworkSummaryResponse, SearchMatchResponse,
    NetworkCreationResponse,
    ListResponse, SingleResponse, SearchResponse, CreationResponse,
    DeleteResponse, HealthResponse,
    MultiOmicsCreate, MultiOmicsSearch,
    OmicsLayerResponse, MultiOmicsResponse, MultiOmicsCreationResponse,
    MultiOmicsSearchMatchResponse, MultiOmicsSingleResponse,
    MultiOmicsCreationWrapper, MultiOmicsSearchResponse
)

# CRUD Operations
from . import crud

# Executor Management
from .subgraph_executor import get_backend_name, get_multiomics_backend_name, shutdown_executor

# ============================================================================
# Logging Configuration
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Lifecycle Manager
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle Manager für FastAPI App.
    
    Startet ProcessPoolExecutor bei App-Start und fährt ihn bei 
    Shutdown herunter.
    """
    # Startup
    config = get_config()
    logger.info(f"Starting Gen API - Environment: {config.container_env}")
    backend_name = get_backend_name()
    logger.info(
        "Subgraph algorithm selected: %s",
        "csubgraph (C++)" if backend_name == "csubgraph" else "Python",
    )
    omics_backend_name = get_multiomics_backend_name()
    logger.info(
        "Multi-omics algorithm selected: %s",
        "csubgraph (C++)" if omics_backend_name == "csubgraph" else "Python",
    )
    logger.info("ProcessPoolExecutor ready for Subgraph Executor")
    yield
    
    # Shutdown
    logger.info("Shutting down Gen API")
    shutdown_executor()
    logger.info("Subgraph Executor shut down")


# ============================================================================
# FastAPI App Setup
# ============================================================================

app = FastAPI(
    title="Gen - Biological Network Analysis API",
    description="REST API for searching biological networks using subgraph matching",
    version="1.1.0",
    lifespan=lifespan
)

# CORS Configuration aus Config laden
config = get_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_credentials,
    allow_methods=config.cors_methods,
    allow_headers=config.cors_headers,
)


# ============================================================================
# Helper Functions: Mapping zwischen Models und Schemas
# ============================================================================

def network_summary_to_response(summary: NetworkSummary) -> NetworkSummaryResponse:
    """Konvertiert NetworkSummary Domain Model zu Response Schema"""
    return NetworkSummaryResponse(
        network_id=summary.network_id,
        name=summary.name,
        network_type=summary.network_type,
        organism=summary.organism,
        node_count=summary.node_count,
        edge_count=summary.edge_count,
        created_at=summary.created_at
    )


def network_to_response(network: Network) -> NetworkResponse:
    """Konvertiert Network Domain Model zu Response Schema"""
    return NetworkResponse(
        network_id=network.network_id,
        name=network.name,
        network_type=network.network_type,
        organism=network.organism,
        description=network.description,
        node_labels=network.node_labels,
        adjacency_matrix=network.adjacency_matrix,
        node_count=network.node_count,
        edge_count=network.edge_count,
        signature_array=network.signature_array,
        created_at=network.created_at
    )


def search_match_to_response(match: SearchMatch) -> SearchMatchResponse:
    """Konvertiert SearchMatch Domain Model zu Response Schema"""
    return SearchMatchResponse(
        network_id=match.network_id,
        name=match.name,
        network_type=match.network_type,
        organism=match.organism,
        node_labels=match.node_labels,
        node_count=match.node_count,
        edge_count=match.edge_count,
        match_type=match.match_type
    )


def creation_result_to_response(result: NetworkCreationResult) -> NetworkCreationResponse:
    """Konvertiert NetworkCreationResult Domain Model zu Response Schema"""
    return NetworkCreationResponse(
        network_id=result.network_id,
        name=result.name,
        network_type=result.network_type,
        organism=result.organism,
        description=result.description,
        node_count=result.node_count,
        edge_count=result.edge_count
    )


def multiomics_network_to_response(network: MultiOmicsNetwork) -> MultiOmicsResponse:
    """Konvertiert MultiOmicsNetwork Domain Model zu Response Schema"""
    return MultiOmicsResponse(
        network_id=network.network_id,
        name=network.name,
        network_type=network.network_type,
        organism=network.organism,
        description=network.description,
        node_labels=network.node_labels,
        node_count=network.node_count,
        edge_count=network.edge_count,
        layers=[
            OmicsLayerResponse(
                layer_name=layer.layer_name,
                adjacency_matrix=layer.adjacency_matrix,
                edge_count=layer.edge_count
            )
            for layer in network.layers
        ],
        created_at=network.created_at
    )


def multiomics_creation_to_response(result: MultiOmicsCreationResult) -> MultiOmicsCreationResponse:
    """Konvertiert MultiOmicsCreationResult Domain Model zu Response Schema"""
    return MultiOmicsCreationResponse(
        network_id=result.network_id,
        name=result.name,
        network_type=result.network_type,
        organism=result.organism,
        description=result.description,
        node_count=result.node_count,
        edge_count=result.edge_count,
        layer_names=result.layer_names
    )


def multiomics_match_to_response(match: MultiOmicsSearchMatch) -> MultiOmicsSearchMatchResponse:
    """Konvertiert MultiOmicsSearchMatch Domain Model zu Response Schema"""
    return MultiOmicsSearchMatchResponse(
        network_id=match.network_id,
        name=match.name,
        network_type=match.network_type,
        organism=match.organism,
        node_labels=match.node_labels,
        node_count=match.node_count,
        edge_count=match.edge_count,
        layer_names=match.layer_names,
        mode=match.mode,
        match_type=match.match_type
    )


# ============================================================================
# HTTP Endpoints
# ============================================================================

@app.get(
    "/",
    tags=["Frontend"],
    summary="Serve Frontend"
)
async def root():
    """
    Serves the frontend HTML file
    """
    logger.info("GET / - Serving frontend")
    return FileResponse("src/frontend/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Browsers request a favicon automatically; this application has none."""
    return Response(status_code=204)


@app.get(
    "/api/networks",
    tags=["Networks"],
    response_model=ListResponse,
    summary="Get Networks",
    description="Retrieves a list of biological networks from the database"
)
async def get_networks(limit: int = 33, random: bool = True) -> ListResponse:
    """
    Hole Netzwerk-Zusammenfassungen aus der Datenbank
    
    Args:
        limit: Maximale Anzahl (default: 33)
        random: Zufällige Auswahl (default: True)
        
    Returns:
        ListResponse mit Netzwerk-Zusammenfassungen
    """
    logger.info(f"GET /api/networks limit={limit} random={random}")
    try:
        # CRUD gibt Domain Models zurück
        summaries: List[NetworkSummary] = crud.get_all_networks(
            limit=limit,
            random_sample=random
        )
        
        # Konvertiere zu Response Schemas
        response_data = [network_summary_to_response(s) for s in summaries]
        
        logger.info(f"GET /api/networks - Returned {len(response_data)} networks")
        return ListResponse(
            success=True,
            data=response_data,
            count=len(response_data)
        )
    except Exception as e:
        logger.error(f"GET /api/networks - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/networks/{network_id}",
    tags=["Networks"],
    response_model=SingleResponse,
    summary="Get Network by ID",
    description="Retrieves a specific network with its complete adjacency matrix"
)
async def get_network(network_id: int) -> SingleResponse:
    """
    Hole spezifisches Netzwerk mit vollständiger Matrix
    
    Args:
        network_id: ID des gesuchten Netzwerks
        
    Returns:
        SingleResponse mit vollständigem Netzwerk
    """
    logger.info(f"GET /api/networks/{network_id}")
    try:
        # CRUD gibt Domain Model zurück
        network: Network = crud.get_network_by_id(network_id)
        
        if not network:
            logger.warning(f"GET /api/networks/{network_id} - Not found")
            raise HTTPException(status_code=404, detail="Network not found")
        
        # Konvertiere zu Response Schema
        response_data = network_to_response(network)
        
        logger.info(f"GET /api/networks/{network_id} - Found: {network.name}")
        return SingleResponse(success=True, data=response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/networks/{network_id} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/networks",
    tags=["Networks"],
    response_model=CreationResponse,
    summary="Create Network",
    description="Creates a new biological network"
)
async def create_network(network: NetworkCreate) -> CreationResponse:
    """
    Erstellt neues biologisches Netzwerk
    
    Args:
        network: Request Schema (validiert von Pydantic)
        
    Returns:
        CreationResponse mit den Details des erstellten Netzwerks
    """
    logger.info(
        f"POST /api/networks - name={network.name} "
        f"type={network.network_type} organism={network.organism}"
    )
    try:
        # CRUD nimmt primitive Werte und gibt Domain Model zurück
        result: NetworkCreationResult = crud.create_network(
            name=network.name,
            network_type=network.network_type,
            organism=network.organism,
            description=network.description or "",
            node_labels=network.node_labels,
            adjacency_matrix=network.adjacency_matrix
        )
        
        # Konvertiere zu Response Schema
        response_data = creation_result_to_response(result)
        
        logger.info(f"POST /api/networks - Created network_id={result.network_id}")
        return CreationResponse(success=True, data=response_data)
        
    except Exception as e:
        logger.error(f"POST /api/networks - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/networks/search",
    tags=["Search"],
    response_model=SearchResponse,
    summary="Search Subgraph",
    description="Searches for networks containing the given subgraph using the Subgraph algorithm"
)
async def search_networks(search: NetworkSearch) -> SearchResponse:
    """
    Sucht Netzwerke, die den gegebenen Subgraph enthalten
    
    Args:
        search: Request Schema (validiert von Pydantic)
        
    Returns:
        SearchResponse mit gefundenen Matches
    """
    logger.info(f"POST /api/networks/search - nodes={len(search.node_labels)}")
    try:
        # CRUD gibt Domain Models zurück
        matches: List[SearchMatch] = crud.search_subgraph(
            query_matrix=search.adjacency_matrix,
            query_labels=search.node_labels
        )
        
        # Konvertiere zu Response Schemas
        response_data = [search_match_to_response(m) for m in matches]
        
        logger.info(f"POST /api/networks/search - Found {len(response_data)} matches")
        return SearchResponse(success=True, data=response_data)
        
    except Exception as e:
        logger.error(f"POST /api/networks/search - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(
    "/api/networks/{network_id}",
    tags=["Networks"],
    response_model=DeleteResponse,
    summary="Delete Network",
    description="Deletes a network from the database"
)
async def delete_network(network_id: int) -> DeleteResponse:
    """
    Löscht Netzwerk aus der Datenbank
    
    Args:
        network_id: ID des zu löschenden Netzwerks
        
    Returns:
        DeleteResponse mit Status
    """
    logger.info(f"DELETE /api/networks/{network_id}")
    try:
        # CRUD löscht und gibt boolean zurück
        deleted: bool = crud.delete_network(network_id)
        
        if not deleted:
            logger.warning(f"DELETE /api/networks/{network_id} - Not found")
            raise HTTPException(status_code=404, detail="Network not found")
        
        logger.info(f"DELETE /api/networks/{network_id} - Deleted successfully")
        return DeleteResponse(success=True, message="Network deleted")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DELETE /api/networks/{network_id} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------------
# Multi-Omics Endpoints
# ----------------------------------------------------------------------------

@app.post(
    "/api/multiomics",
    tags=["Multi-Omics"],
    response_model=MultiOmicsCreationWrapper,
    summary="Create Multi-Omics Network",
    description="Creates a network with several layers (e.g. transcriptome, proteome) over the same nodes"
)
async def create_multiomics_network(network: MultiOmicsCreate) -> MultiOmicsCreationWrapper:
    """
    Erstellt ein Multi-Omics-Netzwerk

    Args:
        network: Request Schema (validiert von Pydantic)

    Returns:
        MultiOmicsCreationWrapper mit den Details des erstellten Netzwerks
    """
    logger.info(
        f"POST /api/multiomics - name={network.name} "
        f"organism={network.organism} layers={len(network.layers)}"
    )
    try:
        result: MultiOmicsCreationResult = crud.create_multiomics_network(
            name=network.name,
            network_type=network.network_type,
            organism=network.organism,
            description=network.description or "",
            node_labels=network.node_labels,
            layer_names=[layer.layer_name for layer in network.layers],
            layer_matrices=[layer.adjacency_matrix for layer in network.layers]
        )

        logger.info(f"POST /api/multiomics - Created network_id={result.network_id}")
        return MultiOmicsCreationWrapper(success=True, data=multiomics_creation_to_response(result))

    except ValueError as e:
        logger.warning(f"POST /api/multiomics - Invalid input: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"POST /api/multiomics - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/multiomics/search",
    tags=["Multi-Omics"],
    response_model=MultiOmicsSearchResponse,
    summary="Search Multi-Omics Subgraph",
    description="Searches for multi-omics networks containing the query in all given layers"
)
async def search_multiomics(search: MultiOmicsSearch) -> MultiOmicsSearchResponse:
    """
    Sucht Multi-Omics-Netzwerke, die die Query in allen genannten Schichten enthalten

    Args:
        search: Request Schema (validiert von Pydantic)

    Returns:
        MultiOmicsSearchResponse mit gefundenen Matches
    """
    logger.info(
        f"POST /api/multiomics/search - nodes={len(search.node_labels)} "
        f"layers={len(search.layers)} mode={search.mode}"
    )
    try:
        matches: List[MultiOmicsSearchMatch] = crud.search_multiomics(
            layer_names=[layer.layer_name for layer in search.layers],
            layer_matrices=[layer.adjacency_matrix for layer in search.layers],
            query_labels=search.node_labels,
            mode=search.mode
        )

        response_data = [multiomics_match_to_response(m) for m in matches]

        logger.info(f"POST /api/multiomics/search - Found {len(response_data)} matches")
        return MultiOmicsSearchResponse(success=True, data=response_data)

    except ValueError as e:
        logger.warning(f"POST /api/multiomics/search - Invalid input: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"POST /api/multiomics/search - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/multiomics/{network_id}",
    tags=["Multi-Omics"],
    response_model=MultiOmicsSingleResponse,
    summary="Get Multi-Omics Network by ID",
    description="Retrieves a multi-omics network with all layers"
)
async def get_multiomics_network(network_id: int) -> MultiOmicsSingleResponse:
    """
    Hole ein Multi-Omics-Netzwerk mit allen Schichten

    Args:
        network_id: ID des gesuchten Netzwerks

    Returns:
        MultiOmicsSingleResponse mit vollständigem Netzwerk
    """
    logger.info(f"GET /api/multiomics/{network_id}")
    try:
        network = crud.get_multiomics_network_by_id(network_id)

        if not network:
            logger.warning(f"GET /api/multiomics/{network_id} - Not found")
            raise HTTPException(status_code=404, detail="Multi-omics network not found")

        logger.info(f"GET /api/multiomics/{network_id} - Found: {network.name}")
        return MultiOmicsSingleResponse(success=True, data=multiomics_network_to_response(network))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/multiomics/{network_id} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/health",
    tags=["Health"],
    response_model=HealthResponse,
    summary="Health Check",
    description="Check if the API and database are running"
)
async def health_check() -> HealthResponse:
    """
    Health Check Endpoint
    
    Returns:
        HealthResponse mit Status
    """
    logger.info("GET /api/health")
    return HealthResponse(status="healthy", database="connected")


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    config = get_config()
    uvicorn.run(
        app,
        host=config.api_host,
        port=config.api_port
    )
