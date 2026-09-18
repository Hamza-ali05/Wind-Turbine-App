from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from app.gis.study_area import get_study_area_boundary
from tests.test_health import client


def test_get_study_area_boundary_reads_cache(tmp_path: Path) -> None:
    cache = tmp_path / "study_area_boundary.geojson"
    cached = gpd.GeoDataFrame(
        {"name": ["Sindh Wind Corridor"]},
        geometry=[box(67.0, 24.0, 69.0, 25.5)],
        crs="EPSG:4326",
    )
    cached.to_file(cache, driver="GeoJSON")

    result = get_study_area_boundary(cache_path=cache)
    assert result.crs.to_epsg() == 4326
    assert len(result) == 1
    assert not result.geometry.iloc[0].is_empty


def test_study_area_endpoint_returns_geojson(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "study_area_boundary.geojson"
    cached = gpd.GeoDataFrame(
        {"name": ["Sindh Wind Corridor"]},
        geometry=[box(67.0, 24.0, 69.0, 25.5)],
        crs="EPSG:4326",
    )
    cached.to_file(cache, driver="GeoJSON")
    monkeypatch.setattr("app.gis.study_area.BOUNDARY_PATH", cache)

    response = client.get("/api/v1/data/study-area")
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    assert body["features"][0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
