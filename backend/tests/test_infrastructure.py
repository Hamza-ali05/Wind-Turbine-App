from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, box

from app.services.infrastructure import (
    InfrastructureError,
    _summarize,
    acquire_infrastructure,
    get_grid_transmission_lines,
    get_road_network,
)
from tests.test_health import client


def _box_boundary() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[box(68.0, 24.8, 68.2, 25.0)], crs="EPSG:4326")


def test_summarize_road_length_and_power_counts() -> None:
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(68.0, 24.9), (68.1, 24.9)])],
        crs="EPSG:4326",
    )
    grid = gpd.GeoDataFrame(
        {
            "power": ["line", "substation", "substation", "tower", "tower", "tower"],
            "geometry": [
                LineString([(68.0, 24.9), (68.05, 24.95)]),
                Point(68.02, 24.91),
                Point(68.03, 24.92),
                Point(68.04, 24.93),
                Point(68.05, 24.94),
                Point(68.06, 24.95),
            ],
        },
        crs="EPSG:4326",
    )
    summary = _summarize(roads, grid)
    assert summary["substation_count"] == 2
    assert summary["tower_count"] == 3
    assert summary["power_line_count"] == 1
    assert summary["road_length_km"] > 0
    assert summary["crs_projected"] == "EPSG:32642"


def test_acquire_infrastructure_writes_wgs84_and_utm(tmp_path: Path, monkeypatch) -> None:
    roads = gpd.GeoDataFrame(
        {"highway": ["primary"], "geometry": [LineString([(68.0, 24.9), (68.05, 24.91)])]},
        crs="EPSG:4326",
    )
    grid = gpd.GeoDataFrame(
        {"power": ["substation", "tower"], "geometry": [Point(68.01, 24.9), Point(68.02, 24.91)]},
        crs="EPSG:4326",
    )
    monkeypatch.setattr("app.services.infrastructure.get_study_area_boundary", _box_boundary)
    monkeypatch.setattr("app.services.infrastructure.get_road_network", lambda gdf: roads)
    monkeypatch.setattr("app.services.infrastructure.get_grid_transmission_lines", lambda gdf: grid)
    monkeypatch.setattr("app.services.infrastructure._configure_osmnx", lambda *args, **kwargs: None)

    summary = acquire_infrastructure(
        force=True,
        road_path=tmp_path / "road_network.geojson",
        grid_path=tmp_path / "grid_lines.geojson",
        road_utm_path=tmp_path / "road_network_utm32642.geojson",
        grid_utm_path=tmp_path / "grid_lines_utm32642.geojson",
    )
    assert Path(summary["road_path"]).exists()
    assert Path(summary["road_utm_path"]).exists()
    assert Path(summary["grid_path"]).exists()
    assert Path(summary["grid_utm_path"]).exists()
    assert summary["substation_count"] == 1
    assert summary["tower_count"] == 1
    utm = gpd.read_file(summary["road_utm_path"])
    assert utm.crs.to_epsg() == 32642


def test_get_road_network_uses_graph_from_polygon(monkeypatch) -> None:
    called = {}

    class FakeGraph:
        pass

    def fake_graph_from_polygon(polygon, network_type="drive", simplify=True):
        called["network_type"] = network_type
        called["polygon"] = polygon
        return FakeGraph()

    edges_gdf = gpd.GeoDataFrame(
        {"highway": ["residential"], "geometry": [LineString([(68.0, 24.9), (68.01, 24.9)])]},
        crs="EPSG:4326",
    )
    monkeypatch.setattr("app.services.infrastructure.ox.graph_from_polygon", fake_graph_from_polygon)
    monkeypatch.setattr(
        "app.services.infrastructure.ox.graph_to_gdfs",
        lambda graph, nodes=False, edges=True, fill_edge_geometry=True: edges_gdf,
    )
    monkeypatch.setattr("app.services.infrastructure._configure_osmnx", lambda *args, **kwargs: None)

    result = get_road_network(_box_boundary())
    assert called["network_type"] == "drive"
    assert len(result) == 1


def test_get_grid_uses_power_tags(monkeypatch) -> None:
    called = {}

    def fake_features(polygon, tags):
        called["tags"] = tags
        return gpd.GeoDataFrame(
            {"power": ["line"], "geometry": [LineString([(68.0, 24.9), (68.02, 24.91)])]},
            crs="EPSG:4326",
        )

    monkeypatch.setattr("app.services.infrastructure.ox.features_from_polygon", fake_features)
    monkeypatch.setattr("app.services.infrastructure._configure_osmnx", lambda *args, **kwargs: None)
    result = get_grid_transmission_lines(_box_boundary())
    assert called["tags"]["power"] == ["line", "substation", "tower"]
    assert result["power"].iloc[0] == "line"


def test_infrastructure_endpoint_returns_502(monkeypatch) -> None:
    def boom(**kwargs):
        raise InfrastructureError("OSMnx could not download the drive network: timeout")

    monkeypatch.setattr("app.api.routes.data.acquire_infrastructure", boom)
    response = client.post("/api/v1/data/infrastructure")
    assert response.status_code == 502
    assert "drive network" in response.json()["detail"]


def test_infrastructure_endpoint_returns_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.data.acquire_infrastructure",
        lambda **kwargs: {
            "road_edge_count": 120,
            "road_length_km": 845.2,
            "grid_feature_count": 40,
            "substation_count": 6,
            "tower_count": 22,
            "power_line_count": 12,
            "crs_wgs84": "EPSG:4326",
            "crs_projected": "EPSG:32642",
            "road_path": "data/processed/road_network.geojson",
            "road_utm_path": "data/processed/road_network_utm32642.geojson",
            "grid_path": "data/processed/grid_lines.geojson",
            "grid_utm_path": "data/processed/grid_lines_utm32642.geojson",
        },
    )
    response = client.post("/api/v1/data/infrastructure")
    assert response.status_code == 200
    body = response.json()
    assert body["road_length_km"] == 845.2
    assert body["substation_count"] == 6
    assert body["tower_count"] == 22
