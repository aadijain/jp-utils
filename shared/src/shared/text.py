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


@dataclass
class FuriganaSegment:
    text: str
    reading: str  # ruby over `text`; "" means render `text` as-is (no ruby)


@dataclass
class FuriganaText:
    text: str
    segments: list[FuriganaSegment] = field(default_factory=list)  # concatenated, reproduce `text`


@dataclass
class FuriganaRequest:
    texts: list[str]  # batch-first
    mode: SplitMode = SplitMode.C


@dataclass
class FuriganaResponse:
    results: list[FuriganaText] = field(default_factory=list)  # aligned with request.texts


class Conversion(StrEnum):
    HIRA_TO_KATA = "hira_to_kata"  # hiragana -> katakana
    KATA_TO_HIRA = "kata_to_hira"  # katakana -> hiragana
    KANA_TO_ROMAJI = "kana_to_romaji"  # hiragana/katakana -> romaji
    ROMAJI_TO_KANA = "romaji_to_kana"  # romaji -> hiragana
    TO_FULLWIDTH = "to_fullwidth"  # half-width kana/ASCII/digits -> full-width
    TO_HALFWIDTH = "to_halfwidth"  # full-width kana/ASCII/digits -> half-width


@dataclass
class ConvertRequest:
    texts: list[str]  # batch-first
    conversion: Conversion


@dataclass
class ConvertResponse:
    results: list[str] = field(default_factory=list)  # converted text, aligned with request.texts


@dataclass
class MeaningQuery:
    lemma: str  # dictionary form to look up
    reading: str | None = None  # optional disambiguation (hira or kata accepted)


@dataclass
class MeaningEntry:
    reading: str
    glosses: list[str]
    jlpt: int | None = None


@dataclass
class MeaningResult:
    lemma: str
    reading: str | None  # echoes the query reading
    entries: list[MeaningEntry] = field(default_factory=list)  # best-first; empty if not found


@dataclass
class MeaningRequest:
    queries: list[MeaningQuery]  # batch-first


@dataclass
class MeaningResponse:
    results: list[MeaningResult] = field(default_factory=list)  # aligned with request.queries


@dataclass
class FrequencyQuery:
    term: str  # word form to rank (surface or dictionary form)
    reading: str | None = None  # fallback if the term form isn't ranked (hira/kata accepted)


@dataclass
class FrequencyResult:
    term: str
    reading: str | None
    rank: int | None  # JPDB rank, lower = more frequent; None if not ranked


@dataclass
class FrequencyRequest:
    queries: list[FrequencyQuery]  # batch-first


@dataclass
class FrequencyResponse:
    results: list[FrequencyResult] = field(default_factory=list)  # aligned with request.queries


@dataclass
class NormalizeResult:
    surface: str  # echoes the input
    lemma: str  # dictionary form (deinflected); the canonical key together with `reading`
    reading: str  # hiragana reading of the lemma; "" if unavailable
    normalized: str  # Sudachi normalized form (variant unification, e.g. する -> 為る)


@dataclass
class NormalizeRequest:
    surfaces: list[str]  # batch-first
    mode: SplitMode = SplitMode.C


@dataclass
class NormalizeResponse:
    results: list[NormalizeResult] = field(default_factory=list)  # aligned with request.surfaces
