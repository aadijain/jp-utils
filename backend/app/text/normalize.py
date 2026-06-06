"""Deinflection / canonical-key normalization.

`normalize` is the canonical `surface -> (lemma, reading)` authority every feature
keys through, so shared vocabulary state doesn't fragment.

The input is asserted to be one word, so the whole tokenization is that word's
span: `deinflect` drops the trailing morphemes that only carry conjugation and
folds the rest into the lemma. Reading follows the same span, normalized to
hiragana. Taking only the head morpheme instead would silently truncate every
surface Sudachi splits - a compound (記憶喪失 -> 記憶), a prefixed word
(お茶 -> お), a noun with a suffix (上等 -> 上) - and hand back a fragment that
looks exactly like a clean reduction.

`normalized` is Sudachi's variant-unified form (する -> 為る); the lemma (not the
normalized form) is what matches dict headwords. `covered` reports whether the
surface had a real word to head it at all - see the contract for what a consumer
should do when it doesn't.
"""

from app.text.convert import kata_to_hira
from app.text.inflection import deinflect, is_word_head
from app.text.tokenizer import Tokenizer
from shared.text import NormalizeResult, SplitMode


def normalize(tokenizer: Tokenizer, surface: str, mode: SplitMode = SplitMode.C) -> NormalizeResult:
    tokens = tokenizer.tokenize(surface.strip(), mode)
    if not tokens:
        return NormalizeResult(surface=surface, lemma="", reading="", normalized="", covered=False)
    lemma, reading, normalized = deinflect(tokenizer, tokens)
    return NormalizeResult(
        surface=surface,
        lemma=lemma,
        reading=kata_to_hira(reading),
        normalized=normalized,
        covered=is_word_head(tokens[0]),
    )
