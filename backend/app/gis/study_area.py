"""Sindh Wind Corridor study-area boundary (Thatta + Badin districts)."""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import osmnx as ox

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BACKEND_ROOT / "data" / "processed"
BOUNDARY_PATH = PROCESSED_DIR / "study_area_boundary.geojson"

THATTA_QUERY = "Thatta District, Sindh, Pakistan"
BADIN_QUERY = "Badin District, Sindh, Pakistan"


def get_study_area_boundary(*, cache_path: Path | None = None) -> gpd.GeoDataFrame:
    """Return the study area as a single-polygon GeoDataFrame in EPSG:4326.

    The corridor is the union of Thatta and Badin districts: north of the
    Arabian Sea / Keti Bandar, covering Jhimpir / Keenjhar Lake, from the
    Rann of Kutch border to the eastern fringes of Karachi.

    The first call fetches OSM administrative boundaries via OSMnx and writes
    ``data/processed/study_area_boundary.geojson``. Later calls load that file.
    """
    path = cache_path if cache_path is not None else BOUNDARY_PATH
    if path.exists():
        logger.info("Loading cached study-area boundary from %s", path)
        gdf = gpd.read_file(path)
        return _as_wgs84(gdf)

    logger.info("Fetching Thatta and Badin district boundaries from Nominatim")
    gdf = _fetch_and_union_districts()
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")
    logger.info("Wrote study-area boundary to %s", path)
    return gdf


def _fetch_and_union_districts() -> gpd.GeoDataFrame:
    ox.settings.http_user_agent = (
        "wind-suitability-platform/0.1 (Sindh Wind Corridor research)"
    )
    districts = ox.geocode_to_gdf([THATTA_QUERY, BADIN_QUERY])
    if districts.empty or districts.geometry.isna().all():
        raise RuntimeError("Nominatim returned no polygon for Thatta/Badin districts")

    districts = _as_wgs84(districts)
    unioned = gpd.GeoDataFrame(
        {
            "name": ["Sindh Wind Corridor"],
            "districts": ["Thatta District, Badin District"],
        },
        geometry=[districts.union_all()],
        crs="EPSG:4326",
    )
    if unioned.geometry.isna().any() or unioned.is_empty.any():
        raise RuntimeError("Failed to union Thatta and Badin district polygons")
    return unioned


def _as_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf
