from fastapi.testclient import TestClient

from app.text.locate import locate
from app.text.tokenizer import Tokenizer


def _segments(result):
    return [(s.text, s.match) for s in result.segments]


def test_locate_plain_match(tokenizer: Tokenizer) -> None:
    result = locate(tokenizer, "猫が好きだ", "猫")
    assert _segments(result) == [("猫", True), ("が好きだ", False)]


def test_locate_is_inflection_aware(tokenizer: Tokenizer) -> None:
    # 食べた is an inflection of 食べる; matched by lemma, not literal substring.
    result = locate(tokenizer, "りんごを食べた", "食べる")
    matched = [s.text for s in result.segments if s.match]
    assert matched == ["食べた"]


def test_locate_absorbs_conjugation_suffixes(tokenizer: Tokenizer) -> None:
    # 食べている = 食べ + て + いる across three tokens; the whole surface is one match.
    result = locate(tokenizer, "ご飯を食べている", "食べる")
    matched = [s.text for s in result.segments if s.match]
    assert matched == ["食べている"]


def test_locate_match_in_middle(tokenizer: Tokenizer) -> None:
    result = locate(tokenizer, "私は猫が好き", "猫")
    assert _segments(result) == [("私は", False), ("猫", True), ("が好き", False)]


def test_locate_no_match_returns_whole_text(tokenizer: Tokenizer) -> None:
    result = locate(tokenizer, "猫が好き", "犬")
    assert _segments(result) == [("猫が好き", False)]


def test_locate_empty_inputs(tokenizer: Tokenizer) -> None:
    assert locate(tokenizer, "", "猫").segments == []
    assert _segments(locate(tokenizer, "猫", "")) == [("猫", False)]


def test_locate_endpoint(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/locate",
        headers=auth_headers,
        json={
            "queries": [
                {"text": "りんごを食べた", "word": "食べる"},
                {"text": "猫が好き", "word": "犬"},
            ]
        },
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [(s["text"], s["match"]) for s in results[0]["segments"]] == [
        ("りんごを", False),
        ("食べた", True),
    ]
    # No match -> the whole text comes back as one unmatched segment.
    assert results[1]["segments"] == [{"text": "猫が好き", "match": False}]


def test_locate_unavailable_without_tokenizer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/v1/text/locate", headers=auth_headers, json={"queries": [{"text": "猫", "word": "猫"}]}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tokenizer_unavailable"


def test_locate_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/locate", json={"queries": [{"text": "猫", "word": "猫"}]})
    assert resp.status_code == 401
