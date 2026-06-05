"""Furigana annotation.

Per token: prefer the curated JmdictFurigana segmentation from the dict cache
(it splits compound kanji correctly, e.g. 日本語 -> 日本|語), and fall back to
aligning the tokenizer's reading onto the surface for inflected/out-of-dictionary
words (e.g. 食べ -> 食|べ). Works without the furigana dict (cache=None): then
everything goes through alignment, so compounds stay unsplit but readings are
still correct.
"""

import re

from app.dicts import DictCache
from app.text.convert import kata_to_hira
from app.text.tokenizer import Tokenizer
from shared.text import FuriganaSegment, SplitMode

_KANJI_RE = re.compile(r"[㐀-鿿々〆ヶ]")


def _has_kanji(s: str) -> bool:
    return _KANJI_RE.search(s) is not None


def _runs(surface: str) -> list[tuple[str, bool]]:
    """Group surface into consecutive (text, is_kanji) runs."""
    runs: list[tuple[str, bool]] = []
    for ch in surface:
        is_kanji = _KANJI_RE.match(ch) is not None
        if runs and runs[-1][1] == is_kanji:
            runs[-1] = (runs[-1][0] + ch, is_kanji)
        else:
            runs.append((ch, is_kanji))
    return runs


def _align(surface: str, reading: str) -> list[FuriganaSegment] | None:
    """Distribute `reading` (hiragana) over the kanji runs of `surface`.

    Kana runs anchor the alignment (they must appear literally in the reading);
    each kanji run takes the reading up to the next anchor. Returns None if the
    surface and reading don't line up.
    """
    runs = _runs(surface)
    out: list[FuriganaSegment] = []
    pos = 0
    for i, (text, is_kanji) in enumerate(runs):
        if not is_kanji:
            hira = kata_to_hira(text)
            if reading[pos : pos + len(hira)] != hira:
                return None
            out.append(FuriganaSegment(text=text, reading=""))
            pos += len(hira)
        elif i + 1 < len(runs):
            next_hira = kata_to_hira(runs[i + 1][0])
            j = reading.find(next_hira, pos)
            if j == -1:
                return None
            out.append(FuriganaSegment(text=text, reading=reading[pos:j]))
            pos = j
        else:
            out.append(FuriganaSegment(text=text, reading=reading[pos:]))
            pos = len(reading)
    return out if pos == len(reading) else None


def _segments_for_token(
    surface: str, reading_katakana: str, cache: DictCache | None
) -> list[FuriganaSegment]:
    if not surface:
        return []
    if not _has_kanji(surface):
        return [FuriganaSegment(text=surface, reading="")]

    reading = kata_to_hira(reading_katakana)
    if cache is not None and reading:
        curated = cache.lookup_furigana(surface, reading)
        if curated:
            return [FuriganaSegment(text=s["ruby"], reading=s["rt"]) for s in curated]
    if reading:
        aligned = _align(surface, reading)
        if aligned is not None:
            return aligned
    # Last resort: ruby the whole surface (reading may be empty).
    return [FuriganaSegment(text=surface, reading=reading)]


def _merge_plain(segments: list[FuriganaSegment]) -> list[FuriganaSegment]:
    """Coalesce adjacent no-reading segments for cleaner output."""
    out: list[FuriganaSegment] = []
    for seg in segments:
        if seg.reading == "" and out and out[-1].reading == "":
            out[-1] = FuriganaSegment(text=out[-1].text + seg.text, reading="")
        else:
            out.append(seg)
    return out


def annotate(
    tokenizer: Tokenizer,
    text: str,
    cache: DictCache | None,
    mode: SplitMode = SplitMode.C,
) -> list[FuriganaSegment]:
    segments: list[FuriganaSegment] = []
    for token in tokenizer.tokenize(text, mode):
        segments.extend(_segments_for_token(token.surface, token.reading, cache))
    return _merge_plain(segments)
