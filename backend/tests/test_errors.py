from fastapi.testclient import TestClient


def test_unknown_route_uses_standard_error_shape(client: TestClient) -> None:
    resp = client.get("/does-not-exist")

    assert resp.status_code == 404
    body = resp.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "not_found"
