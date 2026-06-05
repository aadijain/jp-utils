from pathlib import Path

from fastapi.testclient import TestClient

from app.dicts import DictCache
from app.text.furigana import _align, annotate
from app.text.tokenizer import Tokenizer
from shared.text import FuriganaSegment

# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_align_distributes_reading_over_kanji() -> None:
    assert _align("食べ", "たべ") == [
        FuriganaSegment("食", "た"),
        FuriganaSegment("べ", ""),
    ]


def test_align_kanji_run_between_kana() -> None:
    assert _align("持ち帰っ", "もちかえっ") == [
        FuriganaSegment("持", "も"),
        FuriganaSegment("ち", ""),
        FuriganaSegment("帰", "かえ"),
        FuriganaSegment("っ", ""),
    ]


def test_align_returns_none_on_mismatch() -> None:
    assert _align("食べ", "xyz") is None


# ── annotate (with the synthetic dict cache) ─────────────────────────────────


def test_annotate_uses_cache_for_compound_split(tokenizer: Tokenizer, built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    # 日本語 is in the synthetic furigana dict -> split 日本|語 (alignment can't).
    assert annotate(tokenizer, "日本語", cache) == [
        FuriganaSegment("日本", "にほん"),
        FuriganaSegment("語", "ご"),
    ]


def test_annotate_aligns_inflected_word(tokenizer: Tokenizer, built_cache: Path) -> None:
    # 食べた tokenizes to 食べ + た; 食べ isn't a dict headword -> alignment.
    segments = annotate(tokenizer, "食べた", DictCache.open(built_cache))
    assert FuriganaSegment("食", "た") in segments
    assert "".join(s.text for s in segments) == "食べた"


def test_annotate_without_cache_degrades(tokenizer: Tokenizer) -> None:
    # No furigana dict: compound stays unsplit but the reading is still attached.
    assert annotate(tokenizer, "日本語", None) == [FuriganaSegment("日本語", "にほんご")]


def test_annotate_plain_kana(tokenizer: Tokenizer) -> None:
    assert annotate(tokenizer, "かわいい", None) == [FuriganaSegment("かわいい", "")]


# ── Endpoint ─────────────────────────────────────────────────────────────────


def test_furigana_endpoint(
    text_client_with_dicts: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = text_client_with_dicts.post(
        "/v1/text/furigana",
        headers=auth_headers,
        json={"texts": ["日本語"]},
    )

    assert resp.status_code == 200
    segments = resp.json()["results"][0]["segments"]
    assert segments == [
        {"text": "日本", "reading": "にほん"},
        {"text": "語", "reading": "ご"},
    ]


def test_furigana_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/furigana", json={"texts": ["猫"]})
    assert resp.status_code == 401
