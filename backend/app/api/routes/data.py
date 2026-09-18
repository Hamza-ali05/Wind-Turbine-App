import json
import logging

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.gis.study_area import get_study_area_boundary
from app.models.schemas import (
    InfrastructureAcquireSummary,
    LandCoverAcquireSummary,
    TerrainAcquireSummary,
    WindAcquireSummary,
)
from app.services import not_implemented
from app.services.elevation import TerrainError, acquire_terrain
from app.services.infrastructure import InfrastructureError, acquire_infrastructure
from app.services.land_cover import LandCoverError, acquire_land_cover
from app.services.nasa_power import NasaPowerError, acquire_wind_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/acquire")
def acquire_data() -> dict:
    """Trigger source data acquisition (NASA POWER, elevation, land cover, OSM)."""
    return not_implemented("data_acquisition")


@router.get("/status")
def data_status() -> dict:
    return not_implemented("data_status", layers=[])


@router.get("/study-area")
def study_area() -> JSONResponse:
    """Return the Sindh Wind Corridor (Thatta + Badin) boundary as GeoJSON.

    Generated on first call via OSMnx and cached to
    ``data/processed/study_area_boundary.geojson``.
    """
    try:
        gdf = get_study_area_boundary()
    except Exception as exc:
        logger.exception("Failed to load study-area boundary")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not load study-area boundary: {exc}",
        ) from exc
    return JSONResponse(
        content=json.loads(gdf.to_json()),
        media_type="application/geo+json",
    )


@router.post("/wind", response_model=WindAcquireSummary)
def acquire_wind(
    spacing_deg: float = Query(0.25, gt=0.05, le=2.0),
) -> WindAcquireSummary:
    """Download NASA POWER wind climatology, write a point grid and interpolated raster."""
    try:
        summary = acquire_wind_data(spacing_deg=spacing_deg)
    except NasaPowerError as exc:
        logger.exception("NASA POWER wind acquisition failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return WindAcquireSummary(**summary)


@router.post("/terrain", response_model=TerrainAcquireSummary)
def acquire_terrain_data(force: bool = Query(False)) -> TerrainAcquireSummary:
    """Download SRTM elevation and derive slope and terrain-roughness rasters."""
    try:
        summary = acquire_terrain(force=force)
    except TerrainError as exc:
        logger.exception("Terrain acquisition failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return TerrainAcquireSummary(**summary)


@router.post("/land-cover", response_model=LandCoverAcquireSummary)
def acquire_land_cover_data(force: bool = Query(False)) -> LandCoverAcquireSummary:
    """Download ESA Copernicus/WorldCover land cover and reclassify for wind siting."""
    try:
        summary = acquire_land_cover(force=force)
    except LandCoverError as exc:
        logger.exception("Land-cover acquisition failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return LandCoverAcquireSummary(**summary)


@router.post("/infrastructure", response_model=InfrastructureAcquireSummary)
def acquire_infrastructure_data(force: bool = Query(False)) -> InfrastructureAcquireSummary:
    """Download OSM roads and power grid, save WGS84 and UTM Zone 42N GeoJSON."""
    try:
        summary = acquire_infrastructure(force=force)
    except InfrastructureError as exc:
        logger.exception("Infrastructure acquisition failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return InfrastructureAcquireSummary(**summary)
