"""Word-definition operation: word + reading -> formatted dictionary senses.

Reads the ``word`` and ``word-reading`` input aliases and writes a Jitendex
definition into the ``definition`` output alias, via ``POST /v1/text/meaning``.
The backend returns per-sense structure (each sense = its synonymous glosses, a
part-of-speech list, and example sentences); this op renders that into one of two
HTML layouts chosen via ``params``. A word with no entry is left unchanged.

Both inputs are required: the reading disambiguates senses across homographs
(人 ひと vs じん), so a note without a reading is skipped rather than risking the
wrong definition. The op consumes an already-chosen reading - picking it is the
word-reading op's job, not this op's.

Formatting (``params_spec``):
- ``format``: ``expanded`` (an ``<ol>`` of senses, each with a nested ``<ul>``
  giving every gloss its own bullet) or ``compressed`` (an ``<ol>`` with one
  line per sense, its glosses joined). Both group glosses by sense.
- ``include_pos`` prefixes each sense with its part of speech; ``include_examples``
  adds one example sentence per sense; ``include_readings`` appends an
  all-readings line (``食べる readings: たべる``) after the definition.

The op key is ``word-definition``; its output alias stays ``definition`` (->
Lapis ``MainDefinition``).
"""

from ..client import BackendClient
from .base import ONLY_IF_EMPTY, FieldOperation, ParamSpec

FORMAT_EXPANDED = "expanded"
FORMAT_COMPRESSED = "compressed"


def _pos_prefix(sense: dict, include_pos: bool) -> str:
    pos = sense.get("pos") or []
    return f"[{', '.join(pos)}] " if include_pos and pos else ""


def _example_html(sense: dict, include_examples: bool) -> str:
    """Render at most one example sentence (Japanese, then English) for a sense."""
    examples = sense.get("examples") or []
    if not include_examples or not examples:
        return ""
    ex = examples[0]
    ja = ex.get("ja", "")
    en = ex.get("en", "")
    if not ja:
        return ""
    return f"<div>{ja}</div>" + (f"<div>{en}</div>" if en else "")


def _sense_inner(sense: dict, fmt: str, inc_pos: bool, inc_ex: bool) -> str:
    """Render a sense's content (POS prefix + glosses + example), without a list wrapper."""
    prefix = _pos_prefix(sense, inc_pos)
    if fmt == FORMAT_COMPRESSED:
        body = "; ".join(sense["glosses"])
    else:  # FORMAT_EXPANDED: every gloss its own bullet
        body = "<ul>" + "".join(f"<li>{g}</li>" for g in sense["glosses"]) + "</ul>"
    return prefix + body + _example_html(sense, inc_ex)


def _format(result: dict, params: dict) -> str | None:
    entries = result.get("entries", [])
    senses = [s for entry in entries for s in entry.get("senses", []) if s.get("glosses")]
    if not senses:
        return None

    fmt = params.get("format", FORMAT_EXPANDED)
    inc_pos = bool(params.get("include_pos"))
    inc_ex = bool(params.get("include_examples"))

    foot = ""
    readings = result.get("all_readings") or []
    if params.get("include_readings") and readings:
        lemma = result.get("lemma", "")
        label = f"{lemma} readings" if lemma else "Readings"
        foot = f"<div>{label}: {', '.join(readings)}</div>"

    inners = [_sense_inner(s, fmt, inc_pos, inc_ex) for s in senses]
    body = "<ol>" + "".join(f"<li>{inner}</li>" for inner in inners) + "</ol>"
    return body + foot


class WordDefinitionOperation(FieldOperation):
    key = "word-definition"
    label = "Fetch definition"
    input_aliases = ("word", "word-reading")
    output_alias = "definition"
    params_spec = (
        ONLY_IF_EMPTY,
        ParamSpec(
            "format",
            "Layout",
            "choice",
            default=FORMAT_EXPANDED,
            choices=(FORMAT_EXPANDED, FORMAT_COMPRESSED),
            description="Arrangement of the senses.",
        ),
        ParamSpec(
            "include_pos",
            "Include part of speech",
            "bool",
            default=False,
            description="Show the part of speech before each sense (noun, verb, adjective...).",
        ),
        ParamSpec(
            "include_examples",
            "Include example sentence",
            "bool",
            default=False,
            description="Add an example sentence with translation under each sense.",
        ),
        ParamSpec(
            "include_readings",
            "Include all readings",
            "bool",
            default=False,
            description="Append a line with every reading of the word (人 readings: ひと, じん).",
        ),
    )

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        params = params or {}
        queries = [{"lemma": s["word"], "reading": s["word-reading"]} for s in sources]
        resp = client.post("/v1/text/meaning", {"queries": queries})
        results = resp.get("results", [])
        out: list[str | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            out[i] = _format(result, params)
        return out
