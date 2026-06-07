"""HTTP client for the jp-utils backend (stdlib-only: ``urllib``).

The add-on's single network seam. It pushes all real work to the backend and
just marshals JSON over HTTP with the configured base URL + bearer token. Used by
the settings dialog (connectivity test) and the pipeline operations.

Every failure - unreachable backend, auth rejection, malformed body - is raised
as a :class:`BackendError` carrying the backend's error ``code`` when one was
returned (the standard ``shared.errors.ErrorResponse`` shape), so callers parse a
single failure type.
"""

import json
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 10.0


class BackendError(Exception):
    """A backend call failed.

    ``code`` is the backend's error code when the response carried one, else a
    transport-level label (``unreachable`` / ``bad_response`` / ``http_error``).
    ``status`` is the HTTP status when there was a response.
    """

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.status = status


class BackendClient:
    """Thin JSON-over-HTTP client. Construct per call with the current config."""

    def __init__(self, base_url: str, token: str = "", timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ── Calls ────────────────────────────────────────────────────────────────
    def ping(self) -> dict:
        """Authenticated connectivity probe (``GET /v1/ping``).

        Verifies the configured URL *and* token together (unlike ``/health``).
        """
        return self.request("GET", "/v1/ping")

    def health(self) -> dict:
        """Public health probe (``GET /health``); reports dict/tokenizer state."""
        return self.request("GET", "/health", auth=False)

    def post(self, path: str, body: dict) -> dict:
        """POST a JSON body to a backend path and return the parsed response."""
        return self.request("POST", path, body=body)

    # ── Core ─────────────────────────────────────────────────────────────────
    def request(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
        url = self.base_url + path
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise BackendError(
                "unreachable", f"Could not reach the backend at {self.base_url}: {reason}"
            ) from exc
        return self._parse(raw)

    def _parse(self, raw: bytes) -> dict:
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BackendError("bad_response", f"Backend returned malformed JSON: {exc}") from exc

    def _http_error(self, exc: urllib.error.HTTPError) -> BackendError:
        """Map an HTTP error onto the standard backend error contract."""
        code, message = "http_error", exc.reason or "HTTP error"
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            err = payload.get("error") or {}
            code = err.get("code") or code
            message = err.get("message") or message
        except (ValueError, UnicodeDecodeError, AttributeError, OSError):
            pass  # non-JSON / empty error body: keep the status-line reason
        return BackendError(code, message, status=exc.code)
