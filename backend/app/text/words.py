"""Content-word extraction from a sentence.

Tokenizes a sentence and keeps only the *content words* - the ones that count as
vocabulary for n+1 scoring. Particles, auxiliaries,
punctuation, proper nouns and numerals are dropped. Each surviving morpheme is
reduced to its dictionary-form lemma; matching against the learnt set is
**lemma-only** (the stored reading is dict-preferred while the tokenizer emits
Sudachi readings, so reading is not a safe key yet).

The POS filter mirrors the known-words backfill,
promoted here so the n+1 endpoint and any future feature share one definition of
"a word that counts". Words are de-duplicated by lemma, order-preserving: a
sentence's distinct content words are exactly what n+1 needs (its unknown set + a
length proxy), and they are stable per sentence so the add-on caches them for
incremental re-sorts. `content_words_with_readings` is the primary extractor (it
carries the contextual reading generation needs); `content_words` is its
lemma-only projection (n+1 matches lemma-only).
"""

from app.text.convert import kata_to_hira
from app.text.normalize import lemma_reading
from app.text.tokenizer import Tokenizer
from shared.text import SplitMode, Token
from shared.vocab import VocabWord

# Sudachi top-level POS to keep (content words). "*" fillers are already stripped
# from the contract Token, so part_of_speech[0] is the top-level class:
# noun / verb / i-adj / na-adj / adverb / pronoun.
KEEP_TOP = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "代名詞"}
# Noun subtypes dropped even though the top-level is 名詞: proper nouns + numerals.
DROP_NOUN_SUB = {"固有名詞", "数詞"}


def is_content(token: Token) -> bool:
    """True when the morpheme is a content word that counts toward n+1."""
    pos = token.part_of_speech
    if not pos or pos[0] not in KEEP_TOP:
        return False
    if pos[0] == "名詞" and len(pos) > 1 and pos[1] in DROP_NOUN_SUB:
        return False
    return True


def content_words_with_readings(
    tokenizer: Tokenizer, text: str, mode: SplitMode = SplitMode.C
) -> list[VocabWord]:
    """The distinct content words of `text` (lemma + reading), in first-seen order.

    The reading is the lemma's context-disambiguated reading (`normalize`'s
    `lemma_reading`), folded to hiragana to match the store's convention. Dedup is
    by lemma, so `content_words` is exactly this projected to its lemmas. n+1
    ignores the reading; it rides along so generation gets a contextual reading
    from the same tokenization (and the add-on caches it for incremental re-sorts).
    """
    words: list[VocabWord] = []
    seen: set[str] = set()
    for token in tokenizer.tokenize(text, mode):
        if not is_content(token):
            continue
        lemma = token.dictionary_form or token.surface
        if not lemma or lemma in seen:
            continue
        seen.add(lemma)
        reading = kata_to_hira(lemma_reading(tokenizer, token.surface, token.reading, lemma))
        words.append(VocabWord(lemma=lemma, reading=reading))
    return words


def content_words(tokenizer: Tokenizer, text: str, mode: SplitMode = SplitMode.C) -> list[str]:
    """The distinct content-word lemmas of `text`, in first-seen order."""
    return [w.lemma for w in content_words_with_readings(tokenizer, text, mode)]
