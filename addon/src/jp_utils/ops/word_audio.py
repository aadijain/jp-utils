"""Word-audio operation: word (+ reading) -> attached audio file.

Reads the ``word`` and ``word-reading`` input aliases and looks up pronunciation
audio via ``POST /v1/text/audio`` - a backend proxy to the Yomitan local-audio
server. The backend returns the chosen source's bytes (base64) plus a suggested
filename; the wiring layer attaches the bytes to the collection's media folder
and writes a ``[sound:...]`` reference into the ``word-audio`` output alias (Lapis
``ExpressionAudio``). A word with no audio is left unchanged.

Both inputs are required: the reading disambiguates homographs (人 ひと vs じん),
so a note without a reading is skipped rather than risking the wrong audio.

This is the one op whose backend cost scales with the batch (two serial network
hops per word), so it sends a per-word timeout budget rather than the client's
flat default.
"""

import base64

from ..client import DEFAULT_TIMEOUT, BackendClient
from .base import MediaOperation, MediaResult

# The backend resolves each word with two serial hops to the local audio server
# (list the sources, then download the chosen file), so this endpoint's cost grows
# with the batch - unlike every other op, which answers from SQLite. A start sweep
# over a few hundred new word cards would blow the client's flat default timeout
# long before the backend was done, failing the whole run. Budget per word instead,
# never going below the default.
_TIMEOUT_PER_WORD = 2.0


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
        timeout = max(DEFAULT_TIMEOUT, _TIMEOUT_PER_WORD * len(queries))
        resp = client.post("/v1/text/audio", {"queries": queries}, timeout=timeout)
        results = resp.get("results", [])
        out: list[MediaResult | None] = [None] * len(sources)
        for i, result in enumerate(results[: len(sources)]):
            data = result.get("data")
            filename = result.get("filename")
            if data and filename:
                out[i] = MediaResult(data=base64.b64decode(data), filename=filename)
        return out
