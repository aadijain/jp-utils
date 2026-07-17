from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_health_is_public_and_degraded_without_cache(client: TestClient) -> None:
    # The base client fixture runs no lifespan, so no cache is loaded.
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "jp-utils"
    assert body["status"] == "degraded"
    assert body["cache_built"] is False
    assert body["tokenizer_ready"] is False
    assert body["dicts"] == []


def test_health_ok_with_built_cache(
    built_cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The lifespan calls get_settings() directly, so drive it via env (not a
    # dependency override) and reset the settings cache around the test. Every
    # stateful path is pointed at tmp so the run never touches real data files.
    monkeypatch.setenv("JP_UTILS_DICT_CACHE_PATH", str(built_cache))
    monkeypatch.setenv("JP_UTILS_VOCAB_DB_PATH", str(tmp_path / "vocab.db"))
    monkeypatch.setenv("JP_UTILS_TOKENIZATION_CACHE_PATH", str(tmp_path / "tok.db"))
    monkeypatch.setenv("JP_UTILS_TRANSLATION_DB_PATH", str(tmp_path / "queue.db"))
    get_settings.cache_clear()
    app = create_app()

    # `with` runs the lifespan, which opens the cache onto app.state.
    with TestClient(app) as client:
        resp = client.get("/health")

    get_settings.cache_clear()

    assert resp.status_code == 200
    body = resp.json()
    # `with` runs the lifespan, which also builds the tokenizer.
    assert body["status"] == "ok"
    assert body["cache_built"] is True
    assert body["tokenizer_ready"] is True
    assert {d["name"] for d in body["dicts"]} == {
        "meanings",
        "frequencies",
        "furigana",
        "pitches",
    }
    assert all(d["loaded"] for d in body["dicts"])
