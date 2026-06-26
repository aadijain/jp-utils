"""Locate a word inside a sentence (inflection-aware), breaking it into segments.

Backs the highlight add-on op. The caller strips markup first, so this works on
plain text only: it tokenizes the sentence, deinflects the target word to its
lemma (via `normalize`, the canonical key authority), and finds the FIRST token
whose lemma matches - so an inflected occurrence (食べた for 食べる) is found
without a literal string match. The text is then split into contiguous segments
with the matched slice flagged; the add-on wraps that slice in its own markup.

Only the first match is flagged (handling every occurrence is deliberately left to
the caller / future work). When the word isn't found the whole text comes back as
one unmatched segment.
"""

from app.text.normalize import normalize
from app.text.tokenizer import Tokenizer
from shared.text import LocateResult, LocateSegment, SplitMode, Token


def _is_inflection_tail(token: Token) -> bool:
    """True when ``token`` continues the preceding word's conjugation.

    Sudachi splits a conjugated word into a stem token plus bound suffixes
    (食べた -> 食べ + た), so to highlight the whole surface form we absorb the
    trailing pieces: auxiliaries (助動詞: た/たい/ない), conjunctive particles
    (接続助詞: て/ば), and non-independent helper verbs/adjectives (いる/ない in
    食べている / 食べたくない).
    """
    pos = token.part_of_speech
    if not pos:
        return False
    head = pos[0]
    if head == "助動詞":
        return True
    if head == "助詞" and len(pos) > 1 and pos[1] == "接続助詞":
        return True
    if head in ("動詞", "形容詞") and len(pos) > 1 and pos[1].startswith("非自立"):
        return True
    return False


def locate(
    tokenizer: Tokenizer, text: str, word: str, mode: SplitMode = SplitMode.C
) -> LocateResult:
    word = word.strip()
    if not text or not word:
        return LocateResult(text=text, segments=[LocateSegment(text)] if text else [])

    target = normalize(tokenizer, word, mode)
    target_lemma = target.lemma or word
    tokens = tokenizer.tokenize(text, mode)
    span: tuple[int, int] | None = None
    for i, tok in enumerate(tokens):
        if (
            tok.dictionary_form == target_lemma
            or tok.surface == word
            or (target.normalized and tok.normalized_form == target.normalized)
        ):
            end = tok.end
            for tail in tokens[i + 1 :]:  # absorb the conjugation suffixes
                if not _is_inflection_tail(tail):
                    break
                end = tail.end
            span = (tok.start, end)
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
