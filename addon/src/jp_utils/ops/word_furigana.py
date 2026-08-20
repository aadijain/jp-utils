"""Word-furigana operation: word -> Anki ruby (e.g. ``主役[しゅやく]``).

Reads the ``word`` input alias and writes the standard Anki furigana encoding
into the ``word-furigana`` output alias, via ``POST /v1/text/furigana``. The
backend returns per-word segments (kanji runs carry a reading, kana runs don't);
:func:`to_anki_ruby` renders them into the ``base[reading]`` form Anki's
``{{furigana:}}`` / ``{{kanji:}}`` filters parse. A word with no segments is left
unchanged.

The card's ``word-reading`` is sent along as the backend's per-text reading
override, so the ruby agrees with the reading field the rest of the word pipeline
uses. Without it the backend picks the curated JmdictFurigana row by the
tokenizer's CONTEXT-FREE reading, which is the wrong one for a jukujikun or a
variant-unified word (鍛冶 -> タンヤ, 十分 -> ジュウフン). The input is OPTIONAL:
a card not yet enriched with a reading must still get ruby, exactly as
``sync-word-status`` treats it. Note the reading a note carries is the one it had
when the sweep STARTED - a ``word-reading`` computed by an earlier op in the same
run is not visible here (:func:`jp_utils.ops.base.plan_operations` plans every op
off the same note snapshot); generated word cards are seeded with their reading
at creation, so they enrich correctly on the next sweep.
"""

from ..client import BackendClient
from .base import FieldOperation
from .nplus1 import strip_markup


def to_anki_ruby(segments: list[dict]) -> str:
    """Render furigana segments into Anki ruby (``base[reading]``).

    A separating space precedes a ruby run only when the preceding run was plain
    kana, so the filter doesn't greedily fold that kana into the ruby base
    (matching the convention ``今日[きょう]の 授業[じゅぎょう]``).
    """
    out: list[str] = []
    last_plain = False
    for seg in segments:
        text, reading = seg.get("text", ""), seg.get("reading", "")
        if reading:
            if out and last_plain:
                out.append(" ")
            out.append(f"{text}[{reading}]")
            last_plain = False
        else:
            out.append(text)
            last_plain = True
    return "".join(out)


class WordFuriganaOperation(FieldOperation):
    key = "word-furigana"
    label = "Add word furigana"
    description = (
        "Converts the mined word into Anki ruby furigana (e.g. 主役[しゅやく]) and "
        "writes it to its own field. Uses the reading, when mapped, to pick the "
        "correct kanji segmentation."
    )
    # `word` -> the text to annotate (REQUIRED). `word-reading` -> the reading the
    # ruby must agree with, OPTIONAL: sent when present, else the backend falls
    # back to the tokenizer's reading (a card not yet enriched with one).
    input_aliases = ("word",)
    optional_input_aliases = ("word-reading",)
    output_alias = "word-furigana"

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        body: dict = {"texts": [s["word"] for s in sources]}
        readings = [strip_markup(s.get("word-reading", "")).strip() for s in sources]
        # Omit the key entirely when no note has a reading: the request is then
        # byte-identical to the word-reading op's, which `post_pure` dedups.
        if any(readings):
            body["readings"] = readings
        # post_pure: this endpoint is a pure lookup (and the reading op sends the
        # same request when neither has a reading to override with).
        resp = client.post_pure("/v1/text/furigana", body)
        results = resp.get("results", [])
        out: list[str | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            ruby = to_anki_ruby(result.get("segments", []))
            out[i] = ruby or None
        return out
