"""Pitch-accent lookup over the Kanjium cache.

Positions are keyed by `(term, reading)` (0 = heiban / no downstep), so homographs
resolve to the right accent when a reading is supplied (箸 はし=1 vs 橋 はし=2 vs
端 はし=0). Each position is also mapped to its pitch category (heiban / atamadaka
/ nakadaka / odaka) from the position and the reading's mora count; kifuku (the
verb/adjective undulating class) is POS-driven and left to the renderer.

The term is looked up **as written first**, and only a miss is retried against
the deinflected key, so an inflected word field still gets an accent without
losing a surface that is already a headword. The result echoes whichever key
answered, and the categories are computed from that key's reading.
"""

from app.dicts import DictCache
from app.text.normalize import deinflected_key
from app.text.tokenizer import Tokenizer
from shared.text import PitchQuery, PitchResult

# Small kana that do NOT form their own mora (ゃゅょ and small vowels). Sokuon っ,
# the long-vowel mark ー, and ん each ARE morae, so they are not listed.
_SMALL_KANA = frozenset("ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")


def _mora_count(reading: str) -> int:
    return sum(1 for ch in reading if ch not in _SMALL_KANA)


def _category(position: int, mora_count: int) -> str:
    """Pitch category for a downstep position, given the reading's mora count."""
    if position == 0:
        return "heiban"
    if position == 1:
        return "atamadaka"
    return "odaka" if position == mora_count else "nakadaka"


def _result(term: str, reading: str | None, positions: list[int]) -> PitchResult:
    mora_count = _mora_count(reading) if reading else 0
    return PitchResult(
        term=term,
        reading=reading,
        positions=positions,
        categories=[_category(p, mora_count) for p in positions],
    )


def lookup_pitch(tokenizer: Tokenizer, cache: DictCache, query: PitchQuery) -> PitchResult:
    positions = cache.lookup_pitch(query.term, query.reading)
    if positions:
        return _result(query.term, query.reading, positions)
    key = deinflected_key(tokenizer, query.term, cache)
    if key is not None:
        positions = cache.lookup_pitch(*key)
        if positions:
            return _result(key[0], key[1], positions)
    return _result(query.term, query.reading, [])
