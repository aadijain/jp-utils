"""Frequency operation: word (+ reading) -> JPDB frequency rank (the sort key).

Reads the ``word`` and ``word-reading`` input aliases and writes the JPDB rank
(lower = more frequent) into the ``frequency`` output alias, via
``POST /v1/text/frequency``. A word with no rank is left unchanged.

Both inputs are required: the reading disambiguates homographs (人 ひと vs じん),
so a note without a reading is skipped rather than risking the wrong rank. The
backend uses the reading to resolve the right entry (and as a kana-form fallback
when the kanji term itself isn't ranked).
"""

from ..client import BackendClient
from .base import FieldOperation


class FrequencyOperation(FieldOperation):
    key = "frequency"
    label = "Fetch frequency rank"
    description = (
        "Fetches the word's JPDB frequency rank and writes it to the rank field. "
        'Typically paired with "Sort by rank" to order new cards by how common '
        "the word is."
    )
    input_aliases = ("word", "word-reading")
    output_alias = "frequency"

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        queries = [{"term": s["word"], "reading": s["word-reading"]} for s in sources]
        resp = client.post("/v1/text/frequency", {"queries": queries})
        results = resp.get("results", [])
        out: list[str | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            rank = result.get("rank")
            out[i] = str(rank) if rank is not None else None
        return out
