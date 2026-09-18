from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import box

from app.gis.proj_env import configure_proj
from app.services.land_cover import (
    LandCoverError,
    _write_uint8_raster,
    acquire_land_cover,
    reclassify_for_wind_siting,
    worldcover_tile_ids,
)
from tests.test_health import client


def test_worldcover_tile_ids_cover_sindh_corridor() -> None:
    tiles = worldcover_tile_ids(66.72, 23.84, 69.30, 25.45)
    assert "N24E066" in tiles
    assert "N21E066" in tiles
    assert "N24E069" in tiles


def test_reclassify_worldcover_legend() -> None:
    source = np.array([[10, 40, 50], [60, 80, 90]], dtype=np.uint8)
    out = reclassify_for_wind_siting(source)
    assert out[0, 0] == 6  # forest
    assert out[0, 1] == 2  # agricultural
    assert out[0, 2] == 3  # urban
    assert out[1, 0] == 1  # buildable (bare)
    assert out[1, 1] == 4  # water
    assert out[1, 2] == 5  # wetland


def test_acquire_land_cover_from_local_raster(tmp_path: Path, monkeypatch) -> None:
    configure_proj()
    raw = np.array(
        [
            [60, 60, 40, 40],
            [60, 50, 40, 80],
            [30, 30, 10, 80],
            [30, 90, 10, 10],
        ],
        dtype=np.uint8,
    )
    transform = from_origin(68.0, 25.0, 0.01, 0.01)
    raw_path = tmp_path / "land_cover.tif"
    _write_uint8_raster(raw_path, raw, transform, "EPSG:4326")

    boundary = gpd.GeoDataFrame(
        geometry=[box(68.0, 24.96, 68.04, 25.0)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr("app.services.land_cover.get_study_area_boundary", lambda: boundary)

    summary = acquire_land_cover(
        raw_path=raw_path,
        processed_path=tmp_path / "land_cover_processed.tif",
        reclass_path=tmp_path / "land_cover_reclassified.tif",
        force=False,
    )
    assert summary["source"] == "cached"
    assert Path(summary["reclassified_path"]).exists()
    assert sum(summary["class_counts"].values()) > 0
    assert set(summary["class_counts"]) == {
        "buildable",
        "agricultural",
        "urban",
        "water",
        "wetland",
        "forest",
    }


def test_land_cover_endpoint_returns_502(monkeypatch) -> None:
    def boom(**kwargs):
        raise LandCoverError(
            "Automated Copernicus/WorldCover download failed. "
            "Place a GeoTIFF at data/raw/land_cover.tif and retry."
        )

    monkeypatch.setattr("app.api.routes.data.acquire_land_cover", boom)
    response = client.post("/api/v1/data/land-cover")
    assert response.status_code == 502
    assert "land_cover.tif" in response.json()["detail"]


def test_land_cover_endpoint_returns_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.data.acquire_land_cover",
        lambda **kwargs: {
            "source": "esa_worldcover_2021",
            "land_cover_path": "data/processed/land_cover.tif",
            "reclassified_path": "data/processed/land_cover_reclassified.tif",
            "class_counts": {
                "buildable": 10,
                "agricultural": 5,
                "urban": 1,
                "water": 2,
                "wetland": 1,
                "forest": 3,
            },
            "class_percent": {
                "buildable": 45.45,
                "agricultural": 22.73,
                "urban": 4.55,
                "water": 9.09,
                "wetland": 4.55,
                "forest": 13.64,
            },
            "class_fractions": {
                "buildable": 0.4545,
                "agricultural": 0.2273,
                "urban": 0.0455,
                "water": 0.0909,
                "wetland": 0.0455,
                "forest": 0.1364,
            },
        },
    )
    response = client.post("/api/v1/data/land-cover")
    assert response.status_code == 200
    body = response.json()
    assert body["class_counts"]["buildable"] == 10
    assert body["source"] == "esa_worldcover_2021"
