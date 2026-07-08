"""Pitch operation: word (+ reading) -> pitch-accent downstep position(s).

Reads the ``word`` and ``word-reading`` input aliases and writes the pitch-accent
downstep position(s) into the ``pitch`` output alias, via ``POST /v1/text/pitch``.
Seeded onto the Lapis ``PitchPosition`` field, which renders the accent graph and
colors the word (heiban / atamadaka / nakadaka / odaka) from the number itself.

Both inputs are required: the reading disambiguates homographs (箸 はし vs 橋 はし),
so a note without a reading is skipped rather than risking the wrong accent. A word
with several accepted accents writes them comma-joined (e.g. ``0,2``); a word with
no pitch data is left unchanged.
"""

from ..client import BackendClient
from .base import FieldOperation


class PitchOperation(FieldOperation):
    key = "pitch"
    label = "Fetch pitch accent"
    input_aliases = ("word", "word-reading")
    output_alias = "pitch"

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        queries = [{"term": s["word"], "reading": s["word-reading"]} for s in sources]
        resp = client.post("/v1/text/pitch", {"queries": queries})
        results = resp.get("results", [])
        out: list[str | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            positions = result.get("positions") or []
            out[i] = ",".join(str(p) for p in positions) if positions else None
        return out
