from fastapi.testclient import TestClient
from app.main import app


def test_openapi_contains_core_routes():
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/projects" in paths
    assert "/api/v1/projects/{project_id}/issues" in paths
    assert "/api/v1/issues/{identifier}/transition" in paths
    assert "/api/v1/projects/{project_id}/board" in paths


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
