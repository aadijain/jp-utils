"""Meaning lookup over the jitendex cache.

Returns the cache's per-headword entries best-first (entries[0] is the primary,
highest-priority sense; the rest are alternates), each carrying its per-sense
structure (glosses, part-of-speech, example sentences). An optional reading
filters to matching entries; readings are compared in hiragana space so katakana
input (e.g. the tokenizer's reading) and katakana headwords (loanwords) both
match. ``all_readings`` always lists every distinct reading of the lemma (from
the unfiltered rows), so a consumer can render an "all readings" line without a
second lookup.

The lemma is looked up **as written first** - a surface that is already a
headword is the right entry, and going through the deinflected form
unconditionally would flatten homograph readings. Only a miss is retried against
the deinflected key, so an inflected word field still gets a definition. The
result echoes whichever key answered.
"""

from app.dicts import DictCache
from app.text.convert import kata_to_hira
from app.text.normalize import deinflected_key
from app.text.tokenizer import Tokenizer
from shared.text import (
    ExampleSegment,
    MeaningEntry,
    MeaningExample,
    MeaningQuery,
    MeaningResult,
    MeaningSense,
)


def _to_example(ex: dict) -> MeaningExample:
    return MeaningExample(
        ja=ex.get("ja", ""),
        en=ex.get("en", ""),
        segments=[
            ExampleSegment(
                text=s.get("text", ""),
                reading=s.get("reading", ""),
                keyword=bool(s.get("kw")),
            )
            for s in ex.get("segments", [])
        ],
    )


def _to_sense(sense: dict) -> MeaningSense:
    return MeaningSense(
        glosses=sense.get("glosses", []),
        pos=sense.get("pos", []),
        examples=[_to_example(ex) for ex in sense.get("examples", [])],
    )


def _entries(
    cache: DictCache, lemma: str, reading: str | None
) -> tuple[list[MeaningEntry], list[str]]:
    """One lemma's entries (reading-filtered) plus every reading it has (unfiltered)."""
    rows = cache.lookup_meaning(lemma)
    all_readings = list(dict.fromkeys(row["reading"] for row in rows if row["reading"]))
    if reading:
        target = kata_to_hira(reading)
        rows = [row for row in rows if kata_to_hira(row["reading"]) == target]
    entries = [
        MeaningEntry(
            reading=row["reading"],
            senses=[_to_sense(s) for s in row["senses"]],
            jlpt=row["jlpt"],
        )
        for row in rows
    ]
    return entries, all_readings


def lookup_meaning(tokenizer: Tokenizer, cache: DictCache, query: MeaningQuery) -> MeaningResult:
    entries, all_readings = _entries(cache, query.lemma, query.reading)
    if entries:
        return MeaningResult(
            lemma=query.lemma, reading=query.reading, entries=entries, all_readings=all_readings
        )
    key = deinflected_key(tokenizer, query.lemma, cache)
    if key is not None:
        alt_entries, alt_readings = _entries(cache, key[0], key[1])
        if alt_entries:
            return MeaningResult(
                lemma=key[0], reading=key[1], entries=alt_entries, all_readings=alt_readings
            )
    # No entry either way: the unfiltered readings of the lemma as asked for still
    # answer "what readings does this have", so they are not dropped.
    return MeaningResult(
        lemma=query.lemma, reading=query.reading, entries=[], all_readings=all_readings
    )
