from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import box

from app.gis.proj_env import configure_proj
from app.services.elevation import (
    TerrainError,
    _slope_degrees,
    _terrain_ruggedness_index,
    _write_float_raster,
    acquire_terrain,
)
from tests.test_health import client


def _flat_dem() -> tuple[np.ndarray, object]:
    elevation = np.full((15, 15), 50.0, dtype=np.float32)
    transform = from_origin(68.0, 25.0, 0.001, 0.001)
    return elevation, transform


def test_flat_surface_has_near_zero_slope() -> None:
    elevation, transform = _flat_dem()
    slope = _slope_degrees(elevation, transform)
    assert float(np.nanmax(np.abs(slope[1:-1, 1:-1]))) < 0.05


def test_flat_surface_has_near_zero_roughness() -> None:
    elevation, _transform = _flat_dem()
    tri = _terrain_ruggedness_index(elevation)
    interior = tri[1:-1, 1:-1]
    assert float(np.nanmax(interior)) < 1e-3


def test_acquire_terrain_from_cached_dem(tmp_path: Path, monkeypatch) -> None:
    configure_proj()
    elevation, transform = _flat_dem()
    dem_path = tmp_path / "dem_srtm.tif"
    _write_float_raster(dem_path, elevation, transform, "EPSG:4326")

    boundary = gpd.GeoDataFrame(
        geometry=[box(68.002, 24.988, 68.012, 24.998)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr("app.services.elevation.get_study_area_boundary", lambda: boundary)

    summary = acquire_terrain(
        dem_path=dem_path,
        slope_path=tmp_path / "slope.tif",
        roughness_path=tmp_path / "terrain_roughness.tif",
        force=False,
    )
    assert summary["source"] == "cached"
    assert summary["elevation_mean"] == 50.0
    assert summary["slope_mean"] < 0.05
    assert Path(summary["slope_path"]).exists()
    assert Path(summary["roughness_path"]).exists()


def test_terrain_endpoint_returns_502(monkeypatch) -> None:
    def boom(**kwargs):
        raise TerrainError("Could not download a DEM covering the study area")

    monkeypatch.setattr("app.api.routes.data.acquire_terrain", boom)
    response = client.post("/api/v1/data/terrain")
    assert response.status_code == 502
    assert "Could not download a DEM" in response.json()["detail"]


def test_terrain_endpoint_returns_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.data.acquire_terrain",
        lambda **kwargs: {
            "elevation_min": 2.0,
            "elevation_max": 180.0,
            "elevation_mean": 41.0,
            "slope_min": 0.1,
            "slope_max": 12.4,
            "slope_mean": 2.2,
            "dem_path": "data/raw/dem_srtm.tif",
            "slope_path": "data/processed/slope.tif",
            "roughness_path": "data/processed/terrain_roughness.tif",
            "source": "aws_srtm",
        },
    )
    response = client.post("/api/v1/data/terrain")
    assert response.status_code == 200
    body = response.json()
    assert body["elevation_mean"] == 41.0
    assert body["slope_max"] == 12.4
    assert "slope.tif" in body["slope_path"]
