from pathlib import Path

from fastapi.testclient import TestClient

from app.dicts import DictCache
from app.text.frequency import lookup_frequency
from app.text.tokenizer import Tokenizer
from shared.text import FrequencyQuery


def test_lookup_frequency_by_term(tokenizer: Tokenizer, built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert lookup_frequency(tokenizer, cache, FrequencyQuery(term="水")).rank == 500


def test_lookup_frequency_disambiguates_homograph_by_reading(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # Same term, the reading picks the rank (人 ひと vs にん in the real dict).
    assert lookup_frequency(tokenizer, cache, FrequencyQuery(term="水", reading="みず")).rank == 500
    assert lookup_frequency(tokenizer, cache, FrequencyQuery(term="水", reading="すい")).rank == 800


def test_lookup_frequency_reading_fallback_normalizes_kana(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # term has no rank; katakana reading falls back to the hiragana kana-form みず.
    result = lookup_frequency(tokenizer, cache, FrequencyQuery(term="ミヅ", reading="ミズ"))
    assert result.rank == 1500


def test_lookup_frequency_not_found(tokenizer: Tokenizer, built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert lookup_frequency(tokenizer, cache, FrequencyQuery(term="存在しない")).rank is None


def test_lookup_frequency_falls_back_to_the_deinflected_term(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # 食べた is not ranked as written; its lemma is, and the result echoes the key
    # that answered - with the lemma's own reading, not the surface's.
    result = lookup_frequency(tokenizer, cache, FrequencyQuery(term="食べた"))
    assert (result.term, result.reading, result.rank) == ("食べる", "たべる", 700)


def test_lookup_frequency_keeps_a_surface_that_is_already_ranked(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # The surface answers, so no deinflection intervenes and the homograph reading survives.
    result = lookup_frequency(tokenizer, cache, FrequencyQuery(term="水", reading="すい"))
    assert (result.term, result.reading, result.rank) == ("水", "すい", 800)


def test_lookup_frequency_miss_echoes_the_query_not_the_lemma(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # Unranked either way: the caller gets back what it asked about.
    result = lookup_frequency(tokenizer, cache, FrequencyQuery(term="走った"))
    assert (result.term, result.rank) == ("走った", None)


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
