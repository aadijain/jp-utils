from pathlib import Path

from fastapi.testclient import TestClient

from app.dicts import DictCache
from app.text.meaning import lookup_meaning
from shared.text import MeaningQuery


def test_lookup_meaning_returns_entries(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    result = lookup_meaning(cache, MeaningQuery(lemma="食べる"))
    senses = result.entries[0].senses
    assert [s.glosses for s in senses] == [["to eat"], ["to live on", "to subsist"]]
    assert senses[0].pos == ["1-dan", "transitive"]
    assert senses[0].examples[0].ja == "寿司を食べる"
    assert senses[0].examples[0].en == "to eat sushi"
    assert result.entries[0].reading == "たべる"
    assert result.entries[0].jlpt == 5
    assert result.all_readings == ["たべる"]


def test_lookup_meaning_reading_filter_normalizes_kana(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    # katakana reading still matches the hiragana headword reading
    assert lookup_meaning(cache, MeaningQuery(lemma="食べる", reading="タベル")).entries
    assert not lookup_meaning(cache, MeaningQuery(lemma="食べる", reading="ちがう")).entries


def test_lookup_meaning_not_found(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert lookup_meaning(cache, MeaningQuery(lemma="存在しない")).entries == []


def test_meaning_endpoint(text_client_with_dicts: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client_with_dicts.post(
        "/v1/text/meaning",
        headers=auth_headers,
        json={"queries": [{"lemma": "水"}, {"lemma": "存在しない"}]},
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["entries"][0]["senses"] == [{"glosses": ["water"], "pos": [], "examples": []}]
    assert results[1]["entries"] == []


def test_meaning_unavailable_without_cache(
    text_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # text_client has a tokenizer but no dict cache.
    resp = text_client.post(
        "/v1/text/meaning", headers=auth_headers, json={"queries": [{"lemma": "水"}]}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "dictionary_unavailable"


def test_meaning_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/meaning", json={"queries": [{"lemma": "水"}]})
    assert resp.status_code == 401
