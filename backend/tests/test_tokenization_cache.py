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


def test_batch_extraction_touches_the_cache_once(tokenizer, tmp_path) -> None:
    """The batch form must not degrade into a query + commit per sentence."""
    from app.text.words import content_words_batch

    cache = TokenizationCache.open(tmp_path / "tok.db")
    gets, puts = [], []
    real_get, real_put = cache.get_many, cache.put_many
    cache.get_many = lambda h: (gets.append(list(h)), real_get(h))[1]  # type: ignore[method-assign]
    cache.put_many = lambda e: (puts.append(list(e)), real_put(e))[1]  # type: ignore[method-assign]

    texts = ["猫が魚を食べた", "犬が走る", "猫が魚を食べた"]  # third repeats the first
    out = content_words_batch(tokenizer, texts, cache=cache)

    assert out[0] == out[2]  # repeated text resolves to the same words
    assert len(gets) == 1 and len(gets[0]) == 3  # one read for the whole batch
    assert len(puts) == 1 and len(puts[0]) == 2  # one write, deduped by content hash
    cache.close()


def test_entries_survive_a_reopen_at_the_same_version(tmp_path: Path) -> None:
    """The stamp must not cost a rebuild on every restart."""
    path = tmp_path / "tok.db"
    h = sentence_hash("同版")
    first = TokenizationCache.open(path)
    first.put_many([(h, [VocabWord(lemma="同版", reading="どうはん")])])
    first.close()

    reopened = TokenizationCache.open(path)
    assert reopened.get_many([h]) != {}
    reopened.close()


def test_entries_from_another_extraction_version_are_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rule change (signalled by a version bump) must invalidate every entry."""
    path = tmp_path / "tok.db"
    h = sentence_hash("テスト")
    first = TokenizationCache.open(path)
    first.put_many([(h, [VocabWord(lemma="テスト", reading="てすと")])])
    first.close()

    monkeypatch.setattr(tokenization, "EXTRACTION_VERSION", tokenization.EXTRACTION_VERSION + 1)
    reopened = TokenizationCache.open(path)
    assert reopened.get_many([h]) == {}
    reopened.close()

    # ...and the new version is stamped, so the next open keeps what it writes.
    again = TokenizationCache.open(path)
    again.put_many([(h, [VocabWord(lemma="テスト", reading="てすと")])])
    again.close()
    third = TokenizationCache.open(path)
    assert third.get_many([h]) != {}
    third.close()


def test_an_unstamped_cache_is_discarded(tmp_path: Path) -> None:
    """A cache predating the stamp carries pre-change extractions - drop it."""
    import sqlite3

    path = tmp_path / "tok.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tokenization (sentence_hash TEXT PRIMARY KEY, words TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO tokenization VALUES (?, ?)",
        (sentence_hash("ゲーム"), '[{"lemma": "ゲーム", "reading": "げーむ"}]'),
    )
    conn.commit()
    conn.close()

    cache = TokenizationCache.open(path)
    assert cache.get_many([sentence_hash("ゲーム")]) == {}
    cache.close()
