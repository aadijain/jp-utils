# jp-utils backend

A [FastAPI](https://fastapi.tiangolo.com/) service with a single layer:

- a stateless **text** service (`/v1/text/*`) - pure functions over read-only reference data: tokenization, furigana, readings, meanings, frequency, conversions. No user state; reusable by any tool.

The backend never touches Anki's database; all Anki I/O lives in the [add-on](../addon/). Slices share only the [`shared/`](../shared/) contract.

The API is **batch-first**: send many texts in one request and get results aligned to the input. Versioned routes under `/v1` require an `Authorization: Bearer <token>` header. Full interactive schema at `/docs`.

## Text service (`/v1/text/*`)

| Endpoint | What it does |
|---|---|
| `POST /tokenize` | Split Japanese text into words, each with dictionary form, reading, and part of speech (SudachiPy; split mode A/B/C) |
| `POST /space` | Insert spaces at word boundaries |
| `POST /furigana` | Annotate text with per-word readings (curated JmdictFurigana, falling back to reading alignment) |
| `POST /convert` | hiragana/katakana, romaji, and full-width/half-width conversion |
| `POST /meaning` | Dictionary definitions, per-sense (Jitendex); optional reading filter |
| `POST /frequency` | Word frequency ranks (JPDB; lower = more frequent) |
| `POST /normalize` | Deinflect a word to its dictionary form and reading (the canonical surface -> lemma+reading key) |

## Quick start

From this directory:

```bash
uv sync                                          # install dependencies (whole workspace)
export JP_UTILS_API_TOKEN=your-secret-token      # required for /v1 routes

# one-time: download the reference dictionaries and build the lookup cache
uv run python ../scripts/fetch_jitendex.py
uv run python ../scripts/fetch_freq_dict.py
uv run python ../scripts/fetch_jmdict_furigana.py
uv run python -m app.dicts                       # parse the dicts into a SQLite cache

uv run uvicorn app.main:app --reload             # start the dev server
```

Open <http://127.0.0.1:8000/docs> for the API explorer, or <http://127.0.0.1:8000/health> (public, always 200) to see whether the dictionaries and tokenizer loaded.

## Commands

| Command | What it does |
|---|---|
| `uv sync` | Install dependencies |
| `uv run uvicorn app.main:app --reload` | Start the dev server |
| `uv run pytest` | Run the tests |
| `uv run ruff check .` | Lint (ruff config is at the repo root) |
| `uv run ruff format .` | Format |
| `uv run python -m app.dicts [--force]` | Build the dictionary lookup cache |
| `uv run python ../scripts/fetch_jitendex.py [--force]` | Download the Jitendex dictionary |
| `uv run python ../scripts/fetch_freq_dict.py [--force]` | Download the JPDB frequency list |
| `uv run python ../scripts/fetch_jmdict_furigana.py [--force]` | Download JmdictFurigana |

## Dictionary setup

The backend reads three [Yomitan](https://yomitan.wiki)-format dictionaries and parses them once into a read-only SQLite cache (`python -m app.dicts`):

| Dictionary | Provides | Fetch with |
|---|---|---|
| [Jitendex](https://jitendex.org) | meanings | `scripts/fetch_jitendex.py` |
| [JPDB frequency list](https://github.com/MarvNC/jpdb-freq-list) | word frequency | `scripts/fetch_freq_dict.py` |
| [JmdictFurigana](https://github.com/Doublevil/JmdictFurigana) | furigana segmentation | `scripts/fetch_jmdict_furigana.py` |

Each dictionary is located in this order:

1. its environment variable (`JITENDEX_PATH`, `JPDB_FREQ_PATH`, `JMDICT_FURIGANA_PATH`)
2. `backend/data/dict/<file>`
3. the shared default `~/.local/share/japanese-dicts/` (`%LOCALAPPDATA%\japanese-dicts\` on Windows)

The shared default lets a single copy of each dictionary be reused across tools. Missing dictionaries aren't fatal: the affected features are unavailable and `/health` reports the service as degraded until you fetch them and rebuild the cache. A cache built by an older version of the code is ignored the same way; rebuild it with `python -m app.dicts --force` after upgrading.

## Configuration

Settings come from `JP_UTILS_*` environment variables (or a `backend/.env` file):

| Variable | What it does |
|---|---|
| `JP_UTILS_API_TOKEN` | Bearer token required on every `/v1` route |
| `JP_UTILS_DICT_CACHE_PATH` | Override the dictionary cache location |
| `JITENDEX_PATH` / `JPDB_FREQ_PATH` / `JMDICT_FURIGANA_PATH` | Override individual dictionary file locations |

## Layout

```
app/
  main.py          create_app + lifespan (builds tokenizer, dict cache, vocab store)
  config.py        pydantic-settings (JP_UTILS_* env)
  auth.py          bearer-token dependency
  errors.py        APIError + exception handlers (one error shape)
  api/
    health.py      public /health
    v1/            text.py, vocab.py, mining.py routers (bearer-guarded)
  text/            tokenizer, furigana, convert, meaning, frequency, normalize, words, audio, spacing
  dicts/           parsers + read-only SQLite cache over the three dictionaries
tests/             pytest suite (FastAPI TestClient)
```
