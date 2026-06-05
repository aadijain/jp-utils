"""Meaning lookup over the jitendex cache.

Returns the cache's per-headword entries best-first (entries[0] is the primary,
highest-priority sense; the rest are alternates). An optional reading filters to
matching entries; readings are compared in hiragana space so katakana input
(e.g. the tokenizer's reading) and katakana headwords (loanwords) both match.
"""

from app.dicts import DictCache
from app.text.convert import kata_to_hira
from shared.text import MeaningEntry, MeaningQuery, MeaningResult


def lookup_meaning(cache: DictCache, query: MeaningQuery) -> MeaningResult:
    rows = cache.lookup_meaning(query.lemma)
    if query.reading:
        target = kata_to_hira(query.reading)
        rows = [row for row in rows if kata_to_hira(row["reading"]) == target]
    entries = [
        MeaningEntry(reading=row["reading"], glosses=row["glosses"], jlpt=row["jlpt"])
        for row in rows
    ]
    return MeaningResult(lemma=query.lemma, reading=query.reading, entries=entries)
