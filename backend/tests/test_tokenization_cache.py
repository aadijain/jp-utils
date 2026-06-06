from pathlib import Path

import pytest

from app.cache import tokenization
from app.cache.tokenization import TokenizationCache, sentence_hash
from shared.vocab import VocabWord


@pytest.fixture
def cache(tmp_path: Path) -> TokenizationCache:
    return TokenizationCache.open(tmp_path / "tok.db")


def test_sentence_hash_is_deterministic_and_distinct() -> None:
    assert sentence_hash("猫が魚を食べる") == sentence_hash("猫が魚を食べる")
    assert sentence_hash("猫") != sentence_hash("犬")


def test_round_trip(cache: TokenizationCache) -> None:
    words = [VocabWord(lemma="猫", reading="ねこ"), VocabWord(lemma="魚", reading="さかな")]
    h = sentence_hash("猫が魚")
    cache.put_many([(h, words)])
    assert cache.get_many([h]) == {h: words}


def test_miss_is_absent(cache: TokenizationCache) -> None:
    assert cache.get_many([sentence_hash("未知")]) == {}


def test_empty_inputs(cache: TokenizationCache) -> None:
    assert cache.get_many([]) == {}
    cache.put_many([])  # no-op, must not raise


def test_overwrite_keeps_latest(cache: TokenizationCache) -> None:
    h = sentence_hash("x")
    cache.put_many([(h, [VocabWord(lemma="旧")])])
    cache.put_many([(h, [VocabWord(lemma="新", reading="しん")])])
    assert cache.get_many([h]) == {h: [VocabWord(lemma="新", reading="しん")]}


def test_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "tok.db"
    h = sentence_hash("永続")
    first = TokenizationCache.open(path)
    first.put_many([(h, [VocabWord(lemma="永続", reading="えいぞく")])])
    first.close()

    reopened = TokenizationCache.open(path)
    assert reopened.get_many([h]) == {h: [VocabWord(lemma="永続", reading="えいぞく")]}
    reopened.close()


def test_get_many_spans_chunks(cache: TokenizationCache, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tokenization, "_CHUNK", 2)
    entries = [(sentence_hash(str(i)), [VocabWord(lemma=str(i))]) for i in range(5)]
    cache.put_many(entries)
    got = cache.get_many([h for h, _ in entries])
    assert got == dict(entries)


def test_open_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "tok.db"
    cache = TokenizationCache.open(nested)
    assert nested.exists()
    cache.close()
