"""Tests for the stdlib backend client.

A tiny real HTTP server stands in for the backend so the client's request,
parse, and error-mapping paths are exercised end to end (no Anki, no mocks of
``urllib`` internals).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jp_utils.client import BackendClient, BackendError

TOKEN = "test-token"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the test server
        pass

    def _send(self, status: int, payload: dict | None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "tokenizer_ready": True})
            return
        if self.path == "/v1/ping":
            if self.headers.get("Authorization") == f"Bearer {TOKEN}":
                self._send(200, {"status": "ok"})
            else:
                self._send(401, {"error": {"code": "invalid_token", "message": "bad token"}})
            return
        if self.path == "/garbage":
            self._send(200, None)
            self.wfile.write(b"not json")  # body already finished; emulate junk
            return
        self._send(404, {"error": {"code": "not_found", "message": "nope"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        self._send(200, {"echo": body})


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()


def test_ping_with_valid_token(server):
    client = BackendClient(server, token=TOKEN)
    assert client.ping() == {"status": "ok"}


def test_health_needs_no_auth(server):
    client = BackendClient(server, token="")
    assert client.health()["status"] == "ok"


def test_invalid_token_raises_backend_error(server):
    client = BackendClient(server, token="wrong")
    with pytest.raises(BackendError) as exc:
        client.ping()
    assert exc.value.code == "invalid_token"
    assert exc.value.status == 401


def test_post_round_trips_json(server):
    client = BackendClient(server, token=TOKEN)
    assert client.post("/v1/text/echo", {"texts": ["猫"]}) == {"echo": {"texts": ["猫"]}}


def test_unreachable_backend_raises_backend_error():
    # Nothing is listening on this port.
    client = BackendClient("http://127.0.0.1:1", token=TOKEN, timeout=1.0)
    with pytest.raises(BackendError) as exc:
        client.ping()
    assert exc.value.code == "unreachable"


def test_trailing_slash_is_normalized(server):
    client = BackendClient(server + "/", token=TOKEN)
    assert client.ping() == {"status": "ok"}
