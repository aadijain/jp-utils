import csv
import io
from pathlib import Path

import pytest

from app.translations import TranslationQueue, sentence_key
from shared.translations import TranslationQuery


@pytest.fixture
def queue(tmp_path: Path):
    q = TranslationQueue.open(tmp_path / "translation-queue.db")
    yield q
    q.close()


def _export_rows(q: TranslationQueue) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(q.export_pending())))


def _worker_csv(rows: list[tuple[str, str, str]]) -> str:
    """A worker output CSV: the exported header + translation/notes columns."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["key", "source", "context", "translation", "notes"])
    for key, translation, notes in rows:
        writer.writerow([key, "", "", translation, notes])
    return buf.getvalue()


def test_lookup_enqueues_and_roundtrip(queue: TranslationQueue) -> None:
    resp = queue.lookup([TranslationQuery(sentence="知るか！俺は新人だ！", context="Don't know!")])
    assert [r.status for r in resp.results] == ["pending"]

    rows = _export_rows(queue)
    assert len(rows) == 1
    assert rows[0]["source"] == "知るか！俺は新人だ！"
    assert rows[0]["context"] == "Don't know!"

    imported = queue.import_results(
        _worker_csv([(rows[0]["key"], "How should I know?! I'm new here!", "note line")])
    )
    assert (imported.done, imported.skipped) == (1, 0)

    resp = queue.lookup([TranslationQuery(sentence="知るか！俺は新人だ！")])
    (result,) = resp.results
    assert result.status == "done"
    assert result.translation == "How should I know?! I'm new here!"
    assert result.notes == "note line"
    assert _export_rows(queue) == []  # done rows leave the pending export


def test_key_normalization_folds_markup_and_whitespace(queue: TranslationQueue) -> None:
    variants = [
        "<b>彗星</b>&nbsp;見える かな。",
        "彗星 見えるかな。",
        "彗星　見えるかな。",
    ]
    assert len({sentence_key(v) for v in variants}) == 1
    queue.lookup([TranslationQuery(sentence=v) for v in variants])
    assert len(_export_rows(queue)) == 1  # one shared row, first context wins


def test_lookup_results_align_with_queries(queue: TranslationQueue) -> None:
    first = TranslationQuery(sentence="お前が悪い")
    queue.lookup([first])
    key = _export_rows(queue)[0]["key"]
    queue.import_results(_worker_csv([(key, "You're the one in the wrong.", "")]))

    resp = queue.lookup([TranslationQuery(sentence="はい 解散"), first])
    assert [r.status for r in resp.results] == ["pending", "done"]
    assert resp.results[1].translation == "You're the one in the wrong."


def test_import_blank_translation_stays_pending(queue: TranslationQueue) -> None:
    queue.lookup([TranslationQuery(sentence="そうや")])
    key = _export_rows(queue)[0]["key"]

    imported = queue.import_results(_worker_csv([(key, "  ", "")]))
    assert (imported.done, imported.skipped) == (0, 1)
    assert len(_export_rows(queue)) == 1  # still pending

    imported = queue.import_results(_worker_csv([("no-such-key", "hello", "")]))
    assert (imported.done, imported.skipped) == (0, 1)


def test_import_requires_key_and_translation_columns(queue: TranslationQueue) -> None:
    with pytest.raises(ValueError):
        queue.import_results("")
    with pytest.raises(ValueError):
        queue.import_results("key,source\nabc,def\n")


def test_empty_sentence_not_enqueued(queue: TranslationQueue) -> None:
    resp = queue.lookup([TranslationQuery(sentence="<b> </b>&nbsp;")])
    assert [r.status for r in resp.results] == ["pending"]
    assert _export_rows(queue) == []


def test_reimport_is_idempotent(queue: TranslationQueue) -> None:
    queue.lookup([TranslationQuery(sentence="好きな柄とかあるの？")])
    key = _export_rows(queue)[0]["key"]
    body = _worker_csv([(key, "Got any patterns you like?", "n")])
    queue.import_results(body)
    queue.import_results(body)
    (result,) = queue.lookup([TranslationQuery(sentence="好きな柄とかあるの？")]).results
    assert (result.status, result.translation) == ("done", "Got any patterns you like?")
