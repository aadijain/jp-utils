from pathlib import Path

from fastapi.testclient import TestClient

from app.dicts import DictCache
from app.text.meaning import lookup_meaning
from app.text.tokenizer import Tokenizer
from shared.text import MeaningQuery


def test_lookup_meaning_returns_entries(tokenizer: Tokenizer, built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    result = lookup_meaning(tokenizer, cache, MeaningQuery(lemma="食べる"))
    senses = result.entries[0].senses
    assert [s.glosses for s in senses] == [["to eat"], ["to live on", "to subsist"]]
    assert senses[0].pos == ["1-dan", "transitive"]
    example = senses[0].examples[0]
    assert example.ja == "寿司を食べる"
    assert example.en == "to eat sushi"
    # segments carry furigana + the source keyword highlight (食べる)
    assert [(s.text, s.reading, s.keyword) for s in example.segments] == [
        ("寿司", "すし", False),
        ("を", "", False),
        ("食", "た", True),
        ("べる", "", True),
    ]
    assert result.entries[0].reading == "たべる"
    assert result.entries[0].jlpt == 5
    assert result.all_readings == ["たべる"]


def test_lookup_meaning_reading_filter_normalizes_kana(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # katakana reading still matches the hiragana headword reading
    assert lookup_meaning(tokenizer, cache, MeaningQuery(lemma="食べる", reading="タベル")).entries
    assert not lookup_meaning(
        tokenizer, cache, MeaningQuery(lemma="食べる", reading="ちがう")
    ).entries


def test_lookup_meaning_falls_back_to_the_deinflected_lemma(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # 食べた is not a headword; its lemma is, and the result echoes the key that answered.
    result = lookup_meaning(tokenizer, cache, MeaningQuery(lemma="食べた"))
    assert (result.lemma, result.reading) == ("食べる", "たべる")
    assert result.entries[0].senses[0].glosses == ["to eat"]


def test_lookup_meaning_falls_back_to_the_written_spelling_of_a_kana_key(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # もらう is what the collapse keys on and JPDB ranks it 112, so neither the
    # lemma as written nor the deinflected key gets past it - but jitendex lists
    # only 貰う, the spelling the collapse overrode.
    result = lookup_meaning(tokenizer, cache, MeaningQuery(lemma="もらう"))
    assert (result.lemma, result.reading) == ("貰う", "もらう")
    assert result.entries[0].senses[0].glosses == ["to receive"]


def test_lookup_meaning_keeps_a_lemma_that_is_already_a_headword(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # The lemma answers as written, so nothing is deinflected out from under it.
    result = lookup_meaning(tokenizer, cache, MeaningQuery(lemma="人", reading="ひと"))
    assert (result.lemma, result.reading) == ("人", "ひと")
    assert result.entries[0].senses[0].glosses == ["person"]


def test_lookup_meaning_miss_echoes_the_query_and_keeps_its_readings(
    tokenizer: Tokenizer, built_cache: Path
) -> None:
    cache = DictCache.open(built_cache)
    # 人 has entries but none under this reading, and deinflecting a headword is a
    # no-op - so the query is echoed, with the readings it does have.
    result = lookup_meaning(tokenizer, cache, MeaningQuery(lemma="人", reading="ちがう"))
    assert (result.lemma, result.reading, result.entries) == ("人", "ちがう", [])
    assert result.all_readings == ["ひと"]


def test_lookup_meaning_not_found(tokenizer: Tokenizer, built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert lookup_meaning(tokenizer, cache, MeaningQuery(lemma="存在しない")).entries == []


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
