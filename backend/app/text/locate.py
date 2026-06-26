"""Locate a word inside a sentence (inflection-aware), breaking it into segments.

Backs the highlight add-on op. The caller strips markup first, so this works on
plain text only: it tokenizes the sentence, deinflects the target word to its
lemma (`inflection.deinflect`, the same reduction `normalize` keys through), and
finds the FIRST place its morphemes line up - so an inflected occurrence (食べた
for 食べる) is found without a literal string match. A word Sudachi splits
(お茶, 記憶喪失, 足元をすくう) is matched across the whole run of tokens rather
than on its first morpheme alone. The text is then split into contiguous segments
with the matched slice flagged; the add-on wraps that slice in its own markup.

The matched slice runs to `absorbed_end`, which extends it over the bound
morphemes that belong to the word (食べた -> 食べ + た) and stops where a new one
starts - so what gets highlighted is the word, not the rest of the clause.

Only the first match is flagged; handling every occurrence is left to
the caller. When the word isn't found the whole text comes back as
one unmatched segment.
"""

from collections.abc import Sequence

from app.text.inflection import absorbed_end, deinflect, strip_tails
from app.text.tokenizer import Tokenizer
from shared.text import LocateResult, LocateSegment, SplitMode, Token


def _spans(tokens: Sequence[Token], i: int, target: Sequence[Token], lemma: str, norm: str) -> int:
    """How many tokens the target occupies starting at `i`; 0 when it doesn't match.

    A word Sudachi splits in isolation is often kept whole in a sentence (対等
    parses as 対 + 等 alone but as one morpheme in context), so the one-token
    test is tried first whatever the target's own shape. Falling back to the
    multi-token alignment catches the reverse (お茶 stays split in both).
    Everything but the target's last morpheme must align literally - only the
    last one carries the conjugation, so only it is compared by dictionary form.
    """
    tok = tokens[i]
    if tok.dictionary_form == lemma or tok.normalized_form == norm:
        return 1
    if len(target) == 1 or i + len(target) > len(tokens):
        return 0
    if any(tokens[i + k].surface != t.surface for k, t in enumerate(target[:-1])):
        return 0
    last = tokens[i + len(target) - 1]
    if last.dictionary_form == target[-1].dictionary_form or last.surface == target[-1].surface:
        return len(target)
    return 0


def locate(
    tokenizer: Tokenizer, text: str, word: str, mode: SplitMode = SplitMode.C
) -> LocateResult:
    word = word.strip()
    if not text or not word:
        return LocateResult(text=text, segments=[LocateSegment(text)] if text else [])

    word_tokens = tokenizer.tokenize(word, mode)
    if not word_tokens:
        return LocateResult(text=text, segments=[LocateSegment(text)])
    lemma, _, normalized = deinflect(tokenizer, word_tokens)
    target = strip_tails(word_tokens)
    tokens = tokenizer.tokenize(text, mode)
    span: tuple[int, int] | None = None
    for i, tok in enumerate(tokens):
        n = 1 if tok.surface == word else _spans(tokens, i, target, lemma, normalized)
        if n:
            span = (tok.start, absorbed_end(tokens, i + n - 1))
            break

    if span is None:
        return LocateResult(text=text, segments=[LocateSegment(text)])

    start, end = span
    segments: list[LocateSegment] = []
    if start > 0:
        segments.append(LocateSegment(text[:start]))
    segments.append(LocateSegment(text[start:end], match=True))
    if end < len(text):
        segments.append(LocateSegment(text[end:]))
    return LocateResult(text=text, segments=segments)
