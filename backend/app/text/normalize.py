"""Deinflection / canonical-key normalization.

`normalize` is the canonical `surface -> (lemma, reading)` authority every feature
keys through, so shared vocabulary state doesn't fragment.
It deinflects via the tokenizer's head morpheme: lemma =
dictionary_form, reading = the *lemma's* reading (the surface morpheme only
carries the inflected reading, so the dictionary form is re-tokenized for the
full one), normalized to hiragana. `normalized` is Sudachi's variant-unified form
(する -> 為る); the lemma (not the normalized form) is what matches dict headwords.
"""

from app.text.convert import kata_to_hira
from app.text.tokenizer import Tokenizer
from shared.text import NormalizeResult, SplitMode


def lemma_reading(tokenizer: Tokenizer, surface: str, surface_reading: str, lemma: str) -> str:
    """The lemma's reading (katakana, as Sudachi emits) given its surface morpheme.

    When the surface is already the dictionary form its reading is the lemma's; an
    inflected surface carries only the inflected reading, so the dictionary form is
    re-tokenized for the full one. Shared with `content_words_with_readings`.
    """
    if lemma == surface:
        return surface_reading
    lemma_tokens = tokenizer.tokenize(lemma)
    if lemma_tokens:
        return "".join(token.reading for token in lemma_tokens)
    return surface_reading


def normalize(tokenizer: Tokenizer, surface: str, mode: SplitMode = SplitMode.C) -> NormalizeResult:
    tokens = tokenizer.tokenize(surface.strip(), mode)
    if not tokens:
        return NormalizeResult(surface=surface, lemma="", reading="", normalized="")
    head = tokens[0]
    lemma = head.dictionary_form or head.surface
    reading = lemma_reading(tokenizer, head.surface, head.reading, lemma)
    return NormalizeResult(
        surface=surface,
        lemma=lemma,
        reading=kata_to_hira(reading),
        normalized=head.normalized_form,
    )
