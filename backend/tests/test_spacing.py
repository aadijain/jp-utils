from fastapi.testclient import TestClient

from app.text.spacing import space_text
from app.text.tokenizer import Tokenizer


def test_space_text_inserts_word_boundaries(tokenizer: Tokenizer) -> None:
    assert space_text(tokenizer, "日本語を勉強した") == "日本語 を 勉強 し た"


def test_space_text_custom_separator(tokenizer: Tokenizer) -> None:
    assert space_text(tokenizer, "猫が好き", separator="/") == "猫/が/好き"


def test_space_text_empty(tokenizer: Tokenizer) -> None:
    assert space_text(tokenizer, "") == ""


def test_space_endpoint_batches(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/space",
        headers=auth_headers,
        json={"texts": ["猫が好き", ""]},
    )

    assert resp.status_code == 200
    assert resp.json()["results"] == ["猫 が 好き", ""]


def test_space_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/space", json={"texts": ["猫"]})
    assert resp.status_code == 401
