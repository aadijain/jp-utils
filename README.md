# jp-utils

Japanese learning tooling in two halves: a reusable **backend service** that does the heavy text processing (tokenization, furigana, readings, meanings, frequency) and keeps a personal vocabulary store, and a thin **Anki add-on** that uses it to enrich cards and reorder decks. The backend speaks plain HTTP, so other tools can build on it too.

---

## Architecture

Three parts that share only an HTTP contract. The backend and add-on run as separate processes and can live on different machines:

| Component | What it is | Detail |
|---|---|---|
| **[`backend/`](backend/)** | FastAPI service: a stateless **text** service, a stateful **vocab** store (your known-words knowledge base), and a **mining** layer that composes the two. | [backend/README.md](backend/README.md) |
| **[`shared/`](shared/)** | The request/response models that define the contract between the two. | [shared/README.md](shared/README.md) |

The repo is a single [uv](https://docs.astral.sh/uv/) workspace (one `.venv` and `uv.lock` at the root; the three directories above are the members).

## What it does

The **backend** exposes a batch-first, bearer-authenticated HTTP API: tokenization, word spacing, furigana, kana/romaji conversion, dictionary meanings, frequency ranks, deinflection, content-word extraction, and pronunciation audio. See [backend/README.md](backend/README.md) for the full endpoint list.

## Quick start

**Backend** (`cd backend`):

```bash
uv sync                                          # install dependencies
export JP_UTILS_API_TOKEN=your-secret-token      # required for /v1 routes

# one-time: download the reference dictionaries and build the lookup cache
uv run python ../scripts/fetch_jitendex.py
uv run python ../scripts/fetch_freq_dict.py
uv run python ../scripts/fetch_jmdict_furigana.py
uv run python -m app.dicts                       # parse the dicts into the cache

uv run uvicorn app.main:app --reload             # start the dev server
```

Then open <http://127.0.0.1:8000/docs> for the API explorer or <http://127.0.0.1:8000/health> to check the dictionaries loaded. Full detail (endpoints, dictionary resolution, env vars): [backend/README.md](backend/README.md).

## Disclaimers

- *Personal hobby project, may not be actively maintained.*
- *Built for a single-user setup; the backend and add-on run as separate services.*
- *MIT licensed - see [LICENSE](LICENSE).*
