"""ESA Copernicus / WorldCover land cover for the Sindh Wind Corridor."""

from __future__ import annotations

import logging
import math
from pathlib import Path

import geopandas as gpd
import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import Affine, from_bounds as affine_from_bounds
from rasterio.warp import reproject, transform_geom
from rasterio.windows import Window, from_bounds as window_from_bounds

from app.core.config import get_settings
from app.gis.proj_env import configure_proj
from app.gis.study_area import get_study_area_boundary

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MANUAL_RAW_PATH = BACKEND_ROOT / "data" / "raw" / "land_cover.tif"
LAND_COVER_PATH = BACKEND_ROOT / "data" / "processed" / "land_cover.tif"
RECLASS_PATH = BACKEND_ROOT / "data" / "processed" / "land_cover_reclassified.tif"

WORLDCOVER_PREFIX_DEFAULT = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
)
USER_AGENT = "wind-suitability-platform/0.1 (Sindh Wind Corridor research)"
NODATA = 0
TARGET_RES_DEG = 0.0003  # ~30 m, aligned with SRTM-scale suitability layers
BUFFER_DEG = 0.02

# ESA WorldCover 2021 classes -> wind-siting categories (thesis: buildable land + roughness).
WORLDCOVER_TO_SITING = {
    10: 6,  # tree cover -> forest / protected
    20: 1,  # shrubland -> buildable
    30: 1,  # grassland -> buildable
    40: 2,  # cropland -> agricultural
    50: 3,  # built-up -> urban
    60: 1,  # bare / sparse -> buildable
    70: 0,  # snow/ice (absent in Sindh)
    80: 4,  # water
    90: 5,  # herbaceous wetland
    95: 5,  # mangroves -> wetland
    100: 1,  # moss/lichen -> buildable
}

# Copernicus CGLS-LC100 extra forest codes collapse to forest.
for _code in range(111, 127):
    WORLDCOVER_TO_SITING[_code] = 6

CLASS_NAMES = {
    1: "buildable",
    2: "agricultural",
    3: "urban",
    4: "water",
    5: "wetland",
    6: "forest",
}

MANUAL_FALLBACK_HINT = (
    "Place a land-cover GeoTIFF at backend/data/raw/land_cover.tif and retry, "
    "or set COPERNICUS_LANDCOVER_WCS_URL / COPERNICUS_LANDCOVER_URL "
    "(and COPERNICUS_API_KEY if required) in .env."
)


class LandCoverError(Exception):
    """Land-cover download or reclassification failure (maps to HTTP 502)."""


def acquire_land_cover(
    *,
    raw_path: Path | None = None,
    processed_path: Path | None = None,
    land_cover_path: Path | None = None,
    reclass_path: Path | None = None,
    force: bool = False,
) -> dict:
    """Download/clip ESA WorldCover, reclassify for wind siting, write GeoTIFFs."""
    configure_proj()
    processed = processed_path or land_cover_path or LAND_COVER_PATH
    reclass_path = reclass_path or RECLASS_PATH
    raw = raw_path if raw_path is not None else MANUAL_RAW_PATH
    boundary = get_study_area_boundary()
    west, south, east, north = _buffered_bounds(boundary)

    source = "cached"
    if force or not processed.exists():
        array, transform, crs, source = _obtain_land_cover(
            west, south, east, north, raw_path=raw, raw_was_explicit=raw_path is not None
        )
        _write_uint8_raster(processed, array, transform, crs)
    else:
        with rasterio.open(processed) as src:
            array = src.read(1)
            transform = src.transform
            crs = src.crs

    reclass = reclassify_for_wind_siting(array)
    reclass = _mask_to_boundary(reclass, transform, crs, boundary)
    _write_uint8_raster(reclass_path, reclass, transform, crs)

    counts, percents, fractions = _class_distribution(reclass)
    logger.info("Land cover ready source=%s classes=%s", source, counts)
    return {
        "class_counts": counts,
        "class_percent": percents,
        "class_fractions": fractions,
        "source": source,
        "land_cover_path": str(processed),
        "reclassified_path": str(reclass_path),
    }


def reclassify_for_wind_siting(array: np.ndarray) -> np.ndarray:
    """Map ESA/Copernicus land-cover codes to the six wind-siting classes."""
    if not np.isin(array, list(WORLDCOVER_TO_SITING.keys())).any():
        return array.astype(np.uint8)
    out = np.zeros(array.shape, dtype=np.uint8)
    for src_code, dst_code in WORLDCOVER_TO_SITING.items():
        out[array == src_code] = dst_code
    return out


def _buffered_bounds(boundary: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    west, south, east, north = boundary.total_bounds
    return (
        float(west - BUFFER_DEG),
        float(south - BUFFER_DEG),
        float(east + BUFFER_DEG),
        float(north + BUFFER_DEG),
    )


def _obtain_land_cover(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    raw_path: Path,
    raw_was_explicit: bool,
) -> tuple[np.ndarray, Affine, object, str]:
    if raw_was_explicit and raw_path.exists():
        logger.info("Using local land-cover raster %s", raw_path)
        array, transform, crs = _clip_local_raster(raw_path, west, south, east, north)
        return array, transform, crs, "cached"

    errors: list[str] = []
    settings = get_settings()

    try:
        array, transform, crs = _download_worldcover(west, south, east, north)
        return array, transform, crs, "esa_worldcover_2021"
    except Exception as exc:
        errors.append(f"ESA WorldCover: {exc}")
        logger.warning("ESA WorldCover download failed: %s", exc)

    custom_url = settings.COPERNICUS_LANDCOVER_WCS_URL or settings.COPERNICUS_LANDCOVER_URL
    if custom_url:
        try:
            array, transform, crs = _download_configured_url(
                west,
                south,
                east,
                north,
                custom_url,
                settings.COPERNICUS_API_KEY,
            )
            return array, transform, crs, "copernicus_url"
        except Exception as exc:
            errors.append(f"Copernicus URL: {exc}")
            logger.warning("Configured Copernicus URL failed: %s", exc)
    else:
        errors.append("COPERNICUS_LANDCOVER_WCS_URL / COPERNICUS_LANDCOVER_URL is not set")

    if raw_path.exists():
        logger.info("Falling back to manually provided raster %s", raw_path)
        array, transform, crs = _clip_local_raster(raw_path, west, south, east, north)
        return array, transform, crs, "manual_raw"

    detail = " | ".join(errors)
    raise LandCoverError(
        f"Could not download Copernicus/ESA land cover ({detail}). {MANUAL_FALLBACK_HINT}"
    )


def worldcover_tile_ids(west: float, south: float, east: float, north: float) -> list[str]:
    """Return WorldCover 3° tile ids (e.g. N24E066) intersecting a bounding box."""
    names = []
    for lat0, lon0 in _worldcover_tile_origins(west, south, east, north):
        ns = "N" if lat0 >= 0 else "S"
        ew = "E" if lon0 >= 0 else "W"
        names.append(f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}")
    return names


def _download_worldcover(
    west: float, south: float, east: float, north: float
) -> tuple[np.ndarray, Affine, object]:
    tiles = _worldcover_tile_origins(west, south, east, north)
    if not tiles:
        raise LandCoverError("Study-area bounds did not intersect any WorldCover tile")

    out_w, out_h, dst_transform = _destination_grid(west, south, east, north)
    mosaic = np.zeros((out_h, out_w), dtype=np.uint8)
    env = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "AWS_NO_SIGN_REQUEST": "YES",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
        "GDAL_HTTP_USERAGENT": USER_AGENT,
    }
    opened = 0
    with rasterio.Env(**env):
        for lat0, lon0 in tiles:
            url = _worldcover_url(lat0, lon0)
            vsicurl = f"/vsicurl/{url}"
            logger.info("Reading WorldCover tile %s", url)
            try:
                with rasterio.open(vsicurl) as src:
                    window = window_from_bounds(west, south, east, north, transform=src.transform)
                    window = (
                        window.intersection(Window(0, 0, src.width, src.height))
                        .round_offsets()
                        .round_lengths()
                    )
                    if window.width <= 0 or window.height <= 0:
                        continue
                    src_array = src.read(1, window=window)
                    src_transform = src.window_transform(window)
                    tmp = np.zeros((out_h, out_w), dtype=np.uint8)
                    reproject(
                        source=src_array,
                        destination=tmp,
                        src_transform=src_transform,
                        src_crs=src.crs,
                        src_nodata=src.nodata or 0,
                        dst_transform=dst_transform,
                        dst_crs="EPSG:4326",
                        dst_nodata=NODATA,
                        resampling=Resampling.mode,
                    )
                    mosaic = np.where(tmp != NODATA, tmp, mosaic)
                    opened += 1
            except Exception as exc:
                logger.warning("WorldCover vsicurl failed for %s: %s", url, exc)
                try:
                    local = _download_worldcover_tile_http(url, lat0, lon0)
                    array, transform, crs = _clip_local_raster(local, west, south, east, north)
                    mosaic = np.where(array != NODATA, array, mosaic)
                    opened += 1
                except Exception as http_exc:
                    logger.warning("WorldCover HTTP fallback failed for %s: %s", url, http_exc)
                    continue
    if opened == 0:
        raise LandCoverError("No WorldCover tiles could be read via the public AWS COGs")
    return mosaic, dst_transform, "EPSG:4326"


def _worldcover_tile_origins(west: float, south: float, east: float, north: float) -> list[tuple[int, int]]:
    lat_start = int(math.floor(south / 3.0) * 3)
    lat_end = int(math.floor((north - 1e-9) / 3.0) * 3)
    lon_start = int(math.floor(west / 3.0) * 3)
    lon_end = int(math.floor((east - 1e-9) / 3.0) * 3)
    tiles = []
    for lat in range(lat_start, lat_end + 1, 3):
        for lon in range(lon_start, lon_end + 1, 3):
            tiles.append((lat, lon))
    return tiles


def _worldcover_url(lat0: int, lon0: int) -> str:
    settings = get_settings()
    prefix = (settings.ESA_WORLDCOVER_BASE_URL or WORLDCOVER_PREFIX_DEFAULT).rstrip("/")
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    tile = f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"
    return f"{prefix}/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"


def _download_worldcover_tile_http(url: str, lat0: int, lon0: int) -> Path:
    """Fetch a WorldCover COG with requests if vsicurl cannot stream it."""
    import requests

    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    tile = f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"
    dest = BACKEND_ROOT / "data" / "raw" / "worldcover" / f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=300, stream=True)
    if not response.ok:
        raise LandCoverError(f"WorldCover HTTP {response.status_code} for {url}")
    with dest.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            handle.write(chunk)
    return dest


def _download_configured_url(
    west: float,
    south: float,
    east: float,
    north: float,
    url: str,
    api_key: str,
) -> tuple[np.ndarray, Affine, object]:
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    fetch_url = url
    if "{west}" in url:
        fetch_url = url.format(west=west, south=south, east=east, north=north, api_key=api_key)
    elif api_key and "API_KEY" not in url.upper() and "api_key" not in url:
        sep = "&" if "?" in url else "?"
        fetch_url = f"{url}{sep}api_key={api_key}"

    dest = MANUAL_RAW_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300.0, headers=headers, follow_redirects=True) as client:
        with client.stream("GET", fetch_url) as response:
            if response.status_code == 401 or response.status_code == 403:
                raise LandCoverError(
                    f"Copernicus land-cover URL returned HTTP {response.status_code} "
                    f"(authentication required). {MANUAL_FALLBACK_HINT}"
                )
            if not response.is_success:
                raise LandCoverError(f"Copernicus land-cover URL HTTP {response.status_code}")
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    return _clip_local_raster(dest, west, south, east, north)


def _clip_local_raster(
    path: Path, west: float, south: float, east: float, north: float
) -> tuple[np.ndarray, Affine, object]:
    out_w, out_h, dst_transform = _destination_grid(west, south, east, north)
    mosaic = np.zeros((out_h, out_w), dtype=np.uint8)
    with rasterio.Env():
        with rasterio.open(path) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=mosaic,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata or 0,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                dst_nodata=NODATA,
                resampling=Resampling.mode,
            )
    return mosaic, dst_transform, "EPSG:4326"


def _destination_grid(
    west: float, south: float, east: float, north: float
) -> tuple[int, int, Affine]:
    out_w = max(int(math.ceil((east - west) / TARGET_RES_DEG)), 2)
    out_h = max(int(math.ceil((north - south) / TARGET_RES_DEG)), 2)
    transform = affine_from_bounds(west, south, east, north, out_w, out_h)
    return out_w, out_h, transform


def _mask_to_boundary(
    array: np.ndarray,
    transform: Affine,
    crs: object,
    boundary: gpd.GeoDataFrame,
) -> np.ndarray:
    geom = boundary.union_all()
    if crs is not None and boundary.crs is not None and str(crs) != str(boundary.crs):
        geom = transform_geom(str(boundary.crs), str(crs), geom.__geo_interface__)
    else:
        geom = geom.__geo_interface__
    inside = geometry_mask([geom], out_shape=array.shape, transform=transform, invert=True)
    return np.where(inside, array, NODATA).astype(np.uint8)


def _class_distribution(
    array: np.ndarray,
) -> tuple[dict[str, int], dict[str, float], dict[str, float]]:
    valid = array[array != NODATA]
    counts = {name: int(np.sum(valid == code)) for code, name in CLASS_NAMES.items()}
    total = int(valid.size) or 1
    percents = {name: round(100.0 * n / total, 2) for name, n in counts.items()}
    fractions = {name: round(n / total, 4) for name, n in counts.items()}
    return counts, percents, fractions


def _write_uint8_raster(path: Path, array: np.ndarray, transform: Affine, crs: object) -> None:
    configure_proj()
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.Env():
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=array.shape[0],
            width=array.shape[1],
            count=1,
            dtype="uint8",
            crs=crs,
            transform=transform,
            nodata=NODATA,
            compress="lzw",
        ) as dst:
            dst.write(array.astype(np.uint8), 1)
            dst.update_tags(
                source="ESA WorldCover 10m 2021 v200 / Copernicus Sentinel",
                classes="1=buildable,2=agricultural,3=urban,4=water,5=wetland,6=forest",
            )
