"""Read-only SQLite cache built from the reference dictionaries.

The source zips are parsed exactly once into an indexed SQLite file
(`build_cache`); requests then do sub-millisecond point lookups via `DictCache`.
The cache is a throwaway derived artifact: delete it and rebuild. Reads use one
read-only connection per thread (FastAPI's sync endpoints run in a threadpool),
created lazily and reused.

CLI: `python -m app.dicts.cache [--force] [--cache PATH]`.
"""

import json
import logging
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.dicts.parsers import (
    parse_jitendex,
    parse_jmdict_furigana,
    parse_jpdb_freq,
)
from app.dicts.paths import DictKind, default_cache_path, resolve_dict_path
from app.text.convert import kata_to_hira

logger = logging.getLogger("jp_utils.backend")

SCHEMA_VERSION = 3  # v3: per-sense structure; examples carry furigana+keyword segments

_SCHEMA = """
CREATE TABLE meanings (
    lemma   TEXT NOT NULL,
    reading TEXT NOT NULL,
    senses  TEXT NOT NULL,
    score   INTEGER NOT NULL,
    seq     INTEGER NOT NULL,
    jlpt    INTEGER
);
CREATE TABLE frequencies (
    term    TEXT NOT NULL,
    reading TEXT NOT NULL,
    rank    INTEGER NOT NULL,
    PRIMARY KEY (term, reading)
);
CREATE TABLE furigana (
    text     TEXT NOT NULL,
    reading  TEXT NOT NULL,
    segments TEXT NOT NULL
);
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_INDEXES = """
CREATE INDEX idx_meanings_lemma ON meanings(lemma);
CREATE INDEX idx_furigana_key ON furigana(text, reading);
"""

# Logical table names exposed in status / readiness checks.
DICT_TABLES = ("meanings", "frequencies", "furigana")


@dataclass
class DictReport:
    """Per-dictionary outcome of a cache build."""

    name: str
    present: bool
    entries: int
    source: str | None


# ── Build ────────────────────────────────────────────────────────────────────


def _insert_meanings(conn: sqlite3.Connection, path: Path) -> int:
    rows = (
        (r.lemma, r.reading, json.dumps(r.senses, ensure_ascii=False), r.score, r.seq, r.jlpt)
        for r in parse_jitendex(path)
    )
    return _executemany(conn, "INSERT INTO meanings VALUES (?, ?, ?, ?, ?, ?)", rows)


def _insert_frequencies(conn: sqlite3.Connection, path: Path) -> int:
    # Bucket per (term, reading) so homograph readings keep distinct ranks
    # (人 ひと=71 / にん=564). JPDB has up to two rows per (term, reading): the
    # kanji-spelling rank and the kana-spelling rank (㋕); keep the best (lowest)
    # rank within each form, preferring kanji-form over kana-form.
    kanji: dict[tuple[str, str], int] = {}
    kana: dict[tuple[str, str], int] = {}
    for r in parse_jpdb_freq(path):
        key = (r.term, r.reading)
        bucket = kana if r.is_kana_form else kanji
        prev = bucket.get(key)
        if prev is None or r.rank < prev:
            bucket[key] = r.rank
    merged = dict(kana)
    merged.update(kanji)  # kanji-form wins where both exist
    rows = ((term, reading, rank) for (term, reading), rank in merged.items())
    return _executemany(conn, "INSERT INTO frequencies VALUES (?, ?, ?)", rows)


def _insert_furigana(conn: sqlite3.Connection, path: Path) -> int:
    rows = (
        (r.text, r.reading, json.dumps(r.segments, ensure_ascii=False))
        for r in parse_jmdict_furigana(path)
    )
    return _executemany(conn, "INSERT INTO furigana VALUES (?, ?, ?)", rows)


def _executemany(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> int:
    cur = conn.executemany(sql, rows)
    return cur.rowcount if cur.rowcount != -1 else 0


_BUILDERS = {
    DictKind.JITENDEX: ("meanings", _insert_meanings),
    DictKind.JPDB_FREQ: ("frequencies", _insert_frequencies),
    DictKind.JMDICT_FURIGANA: ("furigana", _insert_furigana),
}


def build_cache(cache_path: Path | None = None, *, force: bool = False) -> list[DictReport]:
    """Parse whatever source dicts are present into a fresh SQLite cache.

    Returns a per-dictionary report. Raises FileExistsError if the cache exists
    and `force` is not set. Missing source dicts are skipped (reported absent),
    not errors: the service runs degraded until they're fetched.
    """
    cache_path = cache_path or default_cache_path()
    if cache_path.exists():
        if not force:
            raise FileExistsError(f"cache exists: {cache_path} (pass force=True to rebuild)")
        cache_path.unlink()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(cache_path)
    reports: list[DictReport] = []
    try:
        conn.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
        conn.executescript(_SCHEMA)
        for kind, (name, builder) in _BUILDERS.items():
            source = resolve_dict_path(kind)
            if source is None:
                reports.append(DictReport(name=name, present=False, entries=0, source=None))
                continue
            count = builder(conn, source)
            conn.execute(
                "INSERT OR REPLACE INTO meta VALUES (?, ?)",
                (f"{name}.source", str(source)),
            )
            reports.append(DictReport(name=name, present=True, entries=count, source=str(source)))
        conn.executescript(_INDEXES)
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)",
            ("built_at", datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return reports


# ── Read ─────────────────────────────────────────────────────────────────────


def _stored_schema_version(cache_path: Path) -> int | None:
    """The schema version a cache file was built with, or None if unreadable."""
    try:
        conn = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return None


@dataclass
class DictTableStatus:
    name: str
    loaded: bool
    entries: int


class DictCache:
    """Read-only accessor over a built cache. Store one instance in app state."""

    def __init__(self, cache_path: Path) -> None:
        self._path = cache_path
        self._local = threading.local()

    @classmethod
    def open(cls, cache_path: Path | None = None) -> "DictCache | None":
        """Return a cache accessor, or None when no usable cache exists.

        A cache file whose stored schema version differs from the code's (or that
        isn't a readable cache at all) is treated the same as a missing one: the
        service runs degraded until the cache is rebuilt, instead of erroring on
        lookups against tables the file doesn't have.
        """
        cache_path = cache_path or default_cache_path()
        if not cache_path.is_file():
            return None
        stored = _stored_schema_version(cache_path)
        if stored != SCHEMA_VERSION:
            logger.warning(
                "Ignoring dictionary cache %s: schema version %s != expected %s; "
                "rebuild it with `python -m app.dicts --force`",
                cache_path,
                stored,
                SCHEMA_VERSION,
            )
            return None
        return cls(cache_path)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def status(self) -> list[DictTableStatus]:
        conn = self._conn()
        out: list[DictTableStatus] = []
        for name in DICT_TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            out.append(DictTableStatus(name=name, loaded=count > 0, entries=count))
        return out

    def lookup_meaning(self, lemma: str, reading: str | None = None) -> list[dict]:
        """Meaning entries for a lemma, best (highest score) first."""
        conn = self._conn()
        if reading is None:
            cur = conn.execute(
                "SELECT reading, senses, score, seq, jlpt FROM meanings "
                "WHERE lemma = ? ORDER BY score DESC, seq ASC",
                (lemma,),
            )
        else:
            cur = conn.execute(
                "SELECT reading, senses, score, seq, jlpt FROM meanings "
                "WHERE lemma = ? AND reading = ? ORDER BY score DESC, seq ASC",
                (lemma, reading),
            )
        return [
            {
                "lemma": lemma,
                "reading": row["reading"],
                "senses": json.loads(row["senses"]),
                "score": row["score"],
                "seq": row["seq"],
                "jlpt": row["jlpt"],
            }
            for row in cur.fetchall()
        ]

    def lookup_frequency(self, term: str, reading: str | None = None) -> int | None:
        """Frequency rank for a term (lower = more frequent), or None.

        With a reading, return that reading's rank (homographs differ); readings
        are compared in hiragana space. If the (term, reading) pair isn't ranked,
        fall back to the hiragana kana-form entry (where term == reading). Without
        a reading, return the term's best rank across all its readings.
        """
        conn = self._conn()
        if reading:
            hira = kata_to_hira(reading)
            row = conn.execute(
                "SELECT rank FROM frequencies WHERE term = ? AND reading = ?",
                (term, hira),
            ).fetchone()
            if row:
                return row["rank"]
            term = hira  # kana-form fallback: resolve via the hiragana kana entry
        row = conn.execute(
            "SELECT MIN(rank) AS rank FROM frequencies WHERE term = ?", (term,)
        ).fetchone()
        return row["rank"] if row and row["rank"] is not None else None

    def lookup_furigana(self, text: str, reading: str) -> list[dict] | None:
        """rt-bearing furigana segments for a (text, reading) pair, or None."""
        row = (
            self._conn()
            .execute(
                "SELECT segments FROM furigana WHERE text = ? AND reading = ?",
                (text, reading),
            )
            .fetchone()
        )
        return json.loads(row["segments"]) if row else None

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build the read-only dictionary cache.")
    parser.add_argument("--force", action="store_true", help="rebuild if the cache exists")
    parser.add_argument("--cache", type=Path, default=None, help="cache db path")
    args = parser.parse_args()

    try:
        reports = build_cache(args.cache, force=args.force)
    except FileExistsError as exc:
        print(f"[dicts] {exc}")
        return 1

    print(f"[dicts] cache built at {args.cache or default_cache_path()}")
    for r in reports:
        if r.present:
            print(f"  {r.name}: {r.entries} entries  <- {r.source}")
        else:
            print(f"  {r.name}: MISSING (source dict not found; service runs degraded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
