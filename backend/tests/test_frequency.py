from pathlib import Path

from fastapi.testclient import TestClient

from app.dicts import DictCache
from app.text.frequency import lookup_frequency
from shared.text import FrequencyQuery


def test_lookup_frequency_by_term(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert lookup_frequency(cache, FrequencyQuery(term="水")).rank == 500


def test_lookup_frequency_disambiguates_homograph_by_reading(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    # Same term, the reading picks the rank (人 ひと vs にん in the real dict).
    assert lookup_frequency(cache, FrequencyQuery(term="水", reading="みず")).rank == 500
    assert lookup_frequency(cache, FrequencyQuery(term="水", reading="すい")).rank == 800


def test_lookup_frequency_reading_fallback_normalizes_kana(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    # term has no rank; katakana reading falls back to the hiragana kana-form みず.
    result = lookup_frequency(cache, FrequencyQuery(term="ミヅ", reading="ミズ"))
    assert result.rank == 1500


def test_lookup_frequency_not_found(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert lookup_frequency(cache, FrequencyQuery(term="存在しない")).rank is None


def test_frequency_endpoint(
    text_client_with_dicts: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = text_client_with_dicts.post(
        "/v1/text/frequency",
        headers=auth_headers,
        json={"queries": [{"term": "水"}, {"term": "存在しない"}]},
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["rank"] == 500
    assert results[1]["rank"] is None


def test_frequency_unavailable_without_cache(
    text_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = text_client.post(
        "/v1/text/frequency", headers=auth_headers, json={"queries": [{"term": "水"}]}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "dictionary_unavailable"


def test_frequency_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/frequency", json={"queries": [{"term": "水"}]})
    assert resp.status_code == 401
