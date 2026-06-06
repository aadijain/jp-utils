"""Append-only personal vocabulary store (vocab.db).

A single SQLite `events` table; a word's current status is a projection over the
latest event per (lemma, reading). Keyed on lemma+reading, never Anki card ids.
History is never mutated (append-only) so the data can be reverted if it
corrupts. This is PERSONAL user data: the db file is gitignored.

The store is created on first open (unlike the read-only dict cache, which may be
absent). A single connection guarded by a lock serves all reads and writes - at
single-user scale lock contention is negligible and this is obviously correct.
"""

import csv
import io
import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from shared.vocab import (
    FilterByStatusResponse,
    RecordEntry,
    VocabAction,
    VocabStatus,
    VocabWord,
    WordStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    lemma   TEXT NOT NULL,
    reading TEXT NOT NULL,
    action  TEXT NOT NULL,
    source  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_key ON events(lemma, reading);
"""

# Latest-event action -> a word's current status. Actions absent here (and any
# absence of events) project to `unknown`; `removed` is an explicit revert.
_ACTION_TO_STATUS = {
    VocabAction.SEEN: WordStatus.SEEN,
    VocabAction.LEARNT: WordStatus.LEARNT,
    VocabAction.IGNORED: WordStatus.IGNORED,
    VocabAction.BLACKLISTED: WordStatus.BLACKLISTED,
    VocabAction.REMOVED: WordStatus.UNKNOWN,
}

# Latest-event actions that mean "the word is recorded / not unknown". `removed`
# (and any absence of events) means the word is unknown again.
_PRESENT = {VocabAction.SEEN, VocabAction.LEARNT, VocabAction.IGNORED, VocabAction.BLACKLISTED}

# The auto progression unknown < seen < learnt. An unforced event is appended ONLY
# when it raises the word's status (no downgrade, no churn) and never over a
# terminal `ignored`/`blacklisted`. A forced event (a deliberate action) bypasses
# both checks.
_AUTO_RANK = {WordStatus.UNKNOWN: 0, WordStatus.SEEN: 1, WordStatus.LEARNT: 2}
_MANUAL_TERMINAL = {WordStatus.IGNORED, WordStatus.BLACKLISTED}


def _status_of(action: str) -> WordStatus:
    try:
        return _ACTION_TO_STATUS.get(VocabAction(action), WordStatus.UNKNOWN)
    except ValueError:  # an action string outside the enum projects to unknown
        return WordStatus.UNKNOWN


# Latest-event row per (lemma, reading).
_CURRENT_SQL = (
    "SELECT lemma, reading, action, source, ts FROM events e1 "
    "WHERE id = (SELECT MAX(id) FROM events e2 "
    "WHERE e2.lemma = e1.lemma AND e2.reading = e1.reading)"
)


def default_db_path() -> Path:
    """Default vocab.db location: backend/data/vocab.db."""
    return Path(__file__).resolve().parents[2] / "data" / "vocab.db"


class VocabStore:
    """Read/write accessor over vocab.db. Store one instance in app state."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @classmethod
    def open(cls, db_path: Path | None = None) -> "VocabStore":
        """Open (creating if absent) the vocab store."""
        db_path = db_path or default_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(db_path)

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _status_map(self) -> dict[tuple[str, str], WordStatus]:
        """Current status per (lemma, reading), from each key's latest event."""
        return {
            (r["lemma"], r["reading"]): _status_of(r["action"]) for r in self._read(_CURRENT_SQL)
        }

    def record(self, entries: Iterable[RecordEntry], force: bool = False) -> int:
        """Append a batch of events; returns the number of rows actually written.

        With ``force`` (a deliberate action: a manual add, an ignore/blacklist, a
        downgrade, a revert) every entry is appended as-is. Without it, entries are
        upgrade-only: a `seen`/`learnt` is appended only when it raises the word's
        status, and never over a terminal `ignored`/`blacklisted` - so the
        latest-event-wins projection never downgrades. Returns fewer than submitted
        when guarded events are skipped.
        """
        entries = list(entries)
        if not entries:
            return 0
        current = {} if force else self._status_map()  # guard unforced events
        ts = datetime.now(UTC).isoformat()
        rows = []
        for e in entries:
            key = (e.lemma, e.reading)
            target = _status_of(e.action)
            if not force:
                cur = current.get(key, WordStatus.UNKNOWN)
                if cur in _MANUAL_TERMINAL:
                    continue  # don't clobber a terminal ignore/blacklist
                if _AUTO_RANK.get(target, 0) <= _AUTO_RANK.get(cur, 0):
                    continue  # not an upgrade -> skip (no downgrade, no churn)
                current[key] = target  # reflect for later entries in the same batch
            rows.append((ts, e.lemma, e.reading, str(e.action), str(e.source)))
        if not rows:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT INTO events (ts, lemma, reading, action, source) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    def current_keys(self) -> set[tuple[str, str]]:
        """The recorded (not-unknown) set of (lemma, reading) keys."""
        return {
            (r["lemma"], r["reading"]) for r in self._read(_CURRENT_SQL) if r["action"] in _PRESENT
        }

    def current_lemmas(self) -> set[str]:
        """The recorded (not-unknown) set of lemmas, ignoring reading.

        The lemma-only projection of :meth:`current_keys` (status != unknown), used
        by n+1 scoring: matching is lemma-only because stored readings are
        dict-preferred while the tokenizer emits Sudachi readings.
        """
        return {r["lemma"] for r in self._read(_CURRENT_SQL) if r["action"] in _PRESENT}

    def filter_by_status(
        self, words: Iterable[VocabWord], statuses: Iterable[WordStatus]
    ) -> FilterByStatusResponse:
        """Keep the subset of `words` whose current status is in `statuses`.

        Empty `statuses` falls back to unknown-only (the new-word default).
        """
        wanted = set(statuses) or {WordStatus.UNKNOWN}
        smap = self._status_map()
        matched = [w for w in words if smap.get((w.lemma, w.reading), WordStatus.UNKNOWN) in wanted]
        return FilterByStatusResponse(matched=matched)

    def status(self) -> VocabStatus:
        events = self._read("SELECT COUNT(*) AS c FROM events")[0]["c"]
        version = self._read("SELECT COALESCE(MAX(id), 0) AS v FROM events")[0]["v"]
        return VocabStatus(count=len(self.current_keys()), events=events, version=version)

    def export(self, fmt: str) -> str:
        """Serialize the current recorded set as JSON or CSV (sorted by key)."""
        rows = sorted(
            (r for r in self._read(_CURRENT_SQL) if r["action"] in _PRESENT),
            key=lambda r: (r["lemma"], r["reading"]),
        )
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["lemma", "reading", "action", "source", "ts"])
            for r in rows:
                writer.writerow([r["lemma"], r["reading"], r["action"], r["source"], r["ts"]])
            return buf.getvalue()
        return json.dumps(
            [
                {
                    "lemma": r["lemma"],
                    "reading": r["reading"],
                    "action": r["action"],
                    "source": r["source"],
                    "ts": r["ts"],
                }
                for r in rows
            ],
            ensure_ascii=False,
            indent=2,
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
