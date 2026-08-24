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
misfires on あいだ, あした, あなた, ある, いく - 373 such collapses against
JPDB's 192 over the same corpus. JPDB is a corpus frequency list, so a rank means
"real Japanese uses this form on its own", which is the question being asked.
"""

from app.dicts import DictCache
from app.text.tokenizer import Tokenizer

# The base must itself be a reasonably common word. Sudachi's normalization
# bottoms out in spellings nobody writes (やれる -> 遣る 36634, とっても -> 迚も
# 152585, あんこう -> 鮟鱇 119997) and collapsing onto those trades one key
# nothing holds for another. Measured over the 2390-card corpus: the gain
# plateaus by 5000 (+17 one-unknown cards, the same as no ceiling at all) while
# the ceiling drops the whole junk tail.
CANONICAL_MAX_RANK = 5000


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
    base_rank = dicts.lookup_frequency(normalized)
    if base_rank is None or base_rank > CANONICAL_MAX_RANK:
        return lemma, reading
    return normalized, tokenizer.reading_of(normalized) or reading
