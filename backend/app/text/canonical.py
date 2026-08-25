"""Collapse an inflected or variant lemma onto the word it actually is.

Sudachi hands back two answers per morpheme and they answer different questions.
``dictionary_form`` is *morphological* - the dictionary form of this surface -
and it is correct: 作れる really is a lexeme whose dictionary form is 作れる,
because Sudachi carries potential verbs as their own entries. ``normalized_form``
is *lexical* - the word this form belongs to - and gives 作る.

Vocabulary state needs the lexical answer. Keying on ``dictionary_form`` alone
files 作れる as a word of its own, so a learner who knows 作る still sees it as
unknown: it inflates n+1 unknown counts and gets offered as a word card.

Keying on ``normalized_form`` alone is worse. Sudachi normalizes to the archaic
orthography - する -> 為る, やる -> 遣る, とても -> 迚も - and those are not dict
headwords, so meaning / frequency / pitch lookups would start missing.

So the reduction is **gated on JPDB frequency**, which separates the two
populations Sudachi's normalization mixes together:

- a potential or colloquial form has no rank of its own (作れる, 子ども, みてぇ)
  while its base does, so the collapse fires;
- an orthographic variant is itself ranked (捜す 2123 -> 探す 421, 気づく,
  綺麗, 私たち), so nothing happens and the store keeps the spelling a card uses.

JPDB rather than jitendex on purpose: jitendex answers "is this a headword",
and kana spellings of kanji words are usually not listed as headwords, so it
misfires on あいだ, あした, あなた, ある, いく. JPDB is a corpus frequency list,
so a rank means "real Japanese uses this form on its own", which is the question
being asked.

The base still has to be a spelling people write, and **that is a comparison,
not a threshold**. JPDB gives two figures per entry - the term as written and
the kana spelling of the same word - and their order is the whole answer:
迚も ranks 152585 against とても's 329, so it is archaic and worthless as a key,
while 省く ranks 10363 against はぶく's 48758, so it is simply an uncommon word
written the normal way. A single rank cannot tell those apart; both look "rare".

When the kana spelling wins that comparison outright, it is not enough to refuse
the base - the row names the spelling that *should* be the key, so the collapse
takes it: とっても keys on とても (329) rather than staying its own word or
becoming 迚も. `written_spelling` is the other side of that trade, because a kana
key is often not a jitendex headword.
"""

from app.dicts import DictCache, Spellings
from app.text.tokenizer import Tokenizer

# Backstop for the bases JPDB gives no kana spelling to compare against: with
# nothing to compare, a common-enough base is the only remaining evidence that a
# spelling is real. It is what refuses 鮟鱇, and 重曹 - the wrong
# normalization of 重そう. Bases that DO have a kana figure are decided by the
# comparison instead, so this ceiling never sees them.
CANONICAL_MAX_RANK = 5000

# How far the kana spelling must beat the as-written one before it takes the key
# rather than merely denying it to the base. A margin rather than "kana is lower"
# because a word genuinely written both ways ranks close either way (嵌まる against
# はまる); only a rout means the kanji spelling is one nobody uses.
KANA_SPELLING_MARGIN = 4


def canonical_lemma(
    tokenizer: Tokenizer,
    dicts: DictCache | None,
    lemma: str,
    reading: str,
    normalized: str,
) -> tuple[str, str]:
    """`(lemma, reading)` reduced to the base word, or unchanged when it is one.

    The reading is re-derived from the base rather than carried over, because the
    caller's describes the form as written and the base is no longer that form
    (作れる ツクレル -> 作る ツクル). Katakana in, katakana out, matching
    `inflection.lemma_reading`.

    Without a dict cache there is no gate, so nothing is collapsed - the same
    degradation the frequency tie-break already takes.
    """
    if dicts is None or not normalized or normalized == lemma:
        return lemma, reading
    if dicts.lookup_frequency(lemma) is not None:
        return lemma, reading  # a ranked form is a word in its own right
    spellings = dicts.lookup_spellings(normalized)
    base = _winning_kana_spelling(spellings, lemma)
    if base is None:
        if not _is_the_written_spelling(spellings):
            return lemma, reading
        base = normalized
    return base, tokenizer.reading_of(base) or reading


def written_spelling(dicts: DictCache, lemma: str, normalized: str) -> str | None:
    """The spelling `canonical_lemma` passed over when it keyed on kana, or None.

    A kana key is frequently not a jitendex headword - it lists 貰う, not もらう -
    so a meaning or pitch lookup on one misses however common the word is. The
    spelling to retry is the one the collapse overrode, and JPDB pairing it back
    to this key is what makes the retry safe: 貰う's kana spelling IS もらう, so it
    is the same word, while 菱 reads ひし rather than びし and is a different word
    that Sudachi merely normalizes びし onto.
    """
    if not normalized or normalized == lemma:
        return None
    return normalized if dicts.lookup_spellings(normalized).kana_form == lemma else None


def _winning_kana_spelling(spellings: Spellings, lemma: str) -> str | None:
    """The kana spelling if it takes the key from the base outright, else None.

    Never the form already written: a kana surface whose base normalizes back to
    that same kana is not a collapse, it is a no-op wearing one.
    """
    kana_form, kana = spellings.kana_form, spellings.kana
    if kana_form is None or kana is None or kana_form == lemma:
        return None
    if spellings.written is None:
        # No rival spelling at all, so - deliberately unlike the ceiling below -
        # how rare the word is says nothing about how it is spelled, and refusing
        # here would cost ツルツル -> つるつる to protect nothing.
        return kana_form
    return kana_form if kana * KANA_SPELLING_MARGIN < spellings.written else None


def _is_the_written_spelling(spellings: Spellings) -> bool:
    """Whether the base is the spelling the language uses for that word.

    `written` beating `kana` settles it outright, however rare the word is. The
    ceiling stays for the two cases with nothing to compare: no kana figure, and
    a base JPDB ranks only through its kana spelling.
    """
    written, kana = spellings.written, spellings.kana
    if written is None:
        return kana is not None and kana <= CANONICAL_MAX_RANK
    if kana is None:
        return written <= CANONICAL_MAX_RANK
    return written < kana or written <= CANONICAL_MAX_RANK
