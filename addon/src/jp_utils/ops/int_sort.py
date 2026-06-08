"""Integer-sort operation: reorder a deck's new cards by the ``rank`` field.

A SORT op (not a :class:`FieldOperation`): it writes no field. It reads the
single ``rank`` input alias - an integer value stored on the note - and orders
the deck's NEW cards by it. The wiring layer repositions those cards. Ascending
(the default) puts the lowest value first; for a frequency rank that is the
most-frequent word, the Word deck's "learn common words first" order. Notes with
no/blank/non-numeric value sort last.

``rank`` is the dedicated alias (seeded onto Lapis ``FreqSort``, so it sorts by
frequency rank out of the box). It is also what the n+1 sequencer writes, so this
one op orders both. Direction (ascending/descending) is its only option.
"""

from .base import DIRECTION, SortOperation


class IntSortOperation(SortOperation):
    key = "int-sort"
    label = "Sort by rank"
    input_aliases = ("rank",)
    params_spec = (DIRECTION,)

    def sort_value(self, inputs: dict[str, str], params: dict | None = None) -> int | None:
        raw = (inputs.get("rank") or "").strip()
        try:
            return int(raw)
        except ValueError:
            return None
