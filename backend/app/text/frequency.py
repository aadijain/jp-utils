"""Frequency lookup over the JPDB cache.

Ranks are keyed by `(term, reading)` (lower rank = more frequent), so homographs
resolve to the right number when a reading is supplied (人 ひと vs にん). If the
term form isn't ranked under that reading, `DictCache.lookup_frequency` falls
back to the hiragana kana-form (JPDB's canonical kana entry), so a word like 猫
missing a kanji rank can still resolve via ねこ.
"""

from app.dicts import DictCache
from shared.text import FrequencyQuery, FrequencyResult


def lookup_frequency(cache: DictCache, query: FrequencyQuery) -> FrequencyResult:
    rank = cache.lookup_frequency(query.term, query.reading)
    return FrequencyResult(term=query.term, reading=query.reading, rank=rank)
