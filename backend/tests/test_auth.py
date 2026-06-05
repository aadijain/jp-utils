from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


def test_v1_rejects_missing_token(client: TestClient) -> None:
    resp = client.get("/v1/ping")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_v1_rejects_wrong_token(client: TestClient) -> None:
    resp = client.get("/v1/ping", headers={"Authorization": "Bearer nope"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_v1_rejects_malformed_authorization_header(client: TestClient) -> None:
    resp = client.get("/v1/ping", headers={"Authorization": "test-token"})

    assert resp.status_code == 401


def test_v1_accepts_valid_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/v1/ping", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_v1_fails_closed_when_token_not_configured() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(api_token="")
    unconfigured = TestClient(app, raise_server_exceptions=False)

    resp = unconfigured.get("/v1/ping", headers={"Authorization": "Bearer anything"})

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "auth_not_configured"
