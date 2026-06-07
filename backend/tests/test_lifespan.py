from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cache import TokenizationCache
from app.config import Settings
from app.main import create_app


def test_lifespan_opens_tokenization_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        api_token="t",
        dict_cache_path=str(tmp_path / "dict.db"),
        vocab_db_path=str(tmp_path / "vocab.db"),
        tokenization_cache_path=str(tmp_path / "tok.db"),
    )
    # The lifespan reads settings directly (not via the route dependency), so patch
    # the call site to keep it off the real default data paths.
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:  # entering the context runs the lifespan
        assert isinstance(client.app.state.tokenization_cache, TokenizationCache)
    assert (tmp_path / "tok.db").exists()
