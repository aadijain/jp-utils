import csv
import io
import json

from app.vocab import VocabStore
from shared.vocab import RecordEntry, VocabAction, VocabSource, VocabWord, WordStatus


def test_record_and_current_keys(vocab_store: VocabStore) -> None:
    n = vocab_store.record(
        [
            RecordEntry(lemma="食べる", reading="たべる"),
            RecordEntry(lemma="水", reading="みず"),
        ]
    )
    assert n == 2
    assert vocab_store.current_keys() == {("食べる", "たべる"), ("水", "みず")}


def test_filter_lemma_only_excludes_removed(vocab_store: VocabStore) -> None:
    # A removed lemma projects back to unknown, so the lemma-only match keeps it.
    vocab_store.record([RecordEntry(lemma="水", reading="みず")])
    vocab_store.record(
        [RecordEntry(lemma="水", reading="みず", action=VocabAction.REMOVED)], force=True
    )
    query = [VocabWord("水", "みず")]
    assert (
        vocab_store.filter_by_status(query, [WordStatus.UNKNOWN], match_lemma_only=True).matched
        == query
    )


def test_seen_counts_as_known(vocab_store: VocabStore) -> None:
    # A `seen` word (sentence reviewed, no word card yet) is known, not unknown.
    vocab_store.record(
        [RecordEntry(lemma="水", reading="みず", action=VocabAction.SEEN, source=VocabSource.ANKI)]
    )
    assert ("水", "みず") in vocab_store.current_keys()
    # default filter (unknown-only) excludes it; {unknown, seen} keeps it.
    assert (
        vocab_store.filter_by_status([VocabWord("水", "みず")], [WordStatus.UNKNOWN]).matched == []
    )
    assert vocab_store.filter_by_status(
        [VocabWord("水", "みず")], [WordStatus.UNKNOWN, WordStatus.SEEN]
    ).matched == [VocabWord("水", "みず")]


def test_filter_defaults_to_unknown_only(vocab_store: VocabStore) -> None:
    vocab_store.record([RecordEntry(lemma="水", reading="みず")])
    result = vocab_store.filter_by_status(
        [VocabWord(lemma="水", reading="みず"), VocabWord(lemma="火", reading="ひ")],
        [WordStatus.UNKNOWN],
    )
    assert result.matched == [VocabWord(lemma="火", reading="ひ")]


def test_filter_by_status_set(vocab_store: VocabStore) -> None:
    vocab_store.record(
        [
            RecordEntry(
                lemma="水", reading="みず", action=VocabAction.SEEN, source=VocabSource.ANKI
            ),
            RecordEntry(lemma="火", reading="ひ", action=VocabAction.LEARNT),
        ]
    )
    words = [VocabWord("水", "みず"), VocabWord("火", "ひ"), VocabWord("木", "き")]
    # {unknown, seen} keeps the unknown (木) and the seen (水); drops the learnt (火).
    result = vocab_store.filter_by_status(words, [WordStatus.UNKNOWN, WordStatus.SEEN])
    assert result.matched == [VocabWord("水", "みず"), VocabWord("木", "き")]


def test_filter_lemma_only_ignores_reading_mismatch(vocab_store: VocabStore) -> None:
    # 人 is learnt under the dict-preferred reading ひと; a query carrying Sudachi's
    # じん would miss the exact (lemma, reading) key and wrongly look unknown.
    vocab_store.record([RecordEntry(lemma="人", reading="ひと", action=VocabAction.LEARNT)])
    query = [VocabWord("人", "じん")]

    # Exact-key match: the reading mismatch surfaces 人 as unknown.
    assert vocab_store.filter_by_status(query, [WordStatus.UNKNOWN]).matched == query
    # Lemma-only match: 人 is recognized as learnt regardless of reading, so it is
    # excluded from {unknown, seen} (generation never regenerates it).
    matched = vocab_store.filter_by_status(
        query, [WordStatus.UNKNOWN, WordStatus.SEEN], match_lemma_only=True
    ).matched
    assert matched == []


def test_filter_lemma_only_collapses_to_most_advanced_reading(vocab_store: VocabStore) -> None:
    # One reading seen, another learnt -> the lemma collapses to learnt (excluded).
    vocab_store.record(
        [
            RecordEntry(
                lemma="人", reading="ひと", action=VocabAction.SEEN, source=VocabSource.ANKI
            ),
            RecordEntry(lemma="人", reading="じん", action=VocabAction.LEARNT),
        ]
    )
    matched = vocab_store.filter_by_status(
        [VocabWord("人", "")], [WordStatus.UNKNOWN, WordStatus.SEEN], match_lemma_only=True
    ).matched
    assert matched == []


def test_ignored_and_blacklisted_count_as_not_new(vocab_store: VocabStore) -> None:
    # ignored particles / blacklisted words must NOT show up as unknown (kept out of n+1).
    vocab_store.record(
        [
            RecordEntry(lemma="は", reading="は", action=VocabAction.IGNORED),
            RecordEntry(lemma="嫌", reading="いや", action=VocabAction.BLACKLISTED),
        ],
        force=True,
    )
    result = vocab_store.filter_by_status(
        [VocabWord("は", "は"), VocabWord("嫌", "いや")], [WordStatus.UNKNOWN]
    )
    assert result.matched == []


def test_removed_reverts_to_unknown(vocab_store: VocabStore) -> None:
    vocab_store.record([RecordEntry(lemma="水", reading="みず")])
    vocab_store.record(
        [RecordEntry(lemma="水", reading="みず", action=VocabAction.REMOVED)], force=True
    )
    # latest event wins -> the word is unknown again
    assert vocab_store.current_keys() == set()
    assert vocab_store.filter_by_status(
        [VocabWord("水", "みず")], [WordStatus.UNKNOWN]
    ).matched == [VocabWord("水", "みず")]


def test_reading_disambiguates_key(vocab_store: VocabStore) -> None:
    vocab_store.record([RecordEntry(lemma="人", reading="ひと")])
    # same lemma, different reading is a different key -> still unknown
    assert vocab_store.filter_by_status(
        [VocabWord("人", "じん")], [WordStatus.UNKNOWN]
    ).matched == [VocabWord("人", "じん")]


# --- emit-on-upgrade-only guard (unforced events) ---


def test_unforced_seen_does_not_downgrade_learnt(vocab_store: VocabStore) -> None:
    vocab_store.record([RecordEntry(lemma="水", reading="みず", action=VocabAction.LEARNT)])
    # the sweep re-sees the word in a sentence; an unforced `seen` must NOT downgrade it.
    n = vocab_store.record(
        [RecordEntry(lemma="水", reading="みず", action=VocabAction.SEEN, source=VocabSource.ANKI)]
    )
    assert n == 0
    assert vocab_store._status_map()[("水", "みず")] == WordStatus.LEARNT


def test_unforced_does_not_clobber_terminal(vocab_store: VocabStore) -> None:
    vocab_store.record(
        [RecordEntry(lemma="は", reading="は", action=VocabAction.IGNORED)], force=True
    )
    n = vocab_store.record(
        [RecordEntry(lemma="は", reading="は", action=VocabAction.SEEN, source=VocabSource.ANKI)]
    )
    assert n == 0
    assert vocab_store._status_map()[("は", "は")] == WordStatus.IGNORED


def test_unforced_upgrades_and_dedupes(vocab_store: VocabStore) -> None:
    # unknown -> seen applies; a repeat seen is skipped; seen -> learnt applies.
    seen = RecordEntry(lemma="水", reading="みず", action=VocabAction.SEEN, source=VocabSource.ANKI)
    learnt = RecordEntry(
        lemma="水", reading="みず", action=VocabAction.LEARNT, source=VocabSource.ANKI
    )
    assert vocab_store.record([seen]) == 1
    assert vocab_store.record([seen]) == 0
    assert vocab_store.record([learnt]) == 1
    assert vocab_store._status_map()[("水", "みず")] == WordStatus.LEARNT


def test_force_applies_directly(vocab_store: VocabStore) -> None:
    # force is deliberate: it bypasses the guard and may even downgrade.
    vocab_store.record([RecordEntry(lemma="水", reading="みず", action=VocabAction.LEARNT)])
    n = vocab_store.record(
        [RecordEntry(lemma="水", reading="みず", action=VocabAction.SEEN)], force=True
    )
    assert n == 1
    assert vocab_store._status_map()[("水", "みず")] == WordStatus.SEEN


def test_forced_noop_is_not_appended(vocab_store: VocabStore) -> None:
    # The add-on re-posts every tag-forced event on each sweep by design. A forced
    # event that restates the current status must not grow the table.
    ignored = RecordEntry(
        lemma="は", reading="は", action=VocabAction.IGNORED, source=VocabSource.ANKI
    )
    assert vocab_store.record([ignored], force=True) == 1
    assert vocab_store.record([ignored], force=True) == 0
    assert vocab_store.record([ignored], force=True) == 0
    assert vocab_store.status().events == 1
    assert vocab_store._status_map()[("は", "は")] == WordStatus.IGNORED


def test_forced_noop_skip_does_not_block_a_real_change(vocab_store: VocabStore) -> None:
    # The no-op skip is status equality only - a forced downgrade still applies.
    vocab_store.record([RecordEntry(lemma="水", reading="みず", action=VocabAction.LEARNT)])
    same = RecordEntry(lemma="水", reading="みず", action=VocabAction.LEARNT)
    assert vocab_store.record([same], force=True) == 0
    down = RecordEntry(lemma="水", reading="みず", action=VocabAction.SEEN)
    assert vocab_store.record([down], force=True) == 1
    assert vocab_store._status_map()[("水", "みず")] == WordStatus.SEEN


def test_forced_removed_on_an_unknown_word_is_a_noop(vocab_store: VocabStore) -> None:
    # `removed` projects to unknown, which is what an unrecorded word already is.
    n = vocab_store.record(
        [RecordEntry(lemma="猫", reading="ねこ", action=VocabAction.REMOVED)], force=True
    )
    assert n == 0
    assert vocab_store.status().events == 0


def test_forced_batch_dedupes_within_itself(vocab_store: VocabStore) -> None:
    # Two cards tagged for the same word in one sweep -> one row, not two.
    entry = RecordEntry(
        lemma="は", reading="は", action=VocabAction.IGNORED, source=VocabSource.ANKI
    )
    assert vocab_store.record([entry, entry], force=True) == 1


def test_status_counts(vocab_store: VocabStore) -> None:
    vocab_store.record([RecordEntry(lemma="水", reading="みず")])
    vocab_store.record(
        [RecordEntry(lemma="水", reading="みず", action=VocabAction.REMOVED)], force=True
    )
    status = vocab_store.status()
    assert status.events == 2  # both rows kept (append-only)
    assert status.count == 0  # but the word is currently removed
    assert status.version == 2


def test_current_words_reports_status(vocab_store: VocabStore) -> None:
    # current_words backs the one-shot katakana backfill script: latest status per key.
    vocab_store.record(
        [RecordEntry(lemma="水", reading="みず", action=VocabAction.SEEN, source=VocabSource.ANKI)]
    )
    vocab_store.record([RecordEntry(lemma="火", reading="ひ", action=VocabAction.LEARNT)])
    assert set(vocab_store.current_words()) == {
        ("水", "みず", WordStatus.SEEN),
        ("火", "ひ", WordStatus.LEARNT),
    }


def test_export_json_and_csv(vocab_store: VocabStore) -> None:
    vocab_store.record(
        [
            RecordEntry(
                lemma="水", reading="みず", action=VocabAction.SEEN, source=VocabSource.ANKI
            ),
            RecordEntry(lemma="火", reading="ひ"),
        ]
    )
    data = json.loads(vocab_store.export("json"))
    assert [d["lemma"] for d in data] == ["水", "火"]  # sorted by key
    assert data[0]["source"] == "anki"

    rows = list(csv.reader(io.StringIO(vocab_store.export("csv"))))
    assert rows[0] == ["lemma", "reading", "action", "source", "ts"]
    assert [r[0] for r in rows[1:]] == ["水", "火"]


def test_version_matches_status_without_projecting_every_key(tmp_path) -> None:
    """Recording a batch and stamping an n+1 sort want the version, not the count."""
    store = VocabStore.open(tmp_path / "vocab.db")
    store.record([RecordEntry(lemma="猫", reading="ねこ", action=VocabAction.SEEN, source="anki")])
    store.record(
        [RecordEntry(lemma="犬", reading="いぬ", action=VocabAction.LEARNT, source="anki")]
    )

    assert store.version() == store.status().version
    store.close()


def test_status_counts_only_recorded_words(tmp_path) -> None:
    store = VocabStore.open(tmp_path / "vocab.db")
    store.record([RecordEntry(lemma="猫", reading="ねこ", action=VocabAction.SEEN, source="anki")])
    store.record([RecordEntry(lemma="犬", reading="いぬ", action=VocabAction.SEEN, source="anki")])
    # A `removed` latest event takes the word back out of the recorded set.
    store.record(
        [RecordEntry(lemma="犬", reading="いぬ", action=VocabAction.REMOVED, source="manual")],
        force=True,
    )

    status = store.status()
    assert status.count == 1  # 猫 only
    assert status.events == 3  # but every event is still on record
    store.close()
