"""OpenStreetMap roads and power grid for the Sindh Wind Corridor."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import httpx
import osmnx as ox
import pandas as pd
from osmnx._errors import InsufficientResponseError
from shapely.geometry import MultiPolygon, Polygon

from app.core.config import get_settings
from app.gis.proj_env import configure_proj
from app.gis.study_area import get_study_area_boundary

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BACKEND_ROOT / "data" / "processed"
ROAD_WGS84_PATH = PROCESSED_DIR / "road_network.geojson"
ROAD_UTM_PATH = PROCESSED_DIR / "road_network_utm32642.geojson"
GRID_WGS84_PATH = PROCESSED_DIR / "grid_lines.geojson"
GRID_UTM_PATH = PROCESSED_DIR / "grid_lines_utm32642.geojson"

UTM_CRS = "EPSG:32642"  # WGS 84 / UTM zone 42N (thesis methodology)
POWER_TAGS = {"power": ["line", "substation", "tower"]}
# kumi is the only public planet instance that currently answers OSMnx queries
# from this host. overpass-api.de 429s; osm.fr 403s OSMnx; osm.ch is regional.
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api",
    "https://overpass-api.de/api",
]


class InfrastructureError(Exception):
    """OSM/OSMnx infrastructure download failure (maps to HTTP 502)."""


def acquire_infrastructure(
    *,
    force: bool = False,
    road_path: Path | None = None,
    grid_path: Path | None = None,
    road_utm_path: Path | None = None,
    grid_utm_path: Path | None = None,
) -> dict:
    """Download drivable roads and OSM power features, save WGS84 + UTM 42N."""
    configure_proj()
    road_path = road_path or ROAD_WGS84_PATH
    grid_path = grid_path or GRID_WGS84_PATH
    road_utm_path = road_utm_path or ROAD_UTM_PATH
    grid_utm_path = grid_utm_path or GRID_UTM_PATH

    boundary = get_study_area_boundary()
    roads = _load_or_download(
        label="road network",
        path=road_path,
        force=force,
        fetch=lambda: get_road_network(boundary),
        wgs_path=road_path,
        utm_path=road_utm_path,
    )
    grid = _load_or_download(
        label="power grid",
        path=grid_path,
        force=force,
        fetch=lambda: get_grid_transmission_lines(boundary),
        wgs_path=grid_path,
        utm_path=grid_utm_path,
    )

    summary = _summarize(roads, grid)
    summary.update(
        {
            "road_path": str(road_path),
            "road_utm_path": str(road_utm_path),
            "grid_path": str(grid_path),
            "grid_utm_path": str(grid_utm_path),
        }
    )
    logger.info(
        "Infrastructure ready: %.1f km roads, %s substations, %s towers",
        summary["road_length_km"],
        summary["substation_count"],
        summary["tower_count"],
    )
    return summary


def get_road_network(study_area_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Download the drivable OSM road network inside the study-area polygon.

    Uses ``ox.graph_from_polygon(..., network_type='drive')`` then
    ``ox.graph_to_gdfs`` for edges, matching the Tkinter prototype pattern
    (``graph_from_place(..., network_type='drive')``) but covering both
    Thatta and Badin instead of a single city name.
    """
    polygon = _as_polygon(study_area_gdf)
    try:
        graph = ox.graph_from_polygon(polygon, network_type="drive", simplify=True)
    except Exception as exc:
        raise InfrastructureError(f"OSMnx could not download the drive network: {exc}") from exc

    edges = ox.graph_to_gdfs(graph, nodes=False, edges=True, fill_edge_geometry=True)
    edges = edges.reset_index()
    if edges.crs is None:
        edges = edges.set_crs("EPSG:4326")
    return _json_safe(edges)


def get_grid_transmission_lines(study_area_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Download OSM power=line, power=substation, and power=tower features."""
    polygon = _as_polygon(study_area_gdf)
    try:
        grid = ox.features_from_polygon(polygon, POWER_TAGS)
    except Exception as exc:
        if isinstance(exc, InsufficientResponseError) or "no data" in str(exc).lower() or "insufficient" in str(exc).lower():
            logger.warning("No OSM power features in the study area: %s", exc)
            return gpd.GeoDataFrame(columns=["power", "geometry"], crs="EPSG:4326")
        raise InfrastructureError(f"OSMnx could not download power infrastructure: {exc}") from exc

    grid = grid.reset_index()
    if grid.crs is None:
        grid = grid.set_crs("EPSG:4326")
    preferred = ["osmid", "id", "element", "power", "voltage", "name", "operator", "geometry"]
    keep = [col for col in preferred if col in grid.columns]
    if "geometry" not in keep:
        keep.append("geometry")
    return _json_safe(grid[keep])


def _as_polygon(study_area_gdf: gpd.GeoDataFrame) -> Polygon | MultiPolygon:
    if study_area_gdf.crs is None:
        study_area_gdf = study_area_gdf.set_crs("EPSG:4326")
    elif study_area_gdf.crs.to_epsg() != 4326:
        study_area_gdf = study_area_gdf.to_crs("EPSG:4326")
    geom = study_area_gdf.union_all()
    if geom.is_empty:
        raise InfrastructureError("Study-area polygon is empty")
    if not isinstance(geom, (Polygon, MultiPolygon)):
        geom = geom.convex_hull
    return geom


def _overpass_urls() -> list[str]:
    configured = get_settings().OSM_OVERPASS_URL.rstrip("/")
    if configured.endswith("/interpreter"):
        configured = configured[: -len("/interpreter")]
    urls: list[str] = []
    if configured and "overpass-api.de" not in configured:
        urls.append(configured)
    for mirror in OVERPASS_MIRRORS:
        if mirror not in urls:
            urls.append(mirror)
    if configured and configured not in urls:
        urls.append(configured)
    return urls


def _configure_osmnx(overpass_url: str | None = None) -> None:
    _prefer_ipv4()
    ox.settings.http_user_agent = (
        "wind-suitability-platform/0.1 (Sindh Wind Corridor research)"
    )
    ox.settings.http_referer = "https://localhost/wind-suitability-platform"
    ox.settings.requests_timeout = 300
    ox.settings.use_cache = True
    ox.settings.overpass_rate_limit = False
    ox.settings.log_console = True
    ox.settings.cache_folder = str(BACKEND_ROOT / "data" / "raw" / "osmnx_cache")
    # ~1000 km² tiles: kumi returned 504 on ~50 km quadrats in this corridor.
    ox.settings.max_query_area_size = 1_000_000_000
    _install_httpx_overpass_transport()
    _disable_osmnx_dns_pinning()
    if overpass_url:
        ox.settings.overpass_url = overpass_url


def _prefer_ipv4() -> None:
    """Windows often stalls on IPv6 to Overpass; pin urllib3 to IPv4."""
    try:
        import urllib3.util.connection as urllib3_cn

        urllib3_cn.HAS_IPV6 = False
    except Exception:
        logger.debug("Could not disable IPv6 for urllib3", exc_info=True)


def _install_httpx_overpass_transport() -> None:
    """Route OSMnx Overpass POSTs through httpx (requests connect-timeouts on this host)."""
    import requests as requests_lib

    if getattr(requests_lib.post, "_wind_httpx", False):
        return

    def _httpx_post(url, data=None, json=None, timeout=180, headers=None, **kwargs):
        timeout_s = getattr(timeout, "total", None) or timeout or 180
        with httpx.Client(timeout=float(timeout_s), follow_redirects=True, headers=headers) as client:
            response = client.post(url, data=data, json=json)
        return _HttpxResponse(response)

    _httpx_post._wind_httpx = True  # type: ignore[attr-defined]
    requests_lib.post = _httpx_post  # type: ignore[assignment]


def _disable_osmnx_dns_pinning() -> None:
    """OSMnx pins Overpass to one backend IP; that host is often unreachable here."""
    import socket

    import osmnx._http as ox_http

    ox_http._config_dns = lambda url: None  # type: ignore[assignment]
    socket.getaddrinfo = ox_http._original_getaddrinfo


class _HttpxResponse:
    def __init__(self, response: httpx.Response) -> None:
        self.status_code = response.status_code
        self.ok = response.is_success
        self.reason = response.reason_phrase
        self.text = response.text
        self.content = response.content
        self.url = str(response.url)

    def json(self):
        return json.loads(self.text)


def _load_or_download(
    *,
    label: str,
    path: Path,
    force: bool,
    fetch,
    wgs_path: Path,
    utm_path: Path,
) -> gpd.GeoDataFrame:
    if not force and path.exists():
        logger.info("Loading cached %s from %s", label, path)
        return gpd.read_file(path)
    gdf = _with_overpass_failover(label, fetch)
    _write_geojson_pair(gdf, wgs_path, utm_path)
    return gdf


def _with_overpass_failover(label: str, fetch):
    last_error: Exception | None = None
    for overpass_url in _overpass_urls():
        try:
            _configure_osmnx(overpass_url)
            logger.info("Downloading %s via %s", label, overpass_url)
            return fetch()
        except Exception as exc:
            last_error = exc
            logger.warning("Overpass %s failed for %s: %s", overpass_url, label, exc)
    if last_error is None:
        raise InfrastructureError(f"No Overpass mirrors configured for {label}")
    if isinstance(last_error, InfrastructureError):
        raise last_error
    raise InfrastructureError(str(last_error)) from last_error


def _write_geojson_pair(gdf: gpd.GeoDataFrame, wgs_path: Path, utm_path: Path) -> None:
    wgs_path.parent.mkdir(parents=True, exist_ok=True)
    utm_path.parent.mkdir(parents=True, exist_ok=True)
    wgs = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
    if wgs.crs is None:
        wgs = wgs.set_crs("EPSG:4326")
    _write_geojson(wgs, wgs_path)
    _write_geojson(wgs.to_crs(UTM_CRS), utm_path)
    logger.info("Wrote %s features to %s and %s", len(gdf), wgs_path.name, utm_path.name)


def _write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    """Write GeoJSON; fall back to to_json() if mixed geometry types fail."""
    try:
        gdf.to_file(path, driver="GeoJSON")
    except Exception as exc:
        logger.warning("GeoJSON driver failed (%s); writing via GeoDataFrame.to_json()", exc)
        path.write_text(gdf.to_json(), encoding="utf-8")


def _summarize(roads: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> dict:
    road_length_km = 0.0
    if not roads.empty and roads.geometry.notna().any():
        meters = roads.set_crs("EPSG:4326") if roads.crs is None else roads
        meters = meters.to_crs(UTM_CRS)
        road_length_km = float(meters.geometry.length.sum() / 1000.0)

    power = _power_values(grid)
    substations = int(power.eq("substation").sum()) if len(power) else 0
    towers = int(power.eq("tower").sum()) if len(power) else 0
    lines = int(power.eq("line").sum()) if len(power) else 0
    return {
        "road_edge_count": int(len(roads)),
        "road_length_km": round(road_length_km, 2),
        "grid_feature_count": int(len(grid)),
        "substation_count": substations,
        "tower_count": towers,
        "power_line_count": lines,
        "crs_wgs84": "EPSG:4326",
        "crs_projected": UTM_CRS,
    }


def _power_values(grid: gpd.GeoDataFrame) -> pd.Series:
    if grid.empty or "power" not in grid.columns:
        return pd.Series(dtype="object")
    return grid["power"].astype(str).str.lower()


def _json_safe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """GeoJSON cannot store list/dict OSM tags; stringify them."""
    out = gdf.copy()
    for col in out.columns:
        if col == "geometry":
            continue
        out[col] = out[col].map(_as_json_value)
    return out


def _as_json_value(value):
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (list, dict, tuple, set)):
        return json.dumps(value, default=str)
    return value
