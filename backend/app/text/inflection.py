"""Inflection: what a conjugated form is made of, and how to reduce it.

Two questions live here that are easy to confuse, and every consumer needs a
different mix of them:

- **Where does the word end?** A segmentation question. Sudachi splits a
  conjugated word into a stem plus bound morphemes (食べた -> 食べ + た), so a
  word occupies a *span* of tokens, not one token. :func:`strip_tails` answers
  it for a surface asserted to be one word.
- **What is the dictionary form of this span?** An inflection question.
  :func:`deinflect` answers it, folding the span's non-inflectional morphemes
  into the lemma and dropping the conjugation.

Keeping them apart matters: reducing a whole surface to ``tokens[0]`` silently
answers the first question with "one morpheme", which is wrong for compounds
(記憶喪失), prefixed words (お茶) and noun+suffix pairs (上等) alike - and the
caller cannot tell a truncation from a clean reduction. :func:`is_word_head`
gives callers the one signal the tokenizer can still get wrong after that.

:func:`is_inflection_tail` is context-free: its caller has asserted the span is
a single word, so a trailing auxiliary is by construction that word's
conjugation.
"""

from collections.abc import Sequence

from app.text.tokenizer import Tokenizer
from shared.text import Token

# 助詞 that attach to a stem (連用形 / 仮定形) and so continue the word's
# conjugation, keyed by dictionary form. Deliberately an allowlist: the
# conjunctive particles that attach to a *finished* clause instead - から, が,
# けど, し, と, のに, ので - end the word and must not be absorbed into it.
TAIL_PARTICLES = frozenset({"て", "で", "ば", "ちゃ", "じゃ", "たり", "つつ", "ながら"})

# Top-level POS that can begin a word. Everything else - 助詞, 助動詞, 接尾辞,
# 記号, 補助記号, 空白 - is bound or punctuation, so a span headed by one is a
# tokenizer misparse rather than a word.
WORD_HEADS = frozenset(
    {"名詞", "代名詞", "形状詞", "連体詞", "副詞", "接続詞", "感動詞", "動詞", "形容詞", "接頭辞"}
)

_INFLECTABLE = ("動詞", "形容詞")


def _top(token: Token) -> str:
    return token.part_of_speech[0] if token.part_of_speech else ""


def is_word_head(token: Token) -> bool:
    """True when `token` can begin a word (see :data:`WORD_HEADS`)."""
    return _top(token) in WORD_HEADS


def is_inflection_tail(token: Token) -> bool:
    """True when `token` carries conjugation rather than meaning of its own.

    Context-free: the caller has asserted its span is one word, so a trailing
    auxiliary belongs to that word. Covers auxiliaries (助動詞: た/ない/ます),
    the stem-attaching particles in :data:`TAIL_PARTICLES`, and non-independent
    helper verbs/adjectives (いる/ない in 食べている / 食べたくない).
    """
    pos = token.part_of_speech
    if not pos:
        return False
    head = pos[0]
    if head == "助動詞":
        return True
    if head == "助詞":
        return token.dictionary_form in TAIL_PARTICLES
    if head in _INFLECTABLE and len(pos) > 1 and pos[1].startswith("非自立"):
        return True
    return False


def strip_tails(tokens: Sequence[Token]) -> Sequence[Token]:
    """`tokens` without the trailing morphemes that only carry its conjugation.

    Dropping a tail can expose the particle that bound it on (ご覧 **に** なる),
    and a particle cannot end a word, so once anything has been stripped the
    trailing 助詞 go with it. A particle the input genuinely ends on is left
    alone, which is what keeps 次第に whole.

    The head is never stripped, so the result is always at least one token.
    """
    end = len(tokens)
    while end > 1 and is_inflection_tail(tokens[end - 1]):
        end -= 1
    if end < len(tokens):
        while end > 1 and _top(tokens[end - 1]) == "助詞":
            end -= 1
    return tokens[:end]


def lemma_reading(tokenizer: Tokenizer, surface: str, surface_reading: str, lemma: str) -> str:
    """The lemma's reading (katakana, as Sudachi emits) given its surface morpheme.

    When the surface is already the dictionary form its reading is the lemma's;
    an inflected surface carries only the inflected reading, so the dictionary
    form is re-tokenized for the full one.
    """
    if lemma == surface:
        return surface_reading
    lemma_tokens = tokenizer.tokenize(lemma)
    if lemma_tokens:
        return "".join(token.reading for token in lemma_tokens)
    return surface_reading


def deinflect(tokenizer: Tokenizer, tokens: Sequence[Token]) -> tuple[str, str, str]:
    """Reduce a one-word span to its ``(lemma, reading, normalized)``.

    Japanese inflects at the end, so only the span's last morpheme is replaced
    by its dictionary form; everything before it is already in dictionary form
    and is folded in as-is. That keeps compounds whole (記憶喪失), keeps a
    prefix attached to its stem (お茶) and keeps a noun with its suffix (上等),
    while still deinflecting the part that actually carries the conjugation.
    """
    span = strip_tails(tokens)
    last = span[-1]
    lemma = last.dictionary_form or last.surface
    prefix = span[:-1]
    return (
        "".join(t.surface for t in prefix) + lemma,
        "".join(t.reading for t in prefix)
        + lemma_reading(tokenizer, last.surface, last.reading, lemma),
        "".join(t.normalized_form for t in prefix) + last.normalized_form,
    )


__all__ = [
    "TAIL_PARTICLES",
    "WORD_HEADS",
    "deinflect",
    "is_inflection_tail",
    "is_word_head",
    "lemma_reading",
    "strip_tails",
]
