"""Pure alias <-> note-field adapter for operations.

Bridges a note's raw ``{field: value}`` contents and its note-type alias mapping
(``{alias: field}``) to the alias-keyed :class:`NoteFields` the framework
consumes, and writes a :class:`NotePlan` back onto a field dict. No ``aqt`` here -
the Anki-facing wiring calls these.
"""

from .base import NoteFields, NotePlan


def to_note_fields(note_id: int, fields: dict[str, str], mapping: dict[str, str]) -> NoteFields:
    """Build the alias-keyed view of a note from its fields and alias mapping.

    A mapped field that is absent from the note resolves to ``""`` (treated as
    unset), so a stale mapping degrades gracefully instead of raising.
    """
    return NoteFields(
        note_id=note_id,
        fields={alias: fields.get(f, "") for alias, f in mapping.items()},
    )


def apply_plan(plan: NotePlan, fields: dict[str, str], mapping: dict[str, str]) -> list[str]:
    """Write a plan's updates into ``fields`` via the alias->field map.

    Mutates ``fields`` in place; returns the names of the fields actually
    changed. An update whose alias isn't mapped, or maps to a field the note
    lacks, is skipped.
    """
    changed: list[str] = []
    for update in plan.updates:
        field_name = mapping.get(update.alias)
        if field_name is not None and field_name in fields:
            fields[field_name] = update.value
            changed.append(field_name)
    return changed
