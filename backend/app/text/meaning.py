"""Meaning lookup over the jitendex cache.

Returns the cache's per-headword entries best-first (entries[0] is the primary,
highest-priority sense; the rest are alternates), each carrying its per-sense
structure (glosses, part-of-speech, example sentences). An optional reading
filters to matching entries; readings are compared in hiragana space so katakana
input (e.g. the tokenizer's reading) and katakana headwords (loanwords) both
match. ``all_readings`` always lists every distinct reading of the lemma (from
the unfiltered rows), so a consumer can render an "all readings" line without a
second lookup.
"""

from app.dicts import DictCache
from app.text.convert import kata_to_hira
from shared.text import MeaningEntry, MeaningExample, MeaningQuery, MeaningResult, MeaningSense


def _to_sense(sense: dict) -> MeaningSense:
    return MeaningSense(
        glosses=sense.get("glosses", []),
        pos=sense.get("pos", []),
        examples=[
            MeaningExample(ja=ex.get("ja", ""), en=ex.get("en", ""))
            for ex in sense.get("examples", [])
        ],
    )


def lookup_meaning(cache: DictCache, query: MeaningQuery) -> MeaningResult:
    rows = cache.lookup_meaning(query.lemma)
    all_readings = list(dict.fromkeys(row["reading"] for row in rows if row["reading"]))
    if query.reading:
        target = kata_to_hira(query.reading)
        rows = [row for row in rows if kata_to_hira(row["reading"]) == target]
    entries = [
        MeaningEntry(
            reading=row["reading"],
            senses=[_to_sense(s) for s in row["senses"]],
            jlpt=row["jlpt"],
        )
        for row in rows
    ]
    return MeaningResult(
        lemma=query.lemma, reading=query.reading, entries=entries, all_readings=all_readings
    )
