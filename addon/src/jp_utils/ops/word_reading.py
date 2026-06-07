"""Word-reading operation: word -> kana reading (e.g. ``主役`` -> ``しゅやく``).

Reads the ``word`` input alias and writes its hiragana reading into the
``word-reading`` output alias. The reading is read off the backend's furigana
segmentation (``POST /v1/text/furigana``): each segment contributes its reading,
or its own text when it carries no ruby (already-kana runs). A word with no
segments is left unchanged.
"""

from ..client import BackendClient
from .base import FieldOperation


def to_reading(segments: list[dict]) -> str:
    return "".join(seg.get("reading") or seg.get("text", "") for seg in segments)


class WordReadingOperation(FieldOperation):
    key = "word-reading"
    label = "Fetch word reading"
    input_aliases = ("word",)
    output_alias = "word-reading"

    def compute(self, client: BackendClient, sources: list[dict[str, str]]) -> list[str | None]:
        resp = client.post("/v1/text/furigana", {"texts": [s["word"] for s in sources]})
        results = resp.get("results", [])
        out: list[str | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            reading = to_reading(result.get("segments", []))
            out[i] = reading or None
        return out
