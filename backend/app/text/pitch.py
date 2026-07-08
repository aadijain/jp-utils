"""Pitch-accent lookup over the Kanjium cache.

Positions are keyed by `(term, reading)` (0 = heiban / no downstep), so homographs
resolve to the right accent when a reading is supplied (箸 はし=1 vs 橋 はし=2 vs
端 はし=0). Each position is also mapped to its pitch category (heiban / atamadaka
/ nakadaka / odaka) from the position and the reading's mora count, matching how
the Lapis note type colors the word - kifuku (the verb/adjective undulating class)
is POS-driven and left to the renderer.
"""

from app.dicts import DictCache
from shared.text import PitchQuery, PitchResult

# Small kana that do NOT form their own mora (ゃゅょ and small vowels). Sokuon っ,
# the long-vowel mark ー, and ん each ARE morae, so they are not listed. Mirrors the
# Lapis note type's `removeSmallKana`, so our categories match what it renders.
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


def lookup_pitch(cache: DictCache, query: PitchQuery) -> PitchResult:
    positions = cache.lookup_pitch(query.term, query.reading)
    mora_count = _mora_count(query.reading) if query.reading else 0
    categories = [_category(p, mora_count) for p in positions]
    return PitchResult(
        term=query.term,
        reading=query.reading,
        positions=positions,
        categories=categories,
    )
