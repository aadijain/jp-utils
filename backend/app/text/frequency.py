"""Frequency lookup over the JPDB cache.

Ranks are keyed by `(term, reading)` (lower rank = more frequent), so homographs
resolve to the right number when a reading is supplied (人 ひと vs にん). If the
term form isn't ranked under that reading, `DictCache.lookup_frequency` falls
back to the hiragana kana-form (JPDB's canonical kana entry), so a word like 猫
missing a kanji rank can still resolve via ねこ.

The term is looked up **as written first** - a surface that is already a headword
is the right entry, and going through the lemma unconditionally would flatten
homograph readings. Only a miss is retried against the deinflected key, so an
inflected word field still gets its rank. The result echoes whichever key
answered.
"""

from app.dicts import DictCache
from app.text.normalize import deinflected_key
from app.text.tokenizer import Tokenizer
from shared.text import FrequencyQuery, FrequencyResult


def lookup_frequency(
    tokenizer: Tokenizer, cache: DictCache, query: FrequencyQuery
) -> FrequencyResult:
    rank = cache.lookup_frequency(query.term, query.reading)
    if rank is not None:
        return FrequencyResult(term=query.term, reading=query.reading, rank=rank)
    key = deinflected_key(tokenizer, query.term, cache)
    if key is not None:
        rank = cache.lookup_frequency(*key)
        if rank is not None:
            return FrequencyResult(term=key[0], reading=key[1], rank=rank)
    return FrequencyResult(term=query.term, reading=query.reading, rank=None)
