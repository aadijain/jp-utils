"""Word-audio proxy over the Yomitan local-audio-yomichan server.

The audio server (`../local-audio-yomichan`, standalone `WO_ANKI=1`) is typically
co-hosted with the backend. It is a two-step protocol:

1. ``GET /?term=X&reading=Y`` -> an ``audioSourceList`` JSON listing matching
   sources (``{name, url}``), already ordered by the server's source preference.
2. ``GET <url>`` for a chosen source -> the raw audio bytes.

This module performs BOTH hops server-side and returns the first source's bytes
(base64-encoded) so the add-on talks only to the backend, never to the audio
server directly (the proxy contract). The proxy stays
generic: it is keyed on the configured audio base URL, not hard-wired to any one
source.
"""

import base64
from urllib.parse import urlparse

import httpx

from shared.text import AudioQuery, AudioResult

# Audio-file suffix -> MIME, mirroring the audio server's own table. Used to set a
# content type and pick an extension when the source URL carries one.
_SUFFIX_TO_MIME = {
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
}
_DEFAULT_SUFFIX = ".mp3"


def _suffix(path: str) -> str:
    """The audio extension of a source URL path, defaulting to ``.mp3``."""
    dot = path.rfind(".")
    if dot != -1:
        suffix = path[dot:].lower()
        if suffix in _SUFFIX_TO_MIME:
            return suffix
    return _DEFAULT_SUFFIX


def _media_filename(term: str, reading: str | None, suffix: str) -> str:
    """A deterministic media filename so re-adding the same audio is idempotent.

    Anki sanitizes the name further on write; this only needs to be stable and
    readable. (`jp-utils-<term>[-<reading>].<ext>`)
    """
    stem = f"jp-utils-{term}" + (f"-{reading}" if reading else "")
    return stem + suffix


class AudioProxy:
    """Two-hop client for the local audio server, holding one httpx connection."""

    def __init__(
        self, base_url: str, *, client: httpx.Client | None = None, timeout: float = 10.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def lookup(self, query: AudioQuery, sources: list[str] | None = None) -> AudioResult:
        """Resolve one word's audio to base64 bytes, or an empty result if none.

        A word with no matching source is NOT an error - it returns a result with
        ``data=None``. Transport failures (server down) propagate to the caller as
        an :class:`httpx.HTTPError` for the endpoint to map onto the error contract.
        """
        empty = AudioResult(term=query.term, reading=query.reading)
        params: dict[str, str] = {"term": query.term}
        if query.reading:
            params["reading"] = query.reading
        if sources:
            params["sources"] = ",".join(sources)

        listing = self._client.get(f"{self.base_url}/", params=params)
        listing.raise_for_status()
        audio_sources = listing.json().get("audioSources", [])
        if not audio_sources:
            return empty

        chosen = audio_sources[0]
        url = chosen.get("url")
        if not url:
            return empty

        # Reconstruct the fetch URL against our own base so the audio server's
        # Host-derived netloc can't redirect us elsewhere.
        parsed = urlparse(url)
        file_url = f"{self.base_url}{parsed.path}"
        if parsed.query:
            file_url += f"?{parsed.query}"

        audio = self._client.get(file_url)
        audio.raise_for_status()

        suffix = _suffix(parsed.path)
        return AudioResult(
            term=query.term,
            reading=query.reading,
            source=chosen.get("name"),
            filename=_media_filename(query.term, query.reading, suffix),
            content_type=audio.headers.get("content-type") or _SUFFIX_TO_MIME[suffix],
            data=base64.b64encode(audio.content).decode("ascii"),
        )
