"""Word-furigana operation: word -> Anki ruby (e.g. ``主役[しゅやく]``).

Reads the ``word`` input alias and writes the standard Anki furigana encoding
into the ``word-furigana`` output alias, via ``POST /v1/text/furigana``. The
backend returns per-word segments (kanji runs carry a reading, kana runs don't);
:func:`to_anki_ruby` renders them into the ``base[reading]`` form Anki's
``{{furigana:}}`` / ``{{kanji:}}`` filters parse. A word with no segments is left
unchanged.
"""

from ..client import BackendClient
from .base import FieldOperation


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
    input_aliases = ("word",)
    output_alias = "word-furigana"

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        resp = client.post("/v1/text/furigana", {"texts": [s["word"] for s in sources]})
        results = resp.get("results", [])
        out: list[str | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            ruby = to_anki_ruby(result.get("segments", []))
            out[i] = ruby or None
        return out
