"""SRTM elevation, slope, and terrain-roughness for the Sindh Wind Corridor."""

from __future__ import annotations

import gzip
import logging
import math
import tempfile
from pathlib import Path

import geopandas as gpd
import httpx
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.transform import Affine, from_origin
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds as window_from_bounds
from rasterio.windows import transform as window_transform

from app.core.config import get_settings
from app.gis.proj_env import configure_proj
from app.gis.study_area import get_study_area_boundary

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RAW_DEM_PATH = BACKEND_ROOT / "data" / "raw" / "dem_srtm.tif"
SLOPE_PATH = BACKEND_ROOT / "data" / "processed" / "slope.tif"
ROUGHNESS_PATH = BACKEND_ROOT / "data" / "processed" / "terrain_roughness.tif"
SKADI_CACHE = BACKEND_ROOT / "data" / "raw" / "srtm_skadi"

SRTM_NODATA = -32768
OUT_NODATA = -9999.0
PIXEL_DEG = 1.0 / 3600.0  # SRTM GL1 / 30 m
AWS_SKADI = "https://s3.amazonaws.com/elevation-tiles-prod/skadi"
OPENTOPO_URL = "https://portal.opentopography.org/API/globaldem"
USER_AGENT = "wind-suitability-platform/0.1 (Sindh Wind Corridor research)"
BUFFER_DEG = 0.02


class TerrainError(Exception):
    """DEM download or terrain-pipeline failure (maps to HTTP 502)."""


def acquire_terrain(
    *,
    dem_path: Path | None = None,
    slope_path: Path | None = None,
    roughness_path: Path | None = None,
    force: bool = False,
) -> dict:
    """Download a DEM, then map elevation, slope, and terrain roughness."""
    configure_proj()
    dem_path = dem_path or RAW_DEM_PATH
    slope_path = slope_path or SLOPE_PATH
    roughness_path = roughness_path or ROUGHNESS_PATH

    boundary = get_study_area_boundary()
    west, south, east, north = _buffered_bounds(boundary)

    source = "cached"
    if force or not dem_path.exists():
        source = _download_dem(west, south, east, north, dem_path)

    elevation, slope, roughness, transform, crs = _derive_terrain(dem_path, boundary)
    _write_float_raster(slope_path, slope, transform, crs)
    _write_float_raster(roughness_path, roughness, transform, crs)

    elev_stats = _masked_stats(elevation)
    slope_stats = _masked_stats(slope)
    logger.info(
        "Terrain ready source=%s elev=%.1f–%.1f m slope=%.2f–%.2f deg",
        source,
        elev_stats["min"],
        elev_stats["max"],
        slope_stats["min"],
        slope_stats["max"],
    )
    return {
        "elevation_min": elev_stats["min"],
        "elevation_max": elev_stats["max"],
        "elevation_mean": elev_stats["mean"],
        "slope_min": slope_stats["min"],
        "slope_max": slope_stats["max"],
        "slope_mean": slope_stats["mean"],
        "dem_path": str(dem_path),
        "slope_path": str(slope_path),
        "roughness_path": str(roughness_path),
        "source": source,
    }


def _buffered_bounds(boundary: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    west, south, east, north = boundary.total_bounds
    return (
        float(west - BUFFER_DEG),
        float(south - BUFFER_DEG),
        float(east + BUFFER_DEG),
        float(north + BUFFER_DEG),
    )


def _download_dem(west: float, south: float, east: float, north: float, dem_path: Path) -> str:
    errors: list[str] = []

    try:
        _download_with_elevation_package(west, south, east, north, dem_path)
        logger.info("DEM downloaded with the elevation package")
        return "elevation"
    except Exception as exc:
        errors.append(f"elevation package: {exc}")
        logger.warning("elevation package failed: %s", exc)

    settings = get_settings()
    if settings.OPENTOPOGRAPHY_API_KEY:
        try:
            _download_opentopography(west, south, east, north, dem_path, settings.OPENTOPOGRAPHY_API_KEY)
            logger.info("DEM downloaded from OpenTopography SRTMGL1")
            return "opentopography"
        except Exception as exc:
            errors.append(f"OpenTopography: {exc}")
            logger.warning("OpenTopography download failed: %s", exc)
    else:
        errors.append("OpenTopography: OPENTOPOGRAPHY_API_KEY is not set")
        logger.warning("Skipping OpenTopography (no API key)")

    try:
        _download_aws_srtm(west, south, east, north, dem_path)
        logger.info("DEM downloaded from AWS SRTM GL1 (skadi) tiles")
        return "aws_srtm"
    except Exception as exc:
        errors.append(f"AWS SRTM tiles: {exc}")
        logger.warning("AWS SRTM download failed: %s", exc)

    raise TerrainError(
        "Could not download a DEM covering the study area. " + " | ".join(errors)
    )


def _download_with_elevation_package(
    west: float, south: float, east: float, north: float, dem_path: Path
) -> None:
    import shutil

    try:
        import elevation  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Python package 'elevation' is not installed") from exc

    if shutil.which("gdalwarp") is None and shutil.which("gdal_translate") is None:
        raise RuntimeError("GDAL command-line tools are not on PATH (needed by elevation.clip)")

    dem_path.parent.mkdir(parents=True, exist_ok=True)
    elevation.clip(bounds=(west, south, east, north), output=str(dem_path), product="SRTM1")
    if not dem_path.exists():
        raise RuntimeError("elevation.clip finished but wrote no file")


def _download_opentopography(
    west: float,
    south: float,
    east: float,
    north: float,
    dem_path: Path,
    api_key: str,
) -> None:
    dem_path.parent.mkdir(parents=True, exist_ok=True)
    params = {
        "demtype": "SRTMGL1",
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=300.0, headers=headers, follow_redirects=True) as client:
        with client.stream("GET", OPENTOPO_URL, params=params) as response:
            if response.status_code == 429:
                raise TerrainError("OpenTopography rate-limited the request (HTTP 429)")
            if response.status_code >= 400:
                body = response.read()[:300].decode("utf-8", errors="replace")
                raise TerrainError(f"OpenTopography HTTP {response.status_code}: {body}")
            content_type = response.headers.get("content-type", "")
            if "html" in content_type.lower():
                raise TerrainError("OpenTopography returned HTML instead of a GeoTIFF")
            with dem_path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)


def _download_aws_srtm(
    west: float, south: float, east: float, north: float, dem_path: Path
) -> None:
    """Fetch SRTM GL1 1° tiles from the same AWS Skadi source the elevation package uses."""
    tiles = list(_srtm_tiles(west, south, east, north))
    if not tiles:
        raise TerrainError("Study-area bounds did not intersect any SRTM tile")

    arrays: list[np.ndarray] = []
    transforms: list[Affine] = []
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=120.0, headers=headers, follow_redirects=True) as client:
        for lat0, lon0 in tiles:
            array, transform = _fetch_skadi_tile(client, lat0, lon0, west, south, east, north)
            arrays.append(array)
            transforms.append(transform)

    mosaic, mosaic_transform = _mosaic(arrays, transforms)
    dem_path.parent.mkdir(parents=True, exist_ok=True)
    _write_float_raster(dem_path, mosaic.astype("float32"), mosaic_transform, "EPSG:4326")


def _srtm_tiles(west: float, south: float, east: float, north: float) -> list[tuple[int, int]]:
    lon_start = math.floor(west)
    lon_end = math.floor(east) if east != math.floor(east) else math.floor(east) - 1
    lat_start = math.floor(south)
    lat_end = math.floor(north) if north != math.floor(north) else math.floor(north) - 1
    tiles = []
    for lat in range(int(lat_start), int(lat_end) + 1):
        for lon in range(int(lon_start), int(lon_end) + 1):
            tiles.append((lat, lon))
    return tiles


def _skadi_name(lat0: int, lon0: int) -> str:
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


def _skadi_url(lat0: int, lon0: int) -> str:
    name = _skadi_name(lat0, lon0)
    folder = name[:3]
    return f"{AWS_SKADI}/{folder}/{name}.hgt.gz"


def _fetch_skadi_tile(
    client: httpx.Client,
    lat0: int,
    lon0: int,
    west: float,
    south: float,
    east: float,
    north: float,
) -> tuple[np.ndarray, Affine]:
    url = _skadi_url(lat0, lon0)
    cache_path = SKADI_CACHE / f"{_skadi_name(lat0, lon0)}.hgt.gz"
    if cache_path.exists():
        array = _hgt_to_array(cache_path.read_bytes(), lat0, lon0)
        return _clip_array(array, lat0, lon0, west, south, east, north)

    last_error = "unknown error"
    for attempt in range(1, 4):
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            logger.warning("SRTM tile %s attempt %s failed: %s", url, attempt, exc)
            continue
        if response.status_code >= 500 or response.status_code == 429:
            last_error = f"HTTP {response.status_code}"
            continue
        if not response.is_success:
            raise TerrainError(f"SRTM tile not found ({url}): HTTP {response.status_code}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
        array = _hgt_to_array(response.content, lat0, lon0)
        return _clip_array(array, lat0, lon0, west, south, east, north)
    raise TerrainError(f"Could not download {url}: {last_error}")


def _hgt_to_array(payload: bytes, lat0: int, lon0: int) -> np.ndarray:
    raw = gzip.decompress(payload)
    values = np.frombuffer(raw, dtype=">i2")
    size = int(math.sqrt(values.size))
    if size * size != values.size:
        raise TerrainError(f"Unexpected HGT size {values.size} for tile {lat0},{lon0}")
    array = np.asarray(values.reshape((size, size)), dtype=np.float32)
    array[array == SRTM_NODATA] = np.nan
    return array


def _clip_array(
    array: np.ndarray,
    lat0: int,
    lon0: int,
    west: float,
    south: float,
    east: float,
    north: float,
) -> tuple[np.ndarray, Affine]:
    size = array.shape[0]
    pixel = 1.0 / (size - 1)
    tile_west, tile_north = float(lon0), float(lat0 + 1)
    transform = from_origin(tile_west, tile_north, pixel, pixel)
    window = window_from_bounds(west, south, east, north, transform=transform)
    row_off = max(int(math.floor(window.row_off)), 0)
    col_off = max(int(math.floor(window.col_off)), 0)
    row_end = min(int(math.ceil(window.row_off + window.height)), size)
    col_end = min(int(math.ceil(window.col_off + window.width)), size)
    if row_end <= row_off or col_end <= col_off:
        raise TerrainError(f"Tile {lat0},{lon0} does not overlap the study-area bounds")
    clipped = array[row_off:row_end, col_off:col_end]
    clipped_transform = window_transform(
        Window(col_off, row_off, clipped.shape[1], clipped.shape[0]),
        transform,
    )
    return clipped, clipped_transform


def _mosaic(arrays: list[np.ndarray], transforms: list[Affine]) -> tuple[np.ndarray, Affine]:
    with tempfile.TemporaryDirectory() as tmp:
        datasets = []
        paths = []
        for i, (array, transform) in enumerate(zip(arrays, transforms, strict=True)):
            path = Path(tmp) / f"tile_{i}.tif"
            _write_float_raster(path, array, transform, "EPSG:4326")
            paths.append(path)
            datasets.append(rasterio.open(path))
        try:
            mosaic, mosaic_transform = merge(datasets, nodata=OUT_NODATA)
        finally:
            for dataset in datasets:
                dataset.close()
    return mosaic[0], mosaic_transform


def _derive_terrain(
    dem_path: Path, boundary: gpd.GeoDataFrame
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Affine, object]:
    with rasterio.open(dem_path) as src:
        elevation = src.read(1).astype(np.float32)
        transform = src.transform
        crs = src.crs
        nodata = src.nodata

    valid = np.isfinite(elevation)
    if nodata is not None:
        valid &= elevation != nodata
    valid &= elevation != SRTM_NODATA
    elevation = np.where(valid, elevation, np.nan)

    slope = _slope_degrees(elevation, transform)
    roughness = _terrain_ruggedness_index(elevation)

    inside = _inside_mask(elevation.shape, transform, crs, boundary)
    elevation = np.where(inside, elevation, np.nan)
    slope = np.where(inside, slope, np.nan)
    roughness = np.where(inside, roughness, np.nan)
    return elevation, slope, roughness, transform, crs


def _slope_degrees(elevation: np.ndarray, transform: Affine) -> np.ndarray:
    pixel_x = abs(transform.a)
    pixel_y = abs(transform.e)
    height, _width = elevation.shape
    latitudes = transform.f - (np.arange(height) + 0.5) * pixel_y
    dx_m = pixel_x * 111_320.0 * np.cos(np.radians(latitudes))
    dy_m = pixel_y * 110_574.0
    filled = np.where(np.isfinite(elevation), elevation, 0.0)
    dz_dy = np.gradient(filled, axis=0) / dy_m
    dz_dx = np.gradient(filled, axis=1) / dx_m[:, None]
    slope = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))
    return np.where(np.isfinite(elevation), slope, np.nan).astype(np.float32)


def _terrain_ruggedness_index(elevation: np.ndarray) -> np.ndarray:
    """Riley et al. (1999) TRI: sqrt of squared elevation differences to 8 neighbors."""
    filled = np.where(np.isfinite(elevation), elevation, 0.0)
    acc = np.zeros(filled.shape, dtype=np.float64)
    for drow in (-1, 0, 1):
        for dcol in (-1, 0, 1):
            if drow == 0 and dcol == 0:
                continue
            shifted = np.roll(np.roll(filled, drow, axis=0), dcol, axis=1)
            acc += (shifted - filled) ** 2
    tri = np.sqrt(acc).astype(np.float32)
    tri[0, :] = np.nan
    tri[-1, :] = np.nan
    tri[:, 0] = np.nan
    tri[:, -1] = np.nan
    return np.where(np.isfinite(elevation), tri, np.nan)


def _inside_mask(
    shape: tuple[int, int],
    transform: Affine,
    crs: object,
    boundary: gpd.GeoDataFrame,
) -> np.ndarray:
    geom = boundary.union_all()
    if crs is not None and boundary.crs is not None and str(crs) != str(boundary.crs):
        geom = transform_geom(str(boundary.crs), str(crs), geom.__geo_interface__)
    else:
        geom = geom.__geo_interface__
    return geometry_mask([geom], out_shape=shape, transform=transform, invert=True)


def _write_float_raster(path: Path, array: np.ndarray, transform: Affine, crs: object) -> None:
    configure_proj()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.where(np.isfinite(array), array, OUT_NODATA).astype(np.float32)
    with rasterio.Env():
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype="float32",
            crs=crs,
            transform=transform,
            nodata=OUT_NODATA,
            compress="lzw",
        ) as dst:
            dst.write(data, 1)


def _masked_stats(array: np.ndarray) -> dict[str, float]:
    values = array[np.isfinite(array)]
    if values.size == 0:
        raise TerrainError("No valid elevation/slope cells inside the study area")
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }
