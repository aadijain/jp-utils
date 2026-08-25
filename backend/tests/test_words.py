from pathlib import Path
from unittest import mock

import pytest

from app.cache import TokenizationCache, sentence_hash
from app.dicts import Spellings
from app.text.tokenizer import Tokenizer
from app.text.words import (
    content_words,
    content_words_with_readings,
    is_content,
    is_pure_katakana,
)


def _tok(tokenizer: Tokenizer, text: str):
    return tokenizer.tokenize(text)[0]


class _FakeDicts:
    """Stands in for `DictCache` with a hand-written rank table (see test_canonical)."""

    def __init__(self, ranks: dict[str, int]) -> None:
        self._ranks = ranks

    def lookup_frequency(self, term: str, reading: str | None = None) -> int | None:
        return self._ranks.get(term)

    def lookup_spellings(self, term: str) -> Spellings:
        # As-written ranks only; the kana-spelling comparison has test_canonical.
        return Spellings(self._ranks.get(term), None, None)


@pytest.fixture
def cache(tmp_path: Path) -> TokenizationCache:
    return TokenizationCache.open(tmp_path / "tok.db")


def test_keeps_nouns_and_verbs_drops_particles(tokenizer: Tokenizer) -> None:
    # 猫 (noun) and 食べる (verb, deinflected) survive; を/た (particle/aux) drop.
    assert content_words(tokenizer, "猫が魚を食べた") == ["猫", "魚", "食べる"]


def test_deinflects_to_dictionary_form(tokenizer: Tokenizer) -> None:
    # Inflected verb -> lemma, not the surface form.
    assert "行く" in content_words(tokenizer, "学校に行きました")


def test_dedupes_preserving_order(tokenizer: Tokenizer) -> None:
    lemmas = content_words(tokenizer, "猫と猫")
    assert lemmas == ["猫"]


def test_drops_proper_nouns_and_numerals(tokenizer: Tokenizer) -> None:
    # 固有名詞 (names) + 数詞 (numerals) are excluded even though top-level is 名詞.
    assert is_content(_tok(tokenizer, "田中")) is False
    assert is_content(_tok(tokenizer, "三")) is False


def test_is_pure_katakana() -> None:
    assert is_pure_katakana("コーヒー")  # letters + ー
    assert is_pure_katakana("ジャン・ポール")  # letters + ・
    assert is_pure_katakana("ア")
    assert not is_pure_katakana("")
    assert not is_pure_katakana("ー")  # no real kana
    assert not is_pure_katakana("・")
    assert not is_pure_katakana("食べる")  # kanji + hiragana
    assert not is_pure_katakana("みず")  # hiragana
    assert not is_pure_katakana("コーヒーA")  # trailing non-katakana


def test_drops_purely_katakana_loanwords(tokenizer: Tokenizer) -> None:
    # A katakana loanword is a common 名詞 but is filtered like a proper noun; the
    # kanji noun in the same sentence survives.
    assert is_content(_tok(tokenizer, "コーヒー")) is False
    assert "コーヒー" not in content_words(tokenizer, "コーヒーを飲む")
    assert "飲む" in content_words(tokenizer, "コーヒーを飲む")


def test_empty_text(tokenizer: Tokenizer) -> None:
    assert content_words(tokenizer, "") == []
    assert content_words(tokenizer, "。、！") == []


def test_cache_miss_populates(tokenizer: Tokenizer, cache: TokenizationCache) -> None:
    words = content_words_with_readings(tokenizer, "犬が走る", cache=cache)
    key = sentence_hash("犬が走る")
    assert cache.get_many([key]) == {key: words}


def test_cache_hit_skips_tokenization(tokenizer: Tokenizer, cache: TokenizationCache) -> None:
    first = content_words_with_readings(tokenizer, "猫が魚を食べた", cache=cache)
    # A spy tokenizer that explodes if touched; the cached hit must not reach it.
    spy = mock.create_autospec(tokenizer, instance=True)
    spy.tokenize.side_effect = AssertionError("tokenizer called on cache hit")
    assert content_words_with_readings(spy, "猫が魚を食べた", cache=cache) == first


def test_no_cache_argument_still_extracts(tokenizer: Tokenizer) -> None:
    # The cache is optional; without it the extractor behaves exactly as before.
    assert content_words_with_readings(tokenizer, "猫が魚を食べた")[0].lemma == "猫"


def test_collapses_inflection_residue_when_dicts_are_available(tokenizer: Tokenizer) -> None:
    # 話せる has no rank of its own; the sentence's vocabulary is 話す.
    dicts = _FakeDicts({"話す": 285})
    assert content_words(tokenizer, "日本語が話せる", dicts=dicts) == ["日本語", "話す"]


def test_dedupes_on_the_collapsed_lemma(tokenizer: Tokenizer) -> None:
    # 作る and 作れる are one word, so the sentence must not count both.
    dicts = _FakeDicts({"作る": 140})
    assert content_words(tokenizer, "作る人が作れる物", dicts=dicts) == ["作る", "人", "物"]


def test_collapsed_lemma_carries_the_base_reading(tokenizer: Tokenizer) -> None:
    dicts = _FakeDicts({"読む": 320})
    words = content_words_with_readings(tokenizer, "本が読めない", dicts=dicts)
    assert ("読む", "よむ") in [(w.lemma, w.reading) for w in words]


def test_without_dicts_extraction_is_unchanged(tokenizer: Tokenizer) -> None:
    assert content_words(tokenizer, "日本語が話せる") == ["日本語", "話せる"]
