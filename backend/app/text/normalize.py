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

`deinflected_key` is the same reduction packaged for the dictionary lookups: the
retry key for a term that missed as written.
"""

from app.dicts import DictCache
from app.text.canonical import canonical_lemma
from app.text.convert import kata_to_hira
from app.text.inflection import deinflect, is_word_head
from app.text.tokenizer import Tokenizer
from shared.text import NormalizeResult, SplitMode


def normalize(
    tokenizer: Tokenizer,
    surface: str,
    mode: SplitMode = SplitMode.C,
    dicts: DictCache | None = None,
) -> NormalizeResult:
    tokens = tokenizer.tokenize(surface.strip(), mode)
    if not tokens:
        return NormalizeResult(surface=surface, lemma="", reading="", normalized="", covered=False)
    lemma, reading, normalized = deinflect(tokenizer, tokens)
    lemma, reading = canonical_lemma(tokenizer, dicts, lemma, reading, normalized)
    return NormalizeResult(
        surface=surface,
        lemma=lemma,
        reading=kata_to_hira(reading),
        normalized=normalized,
        covered=is_word_head(tokens[0]),
    )


def deinflected_key(
    tokenizer: Tokenizer, term: str, dicts: DictCache | None = None
) -> tuple[str, str] | None:
    """The `(lemma, reading)` to retry a dictionary lookup that missed on `term`.

    A word supplied by a card can be an inflected form (攻め), which is not a
    headword, so a miss on the surface gets one more chance at the lemma. With a
    dict cache the lemma is collapsed too, so a potential form retries as the verb
    it belongs to (作れる -> 作る) instead of as itself. `None`
    means there is nothing new to try: the surface has no word head at all, or it
    already IS its own lemma. The reading comes from the same analysis as the
    lemma and replaces the caller's - that one describes the surface, which the
    lemma no longer is.
    """
    result = normalize(tokenizer, term, dicts=dicts)
    if not result.covered or not result.lemma or result.lemma == term.strip():
        return None
    return result.lemma, result.reading
