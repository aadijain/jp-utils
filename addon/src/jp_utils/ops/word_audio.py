"""Word-audio operation: word (+ reading) -> attached audio file.

Reads the ``word`` and ``word-reading`` input aliases and looks up pronunciation
audio via ``POST /v1/text/audio`` - a backend proxy to the Yomitan local-audio
server. The backend returns the chosen source's bytes (base64) plus a suggested
filename; the wiring layer attaches the bytes to the collection's media folder
and writes a ``[sound:...]`` reference into the ``word-audio`` output alias (Lapis
``ExpressionAudio``). A word with no audio is left unchanged.

Both inputs are required: the reading disambiguates homographs (人 ひと vs じん),
so a note without a reading is skipped rather than risking the wrong audio.
"""

import base64

from ..client import BackendClient
from .base import MediaOperation, MediaResult


class WordAudioOperation(MediaOperation):
    key = "word-audio"
    label = "Fetch word audio"
    description = (
        "Downloads a native pronunciation clip for the word, stores it in the "
        "media collection, and writes a [sound:...] reference to the audio field."
    )
    input_aliases = ("word", "word-reading")
    output_alias = "word-audio"

    def fetch(
        self, client: BackendClient, sources: list[dict[str, str]]
    ) -> list[MediaResult | None]:
        queries = [{"term": s["word"], "reading": s["word-reading"]} for s in sources]
        resp = client.post("/v1/text/audio", {"queries": queries})
        results = resp.get("results", [])
        out: list[MediaResult | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            data = result.get("data")
            filename = result.get("filename")
            if data and filename:
                out[i] = MediaResult(data=base64.b64decode(data), filename=filename)
        return out
