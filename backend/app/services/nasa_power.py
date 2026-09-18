"""NASA POWER wind climatology acquisition for the Sindh Wind Corridor."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import geopandas as gpd
import httpx
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from scipy.interpolate import griddata
from shapely.geometry import Point

from app.core.config import get_settings
from app.gis.proj_env import configure_proj
from app.gis.study_area import get_study_area_boundary

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RAW_GRID_PATH = BACKEND_ROOT / "data" / "raw" / "nasa_power_wind_grid.geojson"
WIND_RASTER_PATH = BACKEND_ROOT / "data" / "processed" / "wind_speed_raster.tif"

FILL_VALUE = -999.0
AIR_DENSITY_KG_M3 = 1.225
NODATA = -9999.0
DEFAULT_SPACING_DEG = 0.25
DEFAULT_DELAY_S = 0.35
MAX_RETRIES = 3
USER_AGENT = "wind-suitability-platform/0.1 (Sindh Wind Corridor research)"


class NasaPowerError(Exception):
    """NASA POWER request or wind-pipeline failure (maps to HTTP 502)."""


def acquire_wind_data(
    *,
    spacing_deg: float = DEFAULT_SPACING_DEG,
    delay_s: float = DEFAULT_DELAY_S,
    grid_path: Path | None = None,
    raster_path: Path | None = None,
) -> dict:
    """Sample NASA POWER climatology on a grid and interpolate a wind raster.

    Wind speeds at 10 m and 50 m come from the climatology API (WS10M, WS50M).
    Wind power density is not a POWER parameter; it is computed as
    ``0.5 * 1.225 * WS50M^3`` (W/m²).
    """
    grid_path = grid_path or RAW_GRID_PATH
    raster_path = raster_path or WIND_RASTER_PATH
    configure_proj()

    boundary = get_study_area_boundary()
    coords = _grid_points(boundary, spacing_deg)
    if not coords:
        raise NasaPowerError(
            f"No sample points inside the study area at spacing={spacing_deg}°"
        )

    logger.info("Querying NASA POWER climatology for %s grid points", len(coords))
    records = _fetch_points(coords, delay_s=delay_s)
    if len(records) < 3:
        raise NasaPowerError(
            f"NASA POWER returned usable wind values for only {len(records)} "
            "points; need at least 3 to interpolate a raster"
        )

    gdf = _records_to_gdf(records)
    grid_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(grid_path, driver="GeoJSON")
    logger.info("Wrote wind point grid to %s (%s points)", grid_path, len(gdf))

    _interpolate_wind_raster(gdf, boundary, raster_path)
    logger.info("Wrote wind-speed raster to %s", raster_path)

    speeds = gdf["wind_speed_50m"]
    return {
        "point_count": int(len(gdf)),
        "wind_speed_min": float(speeds.min()),
        "wind_speed_max": float(speeds.max()),
        "wind_speed_mean": float(speeds.mean()),
        "wind_speed_height_m": 50,
        "grid_path": str(grid_path),
        "raster_path": str(raster_path),
    }


def _grid_points(boundary: gpd.GeoDataFrame, spacing_deg: float) -> list[tuple[float, float]]:
    polygon = boundary.union_all()
    minx, miny, maxx, maxy = boundary.total_bounds
    xs = np.arange(minx, maxx + spacing_deg / 2, spacing_deg)
    ys = np.arange(miny, maxy + spacing_deg / 2, spacing_deg)
    points: list[tuple[float, float]] = []
    for x in xs:
        for y in ys:
            if polygon.covers(Point(float(x), float(y))):
                points.append((round(float(x), 6), round(float(y), 6)))
    return points


def _fetch_points(
    coords: list[tuple[float, float]],
    *,
    delay_s: float,
) -> list[dict]:
    settings = get_settings()
    base = settings.NASA_POWER_BASE_URL.rstrip("/")
    url = f"{base}/api/temporal/climatology/point"
    records: list[dict] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    try:
        with httpx.Client(timeout=60.0, headers=headers) as client:
            for i, (lon, lat) in enumerate(coords):
                record = _query_climatology(client, url, lon, lat)
                if record is not None:
                    records.append(record)
                if i < len(coords) - 1 and delay_s > 0:
                    time.sleep(delay_s)
    except httpx.HTTPError as exc:
        logger.exception("NASA POWER is unreachable")
        raise NasaPowerError(f"NASA POWER is unreachable: {exc}") from exc

    return records


def _query_climatology(
    client: httpx.Client,
    url: str,
    lon: float,
    lat: float,
) -> dict | None:
    params = {
        "parameters": "WS10M,WS50M",
        "community": "RE",
        "longitude": lon,
        "latitude": lat,
        "format": "JSON",
    }
    last_error = "unknown error"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            logger.warning(
                "NASA POWER request failed at (%s, %s) attempt %s: %s",
                lon,
                lat,
                attempt,
                exc,
            )
            time.sleep(2 ** (attempt - 1))
            continue

        if response.status_code == 429:
            last_error = "rate limited (HTTP 429)"
            wait = 2 ** attempt
            logger.warning("NASA POWER rate-limited; sleeping %ss", wait)
            time.sleep(wait)
            continue

        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            logger.warning(
                "NASA POWER server error %s at (%s, %s) attempt %s",
                response.status_code,
                lon,
                lat,
                attempt,
            )
            time.sleep(2 ** (attempt - 1))
            continue

        if not response.is_success:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error("NASA POWER rejected (%s, %s): %s", lon, lat, last_error)
            return None

        try:
            return _parse_climatology(response.json(), lon, lat)
        except (KeyError, TypeError, ValueError) as exc:
            last_error = f"unexpected payload: {exc}"
            logger.error("Could not parse NASA POWER response at (%s, %s): %s", lon, lat, exc)
            return None

    logger.error(
        "Giving up on NASA POWER point (%s, %s) after %s attempts: %s",
        lon,
        lat,
        MAX_RETRIES,
        last_error,
    )
    return None


def _parse_climatology(payload: dict, lon: float, lat: float) -> dict | None:
    parameters = payload["properties"]["parameter"]
    ws10 = _annual_value(parameters["WS10M"])
    ws50 = _annual_value(parameters["WS50M"])
    if ws10 is None or ws50 is None:
        logger.warning("NASA POWER fill value at (%s, %s); skipping", lon, lat)
        return None
    return {
        "longitude": lon,
        "latitude": lat,
        "wind_speed_10m": ws10,
        "wind_speed_50m": ws50,
        "wind_power_density": wind_power_density(ws50),
    }


def _annual_value(series: dict) -> float | None:
    raw = series.get("ANN")
    if raw is None:
        months = [series[k] for k in series if k != "ANN" and series[k] != FILL_VALUE]
        if not months:
            return None
        raw = float(np.mean(months))
    value = float(raw)
    if value == FILL_VALUE or np.isnan(value):
        return None
    return value


def wind_power_density(wind_speed_ms: float, air_density: float = AIR_DENSITY_KG_M3) -> float:
    """Mean wind power density (W/m²) from speed: ½ ρ v³."""
    return float(0.5 * air_density * wind_speed_ms**3)


def _records_to_gdf(records: list[dict]) -> gpd.GeoDataFrame:
    gdf = gpd.GeoDataFrame(
        records,
        geometry=[Point(r["longitude"], r["latitude"]) for r in records],
        crs="EPSG:4326",
    )
    return gdf[
        [
            "latitude",
            "longitude",
            "wind_speed_10m",
            "wind_speed_50m",
            "wind_power_density",
            "geometry",
        ]
    ]


def _interpolate_wind_raster(
    gdf: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    raster_path: Path,
    *,
    pixel_size: float = 0.05,
) -> None:
    configure_proj()
    minx, miny, maxx, maxy = boundary.total_bounds
    width = max(int(np.ceil((maxx - minx) / pixel_size)), 2)
    height = max(int(np.ceil((maxy - miny) / pixel_size)), 2)
    transform = from_origin(minx, maxy, pixel_size, pixel_size)

    xs = minx + (np.arange(width) + 0.5) * pixel_size
    ys = maxy - (np.arange(height) + 0.5) * pixel_size
    grid_x, grid_y = np.meshgrid(xs, ys)

    points = np.column_stack([gdf.geometry.x, gdf.geometry.y])
    values = gdf["wind_speed_50m"].to_numpy(dtype=float)
    linear = griddata(points, values, (grid_x, grid_y), method="linear")
    nearest = griddata(points, values, (grid_x, grid_y), method="nearest")
    grid = np.where(np.isnan(linear), nearest, linear)

    inside = geometry_mask(
        [boundary.union_all()],
        out_shape=(height, width),
        transform=transform,
        invert=True,
    )
    grid = np.where(inside, grid, NODATA).astype("float32")

    raster_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.Env():
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
            nodata=NODATA,
        ) as dst:
            dst.write(grid, 1)
            dst.update_tags(
                source="NASA POWER climatology WS50M (ANN, 2001-2020)",
                units="m/s",
            )
