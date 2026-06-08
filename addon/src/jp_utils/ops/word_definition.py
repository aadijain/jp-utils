"""Word-definition operation: word + reading -> dictionary glosses.

Reads the ``word`` and ``word-reading`` input aliases and writes a Jitendex
definition into the ``definition`` output alias, via ``POST /v1/text/meaning``.
Every gloss (each sense and its synonymous phrasings) becomes an ``<li>`` in a
single ``<ul>`` HTML bullet list (the field renders as HTML in Anki). A word with
no entry is left unchanged.

Both inputs are required: the reading disambiguates senses across homographs
(人 ひと vs じん), so a note without a reading is skipped rather than risking the
wrong definition. The op consumes an already-chosen reading - picking it is the
word-reading op's job, not this op's.

The op key is ``word-definition`` (sharing the ``word-`` prefix of the word
enrichment ops), but its output alias stays ``definition`` (-> Lapis
``MainDefinition``). A configurable output format + an optional "all readings"
line are planned future work.
"""

import html

from ..client import BackendClient
from .base import FieldOperation


def _format(entries: list[dict]) -> str | None:
    glosses = [g for entry in entries for g in entry.get("glosses", []) if g]
    if not glosses:
        return None
    return "<ul>" + "".join(f"<li>{html.escape(g)}</li>" for g in glosses) + "</ul>"


class WordDefinitionOperation(FieldOperation):
    key = "word-definition"
    label = "Fetch definition"
    input_aliases = ("word", "word-reading")
    output_alias = "definition"

    def compute(self, client: BackendClient, sources: list[dict[str, str]]) -> list[str | None]:
        queries = [{"lemma": s["word"], "reading": s["word-reading"]} for s in sources]
        resp = client.post("/v1/text/meaning", {"queries": queries})
        results = resp.get("results", [])
        out: list[str | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            out[i] = _format(result.get("entries", []))
        return out
