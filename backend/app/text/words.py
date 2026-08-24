"""Content-word extraction from a sentence.

Tokenizes a sentence and keeps only the *content words* - the ones that count as
vocabulary for n+1 scoring. Particles, auxiliaries,
punctuation, proper nouns, numerals and purely-katakana words (loanwords/names)
are dropped. Each surviving morpheme is
reduced to its dictionary-form lemma (per token, not per word span: a sentence's
vocabulary is its individual content words, so 俺たち contributes 俺 rather than
becoming a word of its own), then collapsed onto the word that form belongs to
(`canonical.canonical_lemma`, so 作れる counts as 作る); matching against the
learnt set is
**lemma-only** (the stored reading is dict-preferred while the tokenizer emits
Sudachi readings, so reading is not a safe key yet).

The POS filter mirrors the known-words backfill,
promoted here as the single shared definition of
"a word that counts". Words are de-duplicated by lemma, order-preserving: a
sentence's distinct content words are exactly what n+1 needs (its unknown set + a
length proxy), and they are stable per sentence so the result is memoized in a
server-side `TokenizationCache` for incremental re-sorts. `content_words_batch`
is the primary extractor (it carries the contextual reading generation needs)
and the single place the cache is consulted - once per BATCH, not per text;
`content_words` is its lemma-only projection (n+1 matches lemma-only).
"""

from collections.abc import Sequence

from app.cache import TokenizationCache, sentence_hash
from app.dicts import DictCache
from app.text.canonical import canonical_lemma
from app.text.convert import kata_to_hira
from app.text.inflection import lemma_reading
from app.text.tokenizer import Tokenizer
from shared.text import SplitMode, Token
from shared.vocab import VocabWord

# NB: changing what any rule below keeps or drops changes what an extraction
# returns, and `TokenizationCache` keys on the sentence alone - so a stored entry
# would keep serving the OLD answer. Bump
# `app.cache.tokenization.EXTRACTION_VERSION` with any such edit here (or in
# `text/inflection.py`, which the stored reading comes from, or
# `text/canonical.py`, which decides what a lemma collapses to) to invalidate it.

# Sudachi top-level POS to keep (content words). "*" fillers are already stripped
# from the contract Token, so part_of_speech[0] is the top-level class:
# noun / verb / i-adj / na-adj / adverb / pronoun.
KEEP_TOP = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "代名詞"}
# Noun subtypes dropped even though the top-level is 名詞: proper nouns + numerals.
DROP_NOUN_SUB = {"固有名詞", "数詞"}

# "Purely katakana" = full-width katakana letters (U+30A1–U+30FA) plus the prolonged
# sound mark ー and the middle dot ・, and nothing else. Such words (loanwords /
# names) are dropped from the content-word set alongside proper nouns and numerals,
# so they never become vocab cards nor count toward n+1. At least one real kana is
# required, so a bare "ー"/"・" is not treated as a katakana word.
_KATAKANA_LETTERS = range(0x30A1, 0x30FB)  # ァ..ヺ
_KATAKANA_EXTRA = frozenset("ー・")  # U+30FC prolonged mark, U+30FB middle dot


def is_pure_katakana(text: str) -> bool:
    """True when `text` is katakana only (letters + ー/・) with at least one kana."""
    has_letter = False
    for ch in text:
        if ord(ch) in _KATAKANA_LETTERS:
            has_letter = True
        elif ch not in _KATAKANA_EXTRA:
            return False
    return has_letter


def is_content(token: Token) -> bool:
    """True when the morpheme is a content word that counts toward n+1."""
    pos = token.part_of_speech
    if not pos or pos[0] not in KEEP_TOP:
        return False
    if pos[0] == "名詞" and len(pos) > 1 and pos[1] in DROP_NOUN_SUB:
        return False
    if is_pure_katakana(token.dictionary_form or token.surface):
        return False  # katakana loanwords/names are not vocab targets
    return True


def _extract(
    tokenizer: Tokenizer, text: str, mode: SplitMode, dicts: DictCache | None
) -> list[VocabWord]:
    """Tokenize `text` and keep its distinct content words (lemma + reading).

    Dedup happens on the CANONICAL lemma, after `canonical_lemma` has collapsed
    inflected forms - 作れる and 作る in one sentence are one word, not two.
    """
    words: list[VocabWord] = []
    seen: set[str] = set()
    for token in tokenizer.tokenize(text, mode):
        if not is_content(token):
            continue
        lemma = token.dictionary_form or token.surface
        if not lemma:
            continue
        reading = lemma_reading(tokenizer, token.surface, token.reading, lemma)
        lemma, reading = canonical_lemma(tokenizer, dicts, lemma, reading, token.normalized_form)
        if lemma in seen:
            continue
        seen.add(lemma)
        words.append(VocabWord(lemma=lemma, reading=kata_to_hira(reading)))
    return words


def content_words_with_readings(
    tokenizer: Tokenizer,
    text: str,
    mode: SplitMode = SplitMode.C,
    cache: TokenizationCache | None = None,
    dicts: DictCache | None = None,
) -> list[VocabWord]:
    """The distinct content words of `text` (lemma + reading), in first-seen order.

    The reading is the lemma's context-disambiguated reading (`inflection`'s
    `lemma_reading`), folded to hiragana to match the store's convention. Dedup is
    by lemma, so `content_words` is exactly this projected to its lemmas. n+1
    ignores the reading; it rides along so generation gets a contextual reading
    from the same tokenization.

    A `cache`, when given, memoizes the result by a content hash of `text` so repeat
    extractions (the n+1 start-sweep, generation) skip Sudachi. This is the one
    place caching is consulted, so every caller gets it for free.
    Caching is limited to mode C (the cached assumption); other modes always extract.

    Single-text convenience over `content_words_batch`. Callers holding a whole
    batch should use that directly - it consults the cache once for the batch
    instead of once per text.
    """
    return content_words_batch(tokenizer, [text], mode, cache, dicts)[0]


def content_words_batch(
    tokenizer: Tokenizer,
    texts: Sequence[str],
    mode: SplitMode = SplitMode.C,
    cache: TokenizationCache | None = None,
    dicts: DictCache | None = None,
) -> list[list[VocabWord]]:
    """`content_words_with_readings` over many texts; result aligned with `texts`.

    The batch form exists for the cache, not the tokenizer: it reads every hit in
    ONE `get_many` and writes every miss in ONE `put_many`, instead of a query and
    a separate committed transaction per text. Over a 2000-sentence sweep that is
    ~250ms of per-sentence commits against ~18ms batched.

    Texts repeated within the batch are extracted once (they share a content hash).
    """
    if cache is None or mode != SplitMode.C:
        return [_extract(tokenizer, text, mode, dicts) for text in texts]

    hashes = [sentence_hash(text) for text in texts]
    cached = cache.get_many(hashes)

    extracted: dict[str, list[VocabWord]] = {}
    results: list[list[VocabWord]] = []
    for text, key in zip(texts, hashes, strict=True):
        words = cached.get(key)
        if words is None:
            words = extracted.get(key)
        if words is None:
            words = _extract(tokenizer, text, mode, dicts)
            extracted[key] = words
        results.append(words)

    if extracted:
        cache.put_many(extracted.items())
    return results


def content_words(
    tokenizer: Tokenizer,
    text: str,
    mode: SplitMode = SplitMode.C,
    cache: TokenizationCache | None = None,
    dicts: DictCache | None = None,
) -> list[str]:
    """The distinct content-word lemmas of `text`, in first-seen order."""
    return [w.lemma for w in content_words_with_readings(tokenizer, text, mode, cache, dicts)]
