"""SudachiPy tokenizer behind a thin adapter.

The ONLY module that imports SudachiPy: no Sudachi types leak into endpoints or
`shared/`, so swapping the tokenizer (fugashi/UniDic, ...) later touches just this
file. Building the dictionary is expensive, so construct one `Tokenizer` at
startup and hold it on app state - never per request.
"""

from sudachipy import Dictionary
from sudachipy import Morpheme as _Morpheme
from sudachipy import SplitMode as _SudachiSplitMode

from shared.text import SplitMode, Token

_MODE_MAP = {
    SplitMode.A: _SudachiSplitMode.A,
    SplitMode.B: _SudachiSplitMode.B,
    SplitMode.C: _SudachiSplitMode.C,
}


class Tokenizer:
    """Wraps a SudachiPy tokenizer, emitting contract `Token`s."""

    def __init__(self) -> None:
        self._tokenizer = Dictionary().create()

    def tokenize(self, text: str, mode: SplitMode = SplitMode.C) -> list[Token]:
        if not text:
            return []
        return [_to_token(m) for m in self._tokenizer.tokenize(text, _MODE_MAP[mode])]

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
