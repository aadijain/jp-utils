"""Inflection: what a conjugated form is made of, and how to reduce it.

Two questions live here that are easy to confuse, and every consumer needs a
different mix of them:

- **Where does the word end?** A segmentation question. Sudachi splits a
  conjugated word into a stem plus bound morphemes (食べた -> 食べ + た), so a
  word occupies a *span* of tokens, not one token. :func:`absorbed_end` answers
  this for a word sitting inside a longer sentence.
- **What is the dictionary form of this span?** An inflection question.
  :func:`deinflect` answers it, folding the span's non-inflectional morphemes
  into the lemma and dropping the conjugation.

Keeping them apart matters: reducing a whole surface to ``tokens[0]`` silently
answers the first question with "one morpheme", which is wrong for compounds
(記憶喪失), prefixed words (お茶) and noun+suffix pairs (上等) alike - and the
caller cannot tell a truncation from a clean reduction. :func:`is_word_head`
gives callers the one signal the tokenizer can still get wrong after that.

The two questions also want *different* tail rules, which is why there are two
predicates rather than one:

- :func:`is_inflection_tail` is context-free. Its caller has asserted the span
  is a single word, so a trailing auxiliary is by construction that word's
  conjugation.
- :func:`absorbed_end` is head-aware. In a sentence the same auxiliary may
  belong to something else entirely: だ after a noun is a copula joining two
  clause parts (新人だ), not part of the noun.
"""

from collections.abc import Sequence

from app.text.tokenizer import Tokenizer
from shared.text import Token

# 助詞 that attach to a stem (連用形 / 仮定形) and so continue the word's
# conjugation, keyed by dictionary form. Deliberately an allowlist: the
# conjunctive particles that attach to a *finished* clause instead - から, が,
# けど, し, と, のに, ので - end the word and must not be absorbed into it.
TAIL_PARTICLES = frozenset({"て", "で", "ば", "ちゃ", "じゃ", "たり", "つつ", "ながら"})

# Light verbs that carry a サ変 noun's own verb form (攻略する, 共有できる).
LIGHT_VERBS = frozenset({"する", "できる", "なさる", "いたす"})

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


def _is_copula(token: Token) -> bool:
    """True for な / に / だ - the copula that inflects a na-adjective."""
    return _top(token) == "助動詞" and token.dictionary_form == "だ"


def _is_light_verb(token: Token) -> bool:
    return _top(token) == "動詞" and token.dictionary_form in LIGHT_VERBS


def absorbed_end(tokens: Sequence[Token], i: int) -> int:
    """The char offset where the word headed by ``tokens[i]`` ends.

    What may attach depends on the head, because the same morpheme belongs to
    different things after different words:

    - 動詞 / 形容詞 absorb their full conjugation (:func:`is_inflection_tail`).
    - 形状詞 absorb only the copula that inflects them (広大な, 明確に) and stop
      there - a helper verb after that starts a new word (本気に **なった**).
    - a サ変 noun absorbs the light verb that is its own verb form (攻略する,
      共有できる) and then conjugates like a 動詞.
    - every other head absorbs nothing. A copula after a plain noun is not part
      of the noun (新人だ, 道理でしょ), and 行く/ある are tagged 非自立可能 by
      possibility, not by use (保健室 **行く**, たくさん **ある**).
    """
    head = tokens[i]
    top = _top(head)
    end = head.end
    j = i + 1
    if top == "名詞" and "サ変可能" in head.part_of_speech:
        if j < len(tokens) and _is_light_verb(tokens[j]):
            end = tokens[j].end
            j += 1
            top = "動詞"
    if top in _INFLECTABLE:
        while j < len(tokens) and is_inflection_tail(tokens[j]):
            end = tokens[j].end
            j += 1
    elif top == "形状詞":
        while j < len(tokens) and _is_copula(tokens[j]):
            end = tokens[j].end
            j += 1
    return end


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
    "LIGHT_VERBS",
    "TAIL_PARTICLES",
    "WORD_HEADS",
    "absorbed_end",
    "deinflect",
    "is_inflection_tail",
    "is_word_head",
    "lemma_reading",
    "strip_tails",
]
