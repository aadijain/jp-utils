from fastapi.testclient import TestClient


def test_tokenize_endpoint_batches(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/tokenize",
        headers=auth_headers,
        json={"texts": ["猫が好き", ""]},
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["text"] for r in results] == ["猫が好き", ""]
    assert results[1]["tokens"] == []  # empty input -> no tokens
    assert results[0]["tokens"][0]["surface"] == "猫"


def test_tokenize_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/tokenize", json={"texts": ["猫"]})
    assert resp.status_code == 401


def test_tokenize_rejects_invalid_mode(
    text_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = text_client.post(
        "/v1/text/tokenize",
        headers=auth_headers,
        json={"texts": ["猫"], "mode": "Z"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_tokenize_unavailable_without_tokenizer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # The base client fixture injects no tokenizer.
    resp = client.post("/v1/text/tokenize", headers=auth_headers, json={"texts": ["猫"]})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tokenizer_unavailable"
