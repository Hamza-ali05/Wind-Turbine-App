from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box

from app.services.nasa_power import (
    NasaPowerError,
    _grid_points,
    acquire_wind_data,
    wind_power_density,
)
from tests.test_health import client


def _box_boundary() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[box(68.0, 24.5, 68.6, 25.1)], crs="EPSG:4326")


def test_wind_power_density_formula() -> None:
    assert round(wind_power_density(10.0), 3) == round(0.5 * 1.225 * 1000, 3)


def test_grid_points_stay_inside_polygon() -> None:
    boundary = _box_boundary()
    points = _grid_points(boundary, 0.25)
    assert len(points) >= 4
    polygon = boundary.union_all()
    for lon, lat in points:
        assert polygon.covers(Point(lon, lat))


def test_acquire_wind_data_writes_grid_and_raster(tmp_path: Path, monkeypatch) -> None:
    boundary = _box_boundary()
    monkeypatch.setattr("app.services.nasa_power.get_study_area_boundary", lambda: boundary)

    def fake_fetch(coords, *, delay_s):
        records = []
        for lon, lat in coords:
            ws50 = 6.0 + (lat - 24.5)
            records.append(
                {
                    "longitude": lon,
                    "latitude": lat,
                    "wind_speed_10m": ws50 - 1.5,
                    "wind_speed_50m": ws50,
                    "wind_power_density": wind_power_density(ws50),
                }
            )
        return records

    monkeypatch.setattr("app.services.nasa_power._fetch_points", fake_fetch)

    grid_path = tmp_path / "nasa_power_wind_grid.geojson"
    raster_path = tmp_path / "wind_speed_raster.tif"
    summary = acquire_wind_data(
        spacing_deg=0.25,
        delay_s=0,
        grid_path=grid_path,
        raster_path=raster_path,
    )

    assert summary["point_count"] >= 3
    assert grid_path.exists()
    assert raster_path.exists()
    assert summary["wind_speed_min"] <= summary["wind_speed_mean"] <= summary["wind_speed_max"]

    gdf = gpd.read_file(grid_path)
    required = {
        "latitude",
        "longitude",
        "wind_speed_10m",
        "wind_speed_50m",
        "wind_power_density",
        "geometry",
    }
    assert required.issubset(set(gdf.columns))


def test_wind_endpoint_returns_502_when_nasa_fails(monkeypatch) -> None:
    def boom(**kwargs):
        raise NasaPowerError("NASA POWER is unreachable: connection refused")

    monkeypatch.setattr("app.api.routes.data.acquire_wind_data", boom)
    response = client.post("/api/v1/data/wind")
    assert response.status_code == 502
    assert "NASA POWER is unreachable" in response.json()["detail"]


def test_wind_endpoint_returns_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.data.acquire_wind_data",
        lambda **kwargs: {
            "point_count": 12,
            "wind_speed_min": 4.1,
            "wind_speed_max": 7.8,
            "wind_speed_mean": 6.2,
            "wind_speed_height_m": 50,
            "grid_path": "data/raw/nasa_power_wind_grid.geojson",
            "raster_path": "data/processed/wind_speed_raster.tif",
        },
    )
    response = client.post("/api/v1/data/wind")
    assert response.status_code == 200
    body = response.json()
    assert body["point_count"] == 12
    assert body["wind_speed_mean"] == 6.2
    assert "wind_speed_raster.tif" in body["raster_path"]
