"""Tests for the pipeline edit log (pure; no Anki - the path is injected)."""

import json
import os
import re

from jp_utils import editlog


def _lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_note_entry_shape() -> None:
    entry = editlog.note_entry(
        "field", "Mining", "Lapis", 1712000000001, 1712000000002, ["Reading"], ["word-reading"]
    )
    assert entry["action"] == "field"
    assert entry["deck"] == "Mining"
    assert entry["note_type"] == "Lapis"
    assert entry["note_id"] == 1712000000001
    assert entry["card_id"] == 1712000000002
    assert entry["fields"] == ["Reading"]
    assert entry["ops"] == ["word-reading"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", entry["time"])


def test_note_entry_dedups_and_drops_missing_card() -> None:
    entry = editlog.note_entry(
        "field", "Mining", "Lapis", 1, None, ["B", "A", "B"], ["pitch", "", "pitch"]
    )
    assert entry["fields"] == ["A", "B"]
    assert entry["ops"] == ["pitch"]
    assert "card_id" not in entry  # a note with no card logs no card id


def test_sort_entry_is_a_per_run_summary() -> None:
    entry = editlog.sort_entry("Mining", "Lapis", 137, ["int-sort"])
    assert entry["action"] == "sort"
    assert entry["cards_moved"] == 137
    assert "note_id" not in entry  # moves are summarised, not logged per card


def test_append_writes_one_compact_line_per_entry(tmp_path) -> None:
    path = str(tmp_path / "user_files" / "edits.jsonl")
    editlog.append(path, [editlog.note_entry("field", "D", "N", 1, 2, ["F"], ["op"])])
    editlog.append(path, [editlog.sort_entry("D", "N", 3, ["int-sort"])])

    raw = open(path, encoding="utf-8").read()
    assert ", " not in raw  # compact separators keep the file small
    entries = _lines(path)
    assert [e["action"] for e in entries] == ["field", "sort"]


def test_append_keeps_unicode_readable(tmp_path) -> None:
    path = str(tmp_path / "edits.jsonl")
    editlog.append(path, [editlog.note_entry("field", "採掘", "Lapis", 1, 2, ["表現"], ["pitch"])])
    assert "採掘" in open(path, encoding="utf-8").read()


def test_append_of_nothing_creates_no_file(tmp_path) -> None:
    path = str(tmp_path / "edits.jsonl")
    editlog.append(path, [])
    assert not os.path.exists(path)


def test_rotation_rolls_the_live_file_aside_once_over_the_cap(tmp_path) -> None:
    path = str(tmp_path / "edits.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x" * (editlog.MAX_BYTES + 1))

    editlog.append(path, [editlog.note_entry("field", "D", "N", 1, 2, ["F"], ["op"])])

    assert os.path.exists(path + ".1")
    assert len(_lines(path)) == 1  # the live file restarts from the rotation


def test_rotation_keeps_only_one_old_generation(tmp_path) -> None:
    path = str(tmp_path / "edits.jsonl")
    for marker in ("first", "second"):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f'{{"action":"{marker}"}}\n' + "x" * editlog.MAX_BYTES)
        editlog.append(path, [editlog.note_entry("field", "D", "N", 1, 2, ["F"], ["op"])])

    assert open(path + ".1", encoding="utf-8").read().startswith('{"action":"second"}')
    assert not os.path.exists(path + ".2")


def test_append_swallows_write_failures(tmp_path) -> None:
    # A path whose parent is a FILE cannot be created: logging must not raise.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    editlog.append(str(blocker / "edits.jsonl"), [editlog.sort_entry("D", "N", 1, ["int-sort"])])


def test_default_path_lives_in_user_files() -> None:
    path = editlog.default_path()
    assert path.endswith(os.path.join("user_files", "edits.jsonl"))
    assert os.path.isabs(path)
