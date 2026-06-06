from fastapi.testclient import TestClient

from app.text.normalize import normalize
from app.text.tokenizer import Tokenizer


def test_normalize_deinflects_verb(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "食べた")
    assert result.lemma == "食べる"
    assert result.reading == "たべる"  # lemma reading, in hiragana


def test_normalize_uses_normalized_form_field(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "した")
    assert result.lemma == "する"  # dictionary form (matches dict headwords)
    assert result.normalized == "為る"  # Sudachi's variant-unified form
    assert result.reading == "する"


def test_normalize_plain_noun(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "猫")
    assert (result.lemma, result.reading) == ("猫", "ねこ")


def test_normalize_empty(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "   ")
    assert result.lemma == ""
    assert result.reading == ""


def test_normalize_endpoint(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/normalize",
        headers=auth_headers,
        json={"surfaces": ["行きました", "猫"]},
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert (results[0]["lemma"], results[0]["reading"]) == ("行く", "いく")
    assert results[1]["lemma"] == "猫"


def test_normalize_unavailable_without_tokenizer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/v1/text/normalize", headers=auth_headers, json={"surfaces": ["猫"]})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tokenizer_unavailable"


def test_normalize_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/normalize", json={"surfaces": ["猫"]})
    assert resp.status_code == 401
