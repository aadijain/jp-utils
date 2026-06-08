"""Pure helpers for vocab-card generation, kept out of the aqt wiring.

The generate op produces new words in the background; the runner creates the notes
on the UI thread. One pure decision sits in between - which context fields to copy
from the source sentence onto the new word note - and it lives here so it can be
unit-tested without Anki.
"""

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
