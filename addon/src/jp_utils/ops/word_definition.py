"""Word-definition operation: word + reading -> formatted dictionary senses.

Reads the ``word`` and ``word-reading`` input aliases and writes a Jitendex
definition into the ``word-meaning`` output alias, via ``POST /v1/text/meaning``.
The backend returns per-sense structure (each sense = its synonymous glosses, a
part-of-speech list, and example sentences); this op renders that into one of two
HTML layouts chosen via ``params``. A word with no entry is left unchanged.

Both inputs are required: the reading disambiguates senses across homographs
(人 ひと vs じん), so a note without a reading is skipped rather than risking the
wrong definition. The op consumes an already-chosen reading - picking it is the
word-reading op's job, not this op's.

Formatting (``params_spec``):
- ``format``: ``expanded`` (a list of senses, each with a nested ``<ul>``
  giving every gloss its own bullet) or ``compressed`` (one line per sense, its
  glosses joined by `` | ``). Both group glosses by sense and label each with a
  circled number (①②③...); native list numbering is disabled.
- ``include_pos`` prefixes each sense with its part of speech as coloured chips;
  ``include_examples`` adds one example sentence per sense in an accented box
  (furigana ruby + the headword shown bold in the accent colour from the source's
  own keyword marking, English translation dimmed); ``include_readings`` appends a
  labelled ``Readings`` chip row listing every reading after the definition.

**Styling is self-contained inline CSS** (no card-template/CSS dependency): every
styled element carries a ``style="..."`` attribute, theme-adaptive via
``currentColor`` / ``color-mix`` so the accents track the card's text colour in
both light and dark. The whole output is wrapped in a ``jpu-definition`` div as an
optional theming hook. See the note-type field reference for the
Yomitan glossary export this draws inspiration from.

The op key is ``word-definition``; its output alias is ``word-meaning`` (->
Lapis ``MainDefinition``).
"""

import html

from ..client import BackendClient
from .base import ONLY_IF_EMPTY, FieldOperation, ParamSpec

FORMAT_EXPANDED = "expanded"
FORMAT_COMPRESSED = "compressed"

# Inline styles, kept as named constants so the markup below stays readable. Colours
# are theme-adaptive: chips use a fixed neutral grey (legible on light + dark), and
# borders/tints derive from `currentColor` (the card's text colour) via `color-mix`.
# Accents (sense markers, the example headword, the readings chip) use one fixed hue
# `_ACCENT` - like the fixed chip grey, a real colour is needed to read as an accent
# distinct from the card's own text; it is tuned to stay legible on light + dark.
_ACCENT = "#6c8cf5"
_CONTAINER_STYLE = "text-align:left;"
_CHIP_STYLE = (
    "display:inline-block;background:#565656;color:#fff;border-radius:.3em;"
    "font-size:.78em;font-weight:bold;padding:.05em .4em;margin:0 .35em .15em 0;"
    "vertical-align:text-bottom;"
)
_GLOSS_UL_STYLE = "margin:.15em 0;padding-left:1.2em;"
# Senses carry their own circled markers (below), so the list drops native numbering.
_SENSE_OL_STYLE = "margin:.15em 0;padding-left:0;list-style:none;"
# Hanging indent: the marker sits in the left pad (negative text-indent), so wrapped
# gloss lines and the block-level example box align under the sense text, not the
# marker. Block children reset `text-indent:0` (else they inherit the negative pull).
_SENSE_LI_STYLE = "margin:.3em 0;padding-left:1.5em;text-indent:-1.5em;"
_MARKER_STYLE = f"color:{_ACCENT};font-weight:bold;margin-right:.4em;"

# Glosses within one sense are synonymous phrasings; a pipe reads cleaner than a
# semicolon (mirrors the Yomitan glossary export).
_GLOSS_SEP = " | "
# Circled digits ①..⑳ (U+2460..U+2473); senses past 20 fall back to "N.".
_CIRCLED = "".join(chr(0x2460 + i) for i in range(20))
_EXAMPLE_BOX_STYLE = (
    "text-indent:0;"  # reset the sense li's hanging indent for this block child
    "border-left:3px solid currentColor;"
    "background:color-mix(in srgb,currentColor 6%,transparent);"
    "border-radius:.3em;padding:.3em .5em;margin:.3em 0;"
)
_EXAMPLE_EN_STYLE = "opacity:.6;font-size:.85em;"
# The headword occurrence in the example: bold + the accent colour, no background, so
# it stands out against the example box on light + dark without a highlighter block.
_HIGHLIGHT_STYLE = f"font-weight:bold;color:{_ACCENT};"
# Readings footer: a labelled row rather than a dim footnote, so it reads as part of
# the entry. The "Readings" chip is accent-tinted (color-coded apart from the grey POS
# chips); `text-indent:0` clears the sense li's hanging indent.
_READINGS_STYLE = "margin-top:.55em;text-indent:0;"
_READINGS_CHIP_STYLE = (
    "display:inline-block;border-radius:.3em;font-size:.72em;font-weight:bold;"
    "letter-spacing:.04em;padding:.08em .5em;text-transform:uppercase;"
    f"color:{_ACCENT};background:color-mix(in srgb,{_ACCENT} 20%,transparent);"
    f"border:1px solid color-mix(in srgb,{_ACCENT} 45%,transparent);"
)
_READINGS_VAL_STYLE = "opacity:.85;margin-left:.4em;"


def _marker(n: int) -> str:
    """A circled sense number (①..⑳), styled; plain ``N.`` beyond the circled range."""
    glyph = _CIRCLED[n - 1] if 1 <= n <= len(_CIRCLED) else f"{n}."
    return f'<span style="{_MARKER_STYLE}">{glyph}</span>'


def _pos_prefix(sense: dict, include_pos: bool) -> str:
    """Render the sense's parts of speech as coloured chips (empty when off/absent)."""
    pos = sense.get("pos") or []
    if not include_pos or not pos:
        return ""
    return "".join(f'<span style="{_CHIP_STYLE}">{html.escape(p)}</span>' for p in pos)


def _example_ja_html(segments: list[dict]) -> str:
    """Render example segments as ruby HTML, highlighting the keyword occurrence.

    A segment with a reading becomes ``<ruby>base<rt>reading</rt></ruby>``; a
    plain run is emitted as-is. Keyword segments (jitendex's headword highlight)
    are wrapped in a coloured span.
    """
    parts: list[str] = []
    for seg in segments:
        text = html.escape(seg.get("text", ""))
        reading = html.escape(seg.get("reading", ""))
        piece = f"<ruby>{text}<rt>{reading}</rt></ruby>" if reading else text
        if seg.get("keyword"):
            piece = f'<span style="{_HIGHLIGHT_STYLE}">{piece}</span>'
        parts.append(piece)
    return "".join(parts)


def _example_html(sense: dict, include_examples: bool) -> str:
    """Render at most one example sentence (Japanese, then dimmed English) for a sense.

    Uses the source furigana + keyword highlight when present (``segments``),
    falling back to the plain ``ja`` line otherwise.
    """
    examples = sense.get("examples") or []
    if not include_examples or not examples:
        return ""
    ex = examples[0]
    ja = ex.get("ja", "")
    segments = ex.get("segments") or []
    en = ex.get("en", "")
    if not ja and not segments:
        return ""
    ja_html = _example_ja_html(segments) if segments else html.escape(ja)
    inner = f'<div lang="ja">{ja_html}</div>'
    if en:
        inner += f'<div style="{_EXAMPLE_EN_STYLE}">{html.escape(en)}</div>'
    return f'<div style="{_EXAMPLE_BOX_STYLE}">{inner}</div>'


def _sense_inner(sense: dict, fmt: str, inc_pos: bool, inc_ex: bool) -> str:
    """Render a sense's content (POS chips + glosses + example), without a list wrapper."""
    prefix = _pos_prefix(sense, inc_pos)
    glosses = [html.escape(g) for g in sense["glosses"]]
    if fmt == FORMAT_COMPRESSED:
        body = _GLOSS_SEP.join(glosses)
    else:  # FORMAT_EXPANDED: every gloss its own bullet
        body = (
            f'<ul style="{_GLOSS_UL_STYLE}">' + "".join(f"<li>{g}</li>" for g in glosses) + "</ul>"
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
        foot = (
            f'<div style="{_READINGS_STYLE}">'
            f'<span style="{_READINGS_CHIP_STYLE}">Readings</span>'
            f'<span style="{_READINGS_VAL_STYLE}">{html.escape(", ".join(readings))}</span></div>'
        )

    inners = [_sense_inner(s, fmt, inc_pos, inc_ex) for s in senses]
    body = (
        f'<ol style="{_SENSE_OL_STYLE}">'
        + "".join(
            f'<li style="{_SENSE_LI_STYLE}">{_marker(i + 1)}{inner}</li>'
            for i, inner in enumerate(inners)
        )
        + "</ol>"
    )
    return f'<div class="jpu-definition" style="{_CONTAINER_STYLE}">{body + foot}</div>'


class WordDefinitionOperation(FieldOperation):
    key = "word-definition"
    label = "Fetch definition"
    description = (
        "Fetches dictionary definitions for the word (using the reading to "
        "disambiguate when present) and writes the formatted senses to the "
        "definition field."
    )
    input_aliases = ("word", "word-reading")
    output_alias = "word-meaning"
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
            description="Append a labelled Readings row listing every reading of the word.",
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
