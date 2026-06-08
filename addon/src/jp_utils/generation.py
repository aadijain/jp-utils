"""Pure helpers for vocab-card generation, kept out of the aqt wiring.

The generate op produces new words in the background; the runner creates the notes
on the UI thread. The pure decisions sit in between - which context fields to copy
from the source sentence onto the new word note, and what counts as "the same word"
when deduping against the target deck - and they live here so they can be
unit-tested without Anki.
"""

from .ops.nplus1 import strip_markup

# Fields the generate op SEEDS itself on the new note; never treated as copied context.
SEED_ALIASES = ("word", "word-reading")


def context_aliases(source_mapping: dict, target_mapping: dict) -> list[str]:
    """Aliases to copy 1:1 from the source sentence note onto the new word note.

    An alias is copied when it maps to a real field on BOTH note types, minus the
    seeds the op writes itself (:data:`SEED_ALIASES`). Sorted for a stable order.
    """
    excluded = set(SEED_ALIASES)
    shared = set(source_mapping) & set(target_mapping)
    return sorted(
        alias
        for alias in shared
        if alias not in excluded and source_mapping.get(alias) and target_mapping.get(alias)
    )


def word_key(word: str, reading: str) -> tuple[str, str]:
    """The dedup key of a word note: its ``(word, reading)`` with markup removed.

    The two sides of the match arrive in different shapes: a generated word is a
    tokenizer lemma (always plain text), while an existing note holds whatever the
    user's template put in the field, which may carry ruby or other HTML. Comparing
    them raw silently missed a marked-up note and created a duplicate card, so both
    sides are normalized through :func:`~jp_utils.ops.nplus1.strip_markup` here.
    """
    return (strip_markup(word).strip(), strip_markup(reading).strip())
