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


def test_content_words_endpoint(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/content-words",
        headers=auth_headers,
        json={"texts": ["猫が好きだ", ""]},
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2  # aligned with the input texts
    assert results[1] == []  # empty input -> no content words
    lemmas = [w["lemma"] for w in results[0]]
    # 猫 (noun) and 好き (na-adj) are content words; the particle が is dropped.
    assert "猫" in lemmas
    assert "が" not in lemmas
    assert all(w["reading"] for w in results[0])  # each carries a contextual reading


def test_content_words_unavailable_without_tokenizer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/v1/text/content-words", headers=auth_headers, json={"texts": ["猫"]})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tokenizer_unavailable"


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
