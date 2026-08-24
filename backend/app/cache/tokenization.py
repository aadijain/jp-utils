"""Content-addressed tokenization cache (tokenization-cache.db).

Memoizes a sentence's content-word extraction so repeat tokenizations (the n+1
start-sweep, generation) skip Sudachi. Keyed by a sha1 of the *stripped*
sentence text (the add-on removes markup before sending; the split mode is always
C so it is not part of the key); the value is the
stable content-word set (lemma + reading).

Entries are keyed by the sentence ALONE, so a change to the extraction rules is
invisible in the key and a pre-change row is indistinguishable from a fresh one:
:data:`EXTRACTION_VERSION` stamps the file so such a cache is emptied on open
rather than served forever.

This is **derived, disposable infra** - delete the file to rebuild - kept OUT of
`vocab.db` so that store's append-only / personal-data invariants stay pure. It is
cross-cutting state on `app.state`, like the tokenizer and dict cache, owned by
neither `text` nor `vocab`. A single connection guarded by a lock serves reads and
writes (as `VocabStore`); at single-user scale lock contention is negligible.
"""

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path

from shared.vocab import VocabWord

logger = logging.getLogger("jp_utils.backend")

# Bump whenever a change under `app/text/` alters what a content-word extraction
# RETURNS: the POS keep-set or the noun-subtype drops, the purely-katakana rule
# (`text/words.py:is_content`), the deinflection / reading rules a stored
# lemma+reading comes from (`text/inflection.py`), or the rule deciding what a
# lemma collapses to (`text/canonical.py`). A cache stamped with a
# different version - an unstamped one included - is emptied on open. This has
# already bitten once: the katakana filter landed a month after the cache
# shipped, and a third of the live rows kept serving katakana lemmas that
# `is_content` can no longer produce.
EXTRACTION_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tokenization (
    sentence_hash TEXT PRIMARY KEY,
    words         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999; chunk IN-lists well under it.
_CHUNK = 500


def sentence_hash(text: str) -> str:
    """Content-address an (already markup-stripped) sentence."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def default_cache_path() -> Path:
    """Default location: backend/data/tokenization-cache.db."""
    return Path(__file__).resolve().parents[2] / "data" / "tokenization-cache.db"


def _dumps(words: Sequence[VocabWord]) -> str:
    return json.dumps([{"lemma": w.lemma, "reading": w.reading} for w in words], ensure_ascii=False)


def _loads(blob: str) -> list[VocabWord]:
    return [VocabWord(lemma=d["lemma"], reading=d.get("reading", "")) for d in json.loads(blob)]


class TokenizationCache:
    """Read/write accessor over tokenization-cache.db. Hold one on `app.state`."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._discard_stale_entries()

    def _discard_stale_entries(self) -> None:
        """Empty the cache when it was built under different extraction rules.

        A stale row is indistinguishable from a fresh one at lookup time (the key
        is the sentence, nothing else), so dropping the lot is the only sound
        invalidation - and since every entry is re-derivable from its sentence,
        the cost is one re-tokenization each. It doubles as the orphan GC: rows
        for notes that no longer exist go with it.
        """
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'extraction_version'"
        ).fetchone()
        stored = int(row["value"]) if row and row["value"].isdigit() else None
        if stored == EXTRACTION_VERSION:
            return
        discarded = self._conn.execute("SELECT COUNT(*) AS c FROM tokenization").fetchone()["c"]
        if discarded:
            logger.warning(
                "Discarding %d tokenization-cache entries from %s: built under extraction "
                "version %s, this build is %s",
                discarded,
                self._path,
                stored,
                EXTRACTION_VERSION,
            )
        self._conn.execute("DELETE FROM tokenization")
        self._conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('extraction_version', ?)",
            (str(EXTRACTION_VERSION),),
        )
        self._conn.commit()

    @classmethod
    def open(cls, db_path: Path | None = None) -> "TokenizationCache":
        """Open (creating if absent) the cache."""
        db_path = db_path or default_cache_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(db_path)

    def get_many(self, hashes: Iterable[str]) -> dict[str, list[VocabWord]]:
        """Cached content words per known hash; misses are simply absent from the map."""
        keys = list(dict.fromkeys(hashes))  # de-dup, order-preserving
        if not keys:
            return {}
        out: dict[str, list[VocabWord]] = {}
        with self._lock:
            for start in range(0, len(keys), _CHUNK):
                chunk = keys[start : start + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows = self._conn.execute(
                    "SELECT sentence_hash, words FROM tokenization "
                    f"WHERE sentence_hash IN ({placeholders})",
                    chunk,
                ).fetchall()
                for r in rows:
                    out[r["sentence_hash"]] = _loads(r["words"])
        return out

    def put_many(self, entries: Iterable[tuple[str, Sequence[VocabWord]]]) -> None:
        """Upsert `(hash -> words)`. Re-storing a hash overwrites it (idempotent)."""
        rows = [(h, _dumps(words)) for h, words in entries]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO tokenization (sentence_hash, words) VALUES (?, ?) "
                "ON CONFLICT(sentence_hash) DO UPDATE SET words = excluded.words",
                rows,
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
