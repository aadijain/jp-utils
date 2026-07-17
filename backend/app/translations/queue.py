"""Async sentence-translation queue (translation-queue.db).

The seam between Anki and an external batch translator. A lookup returns any
finished translation and silently enqueues sentences it has never seen, so the
add-on needs a single round trip; an out-of-process worker drains the pending
set through CSV export/import on its own schedule. Rows are keyed by a content
hash of the normalized sentence (markup/entities/width/whitespace folded away),
so the same sentence re-queried in any form maps to one row and a done row acts
as a permanent cache - re-imports and re-lookups are idempotent.

There is no failed state: the worker owns retries, and an imported row with a
blank translation simply stays pending. The db is derived personal data
(gitignored), kept out of vocab.db so that store's append-only invariants stay
pure. A single connection guarded by a lock serves reads and writes (as
`VocabStore`); at single-user scale lock contention is negligible.
"""

import csv
import hashlib
import html
import io
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from shared.translations import (
    TranslationImportResponse,
    TranslationLookupResponse,
    TranslationQuery,
    TranslationResult,
    TranslationStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    key         TEXT PRIMARY KEY,
    sentence    TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    translation TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    ts_enqueued TEXT NOT NULL,
    ts_done     TEXT
);
"""

# SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999; chunk IN-lists well under it.
_CHUNK = 500

_TAG_RE = re.compile(r"<[^>]+>")

# The export/import CSV columns. `source`/`context` match the worker task's
# template variables by name, so a header-aware run needs no column mapping;
# the import reads the appended `translation`/`notes` output columns.
_EXPORT_COLUMNS = ("key", "source", "context")


def normalize_sentence(text: str) -> str:
    """Fold a sentence to its key form: tags/entities/width/whitespace removed.

    Tags are stripped before entities are unescaped so literal ``&lt;b&gt;`` text
    survives. NFKC folds full/half-width variants; every kind of whitespace
    (including full-width) is dropped so formatting differences can't split keys.
    """
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if not ch.isspace())


def sentence_key(text: str) -> str:
    """Content-address a sentence by its normalized form."""
    return hashlib.sha1(normalize_sentence(text).encode("utf-8")).hexdigest()


def default_db_path() -> Path:
    """Default location: backend/data/translation-queue.db."""
    return Path(__file__).resolve().parents[2] / "data" / "translation-queue.db"


class TranslationQueue:
    """Read/write accessor over translation-queue.db. Hold one on `app.state`."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @classmethod
    def open(cls, db_path: Path | None = None) -> "TranslationQueue":
        """Open (creating if absent) the queue."""
        db_path = db_path or default_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(db_path)

    def _rows_for(self, keys: list[str]) -> dict[str, sqlite3.Row]:
        rows: dict[str, sqlite3.Row] = {}
        for start in range(0, len(keys), _CHUNK):
            chunk = keys[start : start + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            for r in self._conn.execute(
                f"SELECT * FROM translations WHERE key IN ({placeholders})", chunk
            ):
                rows[r["key"]] = r
        return rows

    def lookup(self, queries: Iterable[TranslationQuery]) -> TranslationLookupResponse:
        """Answer each query and enqueue the unknown ones (aligned, batch-first).

        A known key returns its current state; an unknown one is inserted as
        ``pending`` (a sentence normalizing to nothing is answered pending but
        never stored). Duplicate sentences in one batch share a key and are
        enqueued once, first context wins - as across batches.
        """
        queries = list(queries)
        keyed = [(q, sentence_key(q.sentence)) for q in queries]
        unique_keys = list(dict.fromkeys(k for _, k in keyed))
        with self._lock:
            rows = self._rows_for(unique_keys)
            ts = datetime.now(UTC).isoformat()
            inserts = {}
            for query, key in keyed:
                if key in rows or key in inserts or not normalize_sentence(query.sentence):
                    continue
                inserts[key] = (
                    key,
                    query.sentence,
                    query.context,
                    str(TranslationStatus.PENDING),
                    ts,
                )
            if inserts:
                self._conn.executemany(
                    "INSERT INTO translations (key, sentence, context, status, ts_enqueued) "
                    "VALUES (?, ?, ?, ?, ?)",
                    list(inserts.values()),
                )
                self._conn.commit()
        results = []
        for _, key in keyed:
            row = rows.get(key)
            if row is not None and row["status"] == TranslationStatus.DONE:
                results.append(
                    TranslationResult(
                        status=TranslationStatus.DONE,
                        translation=row["translation"],
                        notes=row["notes"],
                    )
                )
            else:
                results.append(TranslationResult(status=TranslationStatus.PENDING))
        return TranslationLookupResponse(results=results)

    def export_pending(self) -> str:
        """The pending rows as a worker-ready CSV (header ``key,source,context``).

        Column names match the worker task's template variables, so a
        header-aware batch run maps them without flags; the ``key`` column rides
        through the worker untouched and drives the import match-back.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, sentence, context FROM translations "
                "WHERE status = ? ORDER BY rowid",  # enqueue order, batch-stable
                (str(TranslationStatus.PENDING),),
            ).fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_EXPORT_COLUMNS)
        for r in rows:
            writer.writerow([r["key"], r["sentence"], r["context"]])
        return buf.getvalue()

    def import_results(self, csv_text: str) -> TranslationImportResponse:
        """Apply a worker output CSV: mark each translated row done.

        The CSV must carry a header with ``key`` and ``translation`` columns (the
        worker appends ``translation``/``notes`` to the exported header). A row
        with a blank translation is skipped and stays pending (the worker retries
        its own errors); an unknown key is skipped too. Re-importing is
        idempotent - a done row is simply overwritten with the same result.
        Raises ``ValueError`` on a malformed CSV / missing columns.
        """
        reader = csv.reader(io.StringIO(csv_text))
        try:
            header = next(reader)
        except (StopIteration, csv.Error) as exc:
            raise ValueError("empty or malformed CSV") from exc
        indexes = {name: i for i, name in enumerate(header)}
        missing = [c for c in ("key", "translation") if c not in indexes]
        if missing:
            raise ValueError(f"CSV header lacks required column(s): {', '.join(missing)}")
        key_i, translation_i = indexes["key"], indexes["translation"]
        notes_i = indexes.get("notes")

        done = skipped = 0
        updates = []
        ts = datetime.now(UTC).isoformat()
        for row in reader:
            if not row or len(row) <= max(key_i, translation_i):
                skipped += 1
                continue
            key, translation = row[key_i], row[translation_i]
            notes = row[notes_i] if notes_i is not None and len(row) > notes_i else ""
            if not key or not translation.strip():
                skipped += 1
                continue
            updates.append((str(TranslationStatus.DONE), translation, notes, ts, key))
        if updates:
            with self._lock:
                known = self._rows_for([u[4] for u in updates])
                matched = [u for u in updates if u[4] in known]
                if matched:
                    self._conn.executemany(
                        "UPDATE translations SET status = ?, translation = ?, notes = ?, "
                        "ts_done = ? WHERE key = ?",
                        matched,
                    )
                    self._conn.commit()
                done = len(matched)
                skipped += len(updates) - len(matched)
        return TranslationImportResponse(done=done, skipped=skipped)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
