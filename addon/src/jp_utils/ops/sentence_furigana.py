"""Sentence-furigana operation: HTML-aware ``sentence`` -> ``sentence-furigana``.

The ``Sentence`` field carries inline HTML (e.g. ``<b>...</b>`` around the mined
word). Tokenizing the raw markup mangles the tags, so this op splits each
sentence into HTML-tag chunks and plain-text runs, furigana's only the text runs
(``POST /v1/text/furigana``, batched across every run of every note in one round
trip), and stitches the tags back in unchanged. Each text run is rendered with
:func:`~jp_utils.ops.word_furigana.to_anki_ruby`, giving the spaced
``base[reading]`` form Lapis ``SentenceFurigana`` expects with bold preserved.
"""

import re

from ..client import BackendClient
from .base import FieldOperation
from .word_furigana import to_anki_ruby

# Splits on whole HTML tags, keeping them: ``re.split`` puts the captured tag at
# the odd indices and the surrounding text at the even ones.
_TAG_RE = re.compile(r"(<[^>]+>)")


def split_html(text: str) -> list[tuple[str, bool]]:
    """Split into ``(chunk, is_tag)`` parts, dropping empties.

    HTML tags are passed through verbatim (``is_tag`` True); the text runs
    between them (``is_tag`` False) are what gets furigana'd.
    """
    return [(chunk, i % 2 == 1) for i, chunk in enumerate(_TAG_RE.split(text)) if chunk]


class SentenceFuriganaOperation(FieldOperation):
    key = "sentence-furigana"
    label = "Add sentence furigana"
    description = (
        "Adds furigana ruby to the whole sentence and writes the result to the "
        "sentence-furigana field. HTML-aware: existing markup in the sentence is "
        "preserved."
    )
    input_aliases = ("sentence",)
    output_alias = "sentence-furigana"

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        split = [split_html(s["sentence"]) for s in sources]
        texts = [chunk for parts in split for chunk, is_tag in parts if not is_tag]
        resp = client.post("/v1/text/furigana", {"texts": texts}) if texts else {}
        results = resp.get("results", [])
        rubies = [to_anki_ruby(r.get("segments", [])) for r in results]

        out: list[str | None] = []
        cursor = 0
        for parts in split:
            pieces: list[str] = []
            for chunk, is_tag in parts:
                if is_tag:
                    pieces.append(chunk)
                else:
                    pieces.append(rubies[cursor] if cursor < len(rubies) else chunk)
                    cursor += 1
            out.append("".join(pieces))
        return out
