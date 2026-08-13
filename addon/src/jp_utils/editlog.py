"""Append-only record of the collection writes a pipeline run makes.

One JSON object per line (JSONL), one line per note per run-action, so a
five-field enrichment of one note is a single record. Keys are spelled out and
the timestamp is local ISO-8601, so a line reads without a decoder ring; no
field values are stored - the log answers "what was touched, when", not "what
did it say before", since the current content is in Anki and the previous
content is gone.

Kept small by size-based rotation (see :data:`MAX_BYTES`): the live file is
rolled aside to ``<name>.1`` once it grows past the cap and any older ``.1`` is
discarded, so the log costs at most ~2x the cap on disk.

Writing is best-effort: :func:`append` swallows its own failures, because a
logging problem must never break a run that already wrote to the collection.
Pure stdlib and path-injected, so it is tested without Anki
(``ui/run.py`` passes :func:`default_path`).
"""

import json
import os
import time

LOG_NAME = "edits.jsonl"
MAX_BYTES = 512 * 1024


def default_path() -> str:
    """``user_files/edits.jsonl`` inside the installed add-on folder.

    The build ships the package's files at the add-on root (see ``addon/build.py``),
    so this module sits beside them; Anki preserves ``user_files/`` across add-on
    updates, which makes it the right home for a log.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_files", LOG_NAME)


def _now() -> str:
    """Local time as ISO-8601 to the second (``2026-08-12T14:31:05``).

    Local rather than UTC because the only reader is the user, comparing a line
    against when they remember running something.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def note_entry(
    action: str,
    deck: str,
    note_type: str,
    note_id: int,
    card_id: int | None,
    fields: list[str],
    ops: list[str],
) -> dict:
    """One note's record: ``time``, ``action``, ``deck``, ``note_type``,
    ``note_id``/``card_id``, the changed ``fields`` and the ``ops`` responsible.

    ``card_id`` is the note's first card (these actions edit note fields, not a
    single card); it is omitted when the note somehow has no card.
    """
    entry = {
        "time": _now(),
        "action": action,
        "deck": deck,
        "note_type": note_type,
        "note_id": int(note_id),
    }
    if card_id is not None:
        entry["card_id"] = int(card_id)
    entry["fields"] = sorted(set(fields))
    entry["ops"] = sorted({op for op in ops if op})
    return entry


def sort_entry(deck: str, note_type: str, count: int, ops: list[str]) -> dict:
    """One reposition record for a whole (deck, note type): ``cards_moved``.

    Sort ops move new cards rather than editing content, and a sweep can move
    hundreds at once, so they are summarised per run instead of per card.
    """
    return {
        "time": _now(),
        "action": "sort",
        "deck": deck,
        "note_type": note_type,
        "cards_moved": int(count),
        "ops": sorted({op for op in ops if op}),
    }


def append(path: str, entries: list[dict]) -> None:
    """Append ``entries`` to the log (one compact JSON object per line).

    Creates the parent directory on first use and rotates before writing when the
    file is already over the cap. Any failure is swallowed - the collection write
    it records has already happened, and losing a log line is better than
    surfacing an error for it.
    """
    if not entries:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _rotate(path)
        with open(path, "a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 - logging must never break a run
        pass


def _rotate(path: str) -> None:
    """Roll the live log aside to ``<path>.1`` once it exceeds :data:`MAX_BYTES`.

    ``os.replace`` overwrites the previous ``.1``, so exactly one generation of
    history is kept.
    """
    try:
        if os.path.getsize(path) < MAX_BYTES:
            return
    except OSError:
        return  # no file yet (or unreadable): nothing to rotate
    os.replace(path, path + ".1")
