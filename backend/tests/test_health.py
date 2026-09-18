from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_redirects_to_docs() -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 302)
    assert response.headers["location"] == "/docs"


def test_app_title() -> None:
    assert app.title == "Wind Turbine Site Suitability API"


def test_placeholder_data_route() -> None:
    response = client.post("/api/v1/data/acquire")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_implemented"
    assert body["stage"] == "data_acquisition"


def test_sites_crud_placeholder() -> None:
    created = client.post(
        "/api/v1/sites",
        json={"name": "Jhimpir candidate", "latitude": 25.05, "longitude": 68.01},
    )
    assert created.status_code == 201
    site_id = created.json()["id"]

    listed = client.get("/api/v1/sites")
    assert listed.status_code == 200
    assert any(item["id"] == site_id for item in listed.json())

    fetched = client.get(f"/api/v1/sites/{site_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Jhimpir candidate"
