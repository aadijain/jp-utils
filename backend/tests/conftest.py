import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dicts import build_cache
from app.main import create_app

TEST_TOKEN = "test-token"


# ── Synthetic reference dictionaries ─────────────────────────────────────────
# Tiny zips matching the real formats, so dict tests don't depend on the large
# downloaded dictionaries.

_JITENDEX_ROWS = [
    # 食べる: structured content with a sense-group (shared POS) holding two senses;
    # sense 1 carries an example sentence (ruby in the Japanese line is stripped).
    [
        "食べる",
        "たべる",
        "",
        "",
        200,
        [
            {
                "type": "structured-content",
                "content": {
                    "tag": "div",
                    "data": {"content": "sense-group"},
                    "content": [
                        {
                            "tag": "span",
                            "data": {"content": "part-of-speech-info"},
                            "content": "1-dan",
                        },
                        {
                            "tag": "span",
                            "data": {"content": "part-of-speech-info"},
                            "content": "transitive",
                        },
                        {
                            "tag": "div",
                            "data": {"content": "sense"},
                            "content": [
                                {
                                    "tag": "ul",
                                    "data": {"content": "glossary"},
                                    "content": {"tag": "li", "content": "to eat"},
                                },
                                {
                                    "tag": "div",
                                    "data": {"content": "extra-info"},
                                    "content": {
                                        "tag": "div",
                                        "data": {"content": "example-sentence"},
                                        "content": [
                                            {
                                                "tag": "div",
                                                "data": {"content": "example-sentence-a"},
                                                "content": {
                                                    "tag": "span",
                                                    "content": [
                                                        {
                                                            "tag": "ruby",
                                                            "content": [
                                                                "寿司",
                                                                {"tag": "rt", "content": "すし"},
                                                            ],
                                                        },
                                                        "を",
                                                        {
                                                            "tag": "span",
                                                            "data": {"content": "example-keyword"},
                                                            "content": [
                                                                {
                                                                    "tag": "ruby",
                                                                    "content": [
                                                                        "食",
                                                                        {
                                                                            "tag": "rt",
                                                                            "content": "た",
                                                                        },
                                                                    ],
                                                                },
                                                                "べる",
                                                            ],
                                                        },
                                                    ],
                                                },
                                            },
                                            {
                                                "tag": "div",
                                                "data": {"content": "example-sentence-b"},
                                                "content": "to eat sushi",
                                            },
                                        ],
                                    },
                                },
                            ],
                        },
                        {
                            "tag": "div",
                            "data": {"content": "sense"},
                            "content": {
                                "tag": "ul",
                                "data": {"content": "glossary"},
                                "content": [
                                    {"tag": "li", "content": "to live on"},
                                    {"tag": "li", "content": "to subsist"},
                                ],
                            },
                        },
                    ],
                },
            }
        ],
        1358280,
        "jlpt-n5",
    ],
    # 水: plain-string glossary, sole entry at score 0 -> kept (no >=1 alternate).
    ["水", "みず", "", "", 0, ["water"], 1565440, ""],
    # 人: score filtering across one lemma's readings - ひと (200) kept; じん (0)
    # dropped because a >=MIN_SCORE reading exists; にん (-1) always dropped.
    ["人", "ひと", "", "", 200, ["person"], 1101000, ""],
    ["人", "じん", "", "", 0, ["-ian; -er (nationality, origin)"], 1101001, ""],
    ["人", "にん", "", "", -1, ["counter for people"], 1101002, ""],
]

_JPDB_ROWS = [
    # 水 is a homograph: each reading keeps its own rank (per-(term, reading) key).
    ["水", "freq", {"reading": "みず", "frequency": {"value": 500, "displayValue": "500"}}],
    ["水", "freq", {"reading": "すい", "frequency": {"value": 800}}],
    # 水/みず also has a kana-spelling rank (㋕); the kanji-form 500 is preferred.
    ["水", "freq", {"reading": "みず", "frequency": {"value": 2100, "displayValue": "2100㋕"}}],
    ["みず", "freq", {"value": 1500, "displayValue": "1500㋕"}],  # kana form
]

_PITCH_ROWS = [
    # 水/みず: single heiban accent; reading given in katakana to exercise kata->hira.
    ["水", "pitch", {"reading": "ミズ", "pitches": [{"position": 0}]}],
    # 人 is a homograph: ひと carries two accepted accents, にん a different one.
    ["人", "pitch", {"reading": "ひと", "pitches": [{"position": 0}, {"position": 2}]}],
    ["人", "pitch", {"reading": "にん", "pitches": [{"position": 1}]}],
    # A non-pitch meta row in the same bank must be ignored.
    ["水", "freq", {"value": 500}],
]

_FURIGANA_ROWS = [
    {
        "text": "食べる",
        "reading": "たべる",
        "furigana": [{"ruby": "食", "rt": "た"}, {"ruby": "べる"}],
    },
    {"text": "水", "reading": "みず", "furigana": [{"ruby": "水", "rt": "みず"}]},
    {
        "text": "日本語",
        "reading": "にほんご",
        "furigana": [{"ruby": "日本", "rt": "にほん"}, {"ruby": "語", "rt": "ご"}],
    },
]


def _write_zip(path: Path, name: str, data: bytes) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name, data)


@pytest.fixture
def synthetic_dicts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write tiny jitendex/JPDB/furigana zips and point the env vars at them."""
    jitendex = tmp_path / "jitendex.zip"
    _write_zip(jitendex, "term_bank_1.json", json.dumps(_JITENDEX_ROWS).encode("utf-8"))

    jpdb = tmp_path / "jpdb-freq-list.zip"
    _write_zip(jpdb, "term_meta_bank_1.json", json.dumps(_JPDB_ROWS).encode("utf-8"))

    furigana = tmp_path / "jmdict-furigana.json.zip"
    body = "﻿" + json.dumps(_FURIGANA_ROWS)  # leading BOM, like the real file
    _write_zip(furigana, "JmdictFurigana.json", body.encode("utf-8"))

    pitch = tmp_path / "kanjium-pitch-accents.zip"
    _write_zip(pitch, "term_meta_bank_1.json", json.dumps(_PITCH_ROWS).encode("utf-8"))

    monkeypatch.setenv("JITENDEX_PATH", str(jitendex))
    monkeypatch.setenv("JPDB_FREQ_PATH", str(jpdb))
    monkeypatch.setenv("JMDICT_FURIGANA_PATH", str(furigana))
    monkeypatch.setenv("KANJIUM_PITCH_PATH", str(pitch))
    return tmp_path


@pytest.fixture
def built_cache(synthetic_dicts: Path, tmp_path: Path) -> Path:
    """Build a cache from the synthetic dicts and return its path."""
    cache_path = tmp_path / "dict-cache.db"
    build_cache(cache_path, force=True)
    return cache_path


@pytest.fixture
def settings() -> Settings:
    return Settings(api_token=TEST_TOKEN)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    # Let the catch-all exception handler run instead of re-raising in the test.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(scope="session")
def tokenizer():
    """One real SudachiPy tokenizer, reused across tests (dict load is slow)."""
    from app.text.tokenizer import Tokenizer

    return Tokenizer()


@pytest.fixture
def text_client(settings: Settings, tokenizer) -> TestClient:
    """Client with the tokenizer injected on app.state (no lifespan needed)."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.tokenizer = tokenizer
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def vocab_store(tmp_path: Path):
    """A fresh vocab store backed by a temp db."""
    from app.vocab import VocabStore

    store = VocabStore.open(tmp_path / "vocab.db")
    yield store
    store.close()


@pytest.fixture
def vocab_client(settings: Settings, vocab_store) -> TestClient:
    """Client with the vocab store injected on app.state (no lifespan needed)."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.vocab_store = vocab_store
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def text_client_with_dicts(settings: Settings, tokenizer, built_cache) -> TestClient:
    """Client with both the tokenizer and the (synthetic) dict cache on app.state."""
    from app.dicts import DictCache

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.tokenizer = tokenizer
    app.state.dict_cache = DictCache.open(built_cache)
    return TestClient(app, raise_server_exceptions=False)
