import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.text.audio import AudioProxy
from shared.text import AudioQuery

TEST_TOKEN = "test-token"

_AUDIO_BYTES = b"ID3fake-mp3-bytes"


def _fake_audio_server(*, sources: list[dict] | None = None):
    """A MockTransport emulating the two-hop local audio server protocol."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":  # audioSourceList listing
            term = request.url.params.get("term")
            listed = (
                sources
                if sources is not None
                else [
                    {"name": "NHK", "url": f"http://audio-host/nhk16/{term}.mp3"},
                    {"name": "Forvo", "url": f"http://audio-host/forvo/{term}.opus"},
                ]
            )
            return httpx.Response(200, json={"type": "audioSourceList", "audioSources": listed})
        # otherwise a file fetch: return the raw audio bytes
        return httpx.Response(200, content=_AUDIO_BYTES, headers={"content-type": "audio/mpeg"})

    return httpx.MockTransport(handler)


def _proxy(transport: httpx.MockTransport) -> AudioProxy:
    return AudioProxy("http://audio-host:5050", client=httpx.Client(transport=transport))


def test_lookup_returns_first_source_bytes() -> None:
    proxy = _proxy(_fake_audio_server())
    result = proxy.lookup(AudioQuery(term="水", reading="みず"))
    assert result.source == "NHK"
    assert result.filename == "jp-utils-水-みず.mp3"
    assert result.content_type == "audio/mpeg"
    assert base64.b64decode(result.data) == _AUDIO_BYTES


def test_lookup_no_sources_is_empty_not_error() -> None:
    proxy = _proxy(_fake_audio_server(sources=[]))
    result = proxy.lookup(AudioQuery(term="存在しない"))
    assert result.data is None
    assert result.source is None
    assert result.filename is None


def test_lookup_filename_omits_reading_when_absent() -> None:
    proxy = _proxy(_fake_audio_server())
    result = proxy.lookup(AudioQuery(term="水"))
    assert result.filename == "jp-utils-水.mp3"


def test_lookup_extension_from_source_url() -> None:
    sources = [{"name": "Forvo", "url": "http://audio-host/forvo/word.opus"}]
    proxy = _proxy(_fake_audio_server(sources=sources))
    result = proxy.lookup(AudioQuery(term="word"))
    assert result.filename.endswith(".opus")


def test_lookup_refetches_against_base_url_not_returned_host() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/":
            return httpx.Response(
                200,
                json={
                    "type": "audioSourceList",
                    "audioSources": [{"name": "X", "url": "http://evil-host:9999/nhk16/a.mp3"}],
                },
            )
        return httpx.Response(200, content=_AUDIO_BYTES, headers={"content-type": "audio/mpeg"})

    proxy = _proxy(httpx.MockTransport(handler))
    proxy.lookup(AudioQuery(term="a"))
    # the file fetch must target our configured base, never the listing's host
    assert any(u.startswith("http://audio-host:5050/nhk16/a.mp3") for u in seen)
    assert not any("evil-host" in u for u in seen)


# ── Endpoint ─────────────────────────────────────────────────────────────────


@pytest.fixture
def audio_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(api_token=TEST_TOKEN)
    app.state.audio_proxy = _proxy(_fake_audio_server())
    return TestClient(app, raise_server_exceptions=False)


def test_audio_endpoint(audio_client: TestClient) -> None:
    resp = audio_client.post(
        "/v1/text/audio",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"queries": [{"term": "水", "reading": "みず"}, {"term": "存在しない"}]},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert base64.b64decode(results[0]["data"]) == _AUDIO_BYTES
    # second query: the mock always lists sources, so it also resolves; assert shape
    assert results[1]["term"] == "存在しない"


def test_audio_endpoint_server_down_is_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(api_token=TEST_TOKEN)
    app.state.audio_proxy = _proxy(httpx.MockTransport(handler))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/v1/text/audio",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"queries": [{"term": "水"}]},
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "audio_unavailable"


def test_audio_endpoint_unavailable_without_proxy() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(api_token=TEST_TOKEN)
    app.state.audio_proxy = None
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/v1/text/audio",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"queries": [{"term": "水"}]},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "audio_unavailable"


def test_audio_endpoint_requires_auth(audio_client: TestClient) -> None:
    resp = audio_client.post("/v1/text/audio", json={"queries": [{"term": "水"}]})
    assert resp.status_code == 401
