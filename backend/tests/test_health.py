from fastapi.testclient import TestClient


def test_health_is_public_and_reports_ok(client: TestClient) -> None:
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "jp-utils"
    assert "version" in body
