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
- ``include_pos`` prefixes each sense with its part of speech as coloured chips;
  ``include_examples`` adds one example sentence per sense in an accented box (the
  English translation dimmed); ``include_readings`` appends a dimmed all-readings
  footer (``食べる readings: たべる``) after the definition.

**Styling is self-contained inline CSS** (no card-template/CSS dependency): every
styled element carries a ``style="..."`` attribute, theme-adaptive via
``currentColor`` / ``color-mix`` so the accents track the card's text colour in
both light and dark. The whole output is wrapped in a ``jpu-definition`` div as an
optional theming hook. See the note-type field reference for the
Yomitan glossary export this draws inspiration from.

The op key is ``word-definition``; its output alias stays ``definition`` (->
Lapis ``MainDefinition``).
"""

from ..client import BackendClient
from .base import ONLY_IF_EMPTY, FieldOperation, ParamSpec

FORMAT_EXPANDED = "expanded"
FORMAT_COMPRESSED = "compressed"

# Inline styles, kept as named constants so the markup below stays readable. Colours
# are theme-adaptive: chips use a fixed neutral grey (legible on light + dark), while
# borders/tints derive from `currentColor` (the card's text colour) via `color-mix`,
# and de-emphasis uses `opacity` (universally supported; degrades gracefully).
_CONTAINER_STYLE = "text-align:left;"
_CHIP_STYLE = (
    "display:inline-block;background:#565656;color:#fff;border-radius:.3em;"
    "font-size:.78em;font-weight:bold;padding:.05em .4em;margin:0 .35em .15em 0;"
    "vertical-align:text-bottom;"
)
_GLOSS_UL_STYLE = "margin:.15em 0;padding-left:1.2em;"
_SENSE_OL_STYLE = "margin:.15em 0;padding-left:1.4em;"
_SENSE_LI_STYLE = "margin:.3em 0;"
_EXAMPLE_BOX_STYLE = (
    "border-left:3px solid currentColor;"
    "background:color-mix(in srgb,currentColor 6%,transparent);"
    "border-radius:.3em;padding:.3em .5em;margin:.3em 0;"
)
_EXAMPLE_EN_STYLE = "opacity:.6;font-size:.85em;"
_READINGS_STYLE = (
    "margin-top:.5em;padding-top:.35em;"
    "border-top:1px solid color-mix(in srgb,currentColor 25%,transparent);"
    "font-size:.85em;opacity:.7;"
)


def _pos_prefix(sense: dict, include_pos: bool) -> str:
    """Render the sense's parts of speech as coloured chips (empty when off/absent)."""
    pos = sense.get("pos") or []
    if not include_pos or not pos:
        return ""
    return "".join(f'<span style="{_CHIP_STYLE}">{p}</span>' for p in pos)


def _example_html(sense: dict, include_examples: bool) -> str:
    """Render at most one example sentence (Japanese, then dimmed English) for a sense."""
    examples = sense.get("examples") or []
    if not include_examples or not examples:
        return ""
    ex = examples[0]
    ja = ex.get("ja", "")
    en = ex.get("en", "")
    if not ja:
        return ""
    inner = f'<div lang="ja">{ja}</div>'
    if en:
        inner += f'<div style="{_EXAMPLE_EN_STYLE}">{en}</div>'
    return f'<div style="{_EXAMPLE_BOX_STYLE}">{inner}</div>'


def _sense_inner(sense: dict, fmt: str, inc_pos: bool, inc_ex: bool) -> str:
    """Render a sense's content (POS chips + glosses + example), without a list wrapper."""
    prefix = _pos_prefix(sense, inc_pos)
    if fmt == FORMAT_COMPRESSED:
        body = "; ".join(sense["glosses"])
    else:  # FORMAT_EXPANDED: every gloss its own bullet
        body = (
            f'<ul style="{_GLOSS_UL_STYLE}">'
            + "".join(f"<li>{g}</li>" for g in sense["glosses"])
            + "</ul>"
        )
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
        foot = f'<div style="{_READINGS_STYLE}">{label}: {", ".join(readings)}</div>'

    inners = [_sense_inner(s, fmt, inc_pos, inc_ex) for s in senses]
    body = (
        f'<ol style="{_SENSE_OL_STYLE}">'
        + "".join(f'<li style="{_SENSE_LI_STYLE}">{inner}</li>' for inner in inners)
        + "</ol>"
    )
    return f'<div class="jpu-definition" style="{_CONTAINER_STYLE}">{body + foot}</div>'


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
