from pathlib import Path

from fastapi.testclient import TestClient

from app.dicts import DictCache
from app.text.pitch import _category, _mora_count, lookup_pitch
from shared.text import PitchQuery


def test_mora_count_ignores_small_kana_but_counts_sokuon_and_choon() -> None:
    assert _mora_count("たべる") == 3
    assert _mora_count("きょう") == 2  # small ょ folds into きょ
    assert _mora_count("がっこう") == 4  # sokuon っ IS a mora
    assert _mora_count("ラーメン") == 4  # ー (long vowel) and ん are morae
    assert _mora_count("しゅっぱつ") == 4  # small ゅ folds; sokuon counts


def test_category_from_position_and_mora() -> None:
    assert _category(0, 3) == "heiban"
    assert _category(1, 3) == "atamadaka"
    assert _category(2, 3) == "nakadaka"  # drop mid-word
    assert _category(3, 3) == "odaka"  # drop on the last mora
    assert _category(1, 1) == "atamadaka"  # 1-mora accented word


def test_lookup_pitch_disambiguates_homograph_by_reading(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    # 人/ひと carries two accents (0 heiban, 2 -> odaka since ひと is 2 morae).
    result = lookup_pitch(cache, PitchQuery(term="人", reading="ひと"))
    assert result.positions == [0, 2]
    assert result.categories == ["heiban", "odaka"]
    # にん (2 morae) with position 1 -> atamadaka.
    result = lookup_pitch(cache, PitchQuery(term="人", reading="にん"))
    assert result.positions == [1]
    assert result.categories == ["atamadaka"]


def test_lookup_pitch_normalizes_katakana_reading(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    result = lookup_pitch(cache, PitchQuery(term="水", reading="ミズ"))
    assert result.positions == [0]
    assert result.categories == ["heiban"]


def test_lookup_pitch_not_found(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    result = lookup_pitch(cache, PitchQuery(term="存在しない", reading="そんざい"))
    assert result.positions == []
    assert result.categories == []


def test_pitch_endpoint(text_client_with_dicts: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client_with_dicts.post(
        "/v1/text/pitch",
        headers=auth_headers,
        json={"queries": [{"term": "人", "reading": "ひと"}, {"term": "存在しない"}]},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["positions"] == [0, 2]
    assert results[0]["categories"] == ["heiban", "odaka"]
    assert results[1]["positions"] == []


def test_pitch_unavailable_without_cache(
    text_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = text_client.post(
        "/v1/text/pitch", headers=auth_headers, json={"queries": [{"term": "人"}]}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "dictionary_unavailable"


def test_pitch_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/pitch", json={"queries": [{"term": "人"}]})
    assert resp.status_code == 401
