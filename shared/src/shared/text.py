"""Text-service request/response contract (the /v1/text/* models).

Plain stdlib dataclasses (+ a StrEnum), shared by the backend and the add-on.
No tokenizer/library types appear here - the backend's tokenizer adapter maps its
output onto these models.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class SplitMode(StrEnum):
    """SudachiPy split granularity: A (shortest) .. C (longest)."""

    A = "A"
    B = "B"
    C = "C"


@dataclass
class Token:
    surface: str  # text as it appears
    dictionary_form: str  # lemma (e.g. した -> する)
    normalized_form: str  # normalized lemma (e.g. 為る for する)
    reading: str  # reading in katakana, as Sudachi emits it
    part_of_speech: list[str]  # POS components, "*" fillers removed
    start: int  # char offset into the source text
    end: int


@dataclass
class TokenizedText:
    text: str
    tokens: list[Token]


@dataclass
class TokenizeRequest:
    texts: list[str]  # batch-first: tokenize many texts in one request
    mode: SplitMode = SplitMode.C


@dataclass
class TokenizeResponse:
    results: list[TokenizedText] = field(default_factory=list)  # aligned with request.texts


@dataclass
class SpacingRequest:
    texts: list[str]  # batch-first
    mode: SplitMode = SplitMode.C
    separator: str = " "  # inserted at word (token) boundaries


@dataclass
class SpacingResponse:
    results: list[str] = field(default_factory=list)  # spaced text, aligned with request.texts
