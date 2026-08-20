"""SudachiPy tokenizer behind a thin adapter.

The ONLY module that imports SudachiPy: no Sudachi types leak into endpoints or
`shared/`, so swapping the tokenizer (fugashi/UniDic, ...) touches just this
file. Building the dictionary is expensive, so construct one `Tokenizer` at
startup and hold it on app state - never per request.
"""

from functools import lru_cache

from sudachipy import Dictionary
from sudachipy import Morpheme as _Morpheme
from sudachipy import SplitMode as _SudachiSplitMode

from shared.text import SplitMode, Token

# A word's dictionary form is re-tokenized to recover its full reading, and a
# corpus hits the same lemmas over and over (~5x repeat over a sentence sweep),
# so `reading_of` is memoized. Bounded, per-instance, and `lru_cache` is itself
# thread-safe.
_READING_CACHE_SIZE = 8192

_MODE_MAP = {
    SplitMode.A: _SudachiSplitMode.A,
    SplitMode.B: _SudachiSplitMode.B,
    SplitMode.C: _SudachiSplitMode.C,
}


class Tokenizer:
    """Wraps a SudachiPy tokenizer, emitting contract `Token`s."""

    def __init__(self) -> None:
        self._tokenizer = Dictionary().create()
        self.reading_of = lru_cache(maxsize=_READING_CACHE_SIZE)(self._reading_of)

    def tokenize(self, text: str, mode: SplitMode = SplitMode.C) -> list[Token]:
        if not text:
            return []
        return [_to_token(m) for m in self._tokenizer.tokenize(text, _MODE_MAP[mode])]

    def _reading_of(self, text: str) -> str:
        """`text`'s full reading in katakana, concatenated over its morphemes."""
        return "".join(token.reading for token in self.tokenize(text))

    def warmup(self) -> None:
        """Force the lazy dictionary load so the first real request is hot."""
        self.tokenize("ウォームアップ")


def _to_token(m: _Morpheme) -> Token:
    pos = [p for p in m.part_of_speech() if p != "*"]
    return Token(
        surface=m.surface(),
        dictionary_form=m.dictionary_form(),
        normalized_form=m.normalized_form(),
        reading=m.reading_form(),
        part_of_speech=pos,
        start=m.begin(),
        end=m.end(),
    )
