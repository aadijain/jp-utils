# jp-utils shared contract

The request/response models that define the HTTP contract between the [backend](../backend/) and the [add-on](../addon/). This package *is* the contract: if both sides agree on these types, they interoperate.

## Why plain dataclasses

The models are **plain stdlib `dataclasses`** - deliberately not Pydantic. Anki's bundled Python cannot `pip install`, so the add-on must run on the standard library alone. By keeping the contract dependency-free, the same types serve both sides:

- the **backend** imports this package normally (it's a uv workspace member) and FastAPI consumes the dataclasses directly;
- the **add-on** gets a *copy* of this package vendored into its `.ankiaddon` zip at build time (`addon/build.py` -> `jp_utils/_vendor/shared`).

No third-party imports may appear here. That constraint is what lets one definition of the contract live in one place.

## Modules

| Module | Contract for |
|---|---|
| `text.py` | tokenize, space, furigana, convert, meaning, frequency, normalize, content-words, audio (`/v1/text/*`) |
| `vocab.py` | record words, filter-by-status, status, export; the `VocabWord` / `WordStatus` / `VocabAction` types (`/v1/vocab/*`) |
| `mining.py` | n+1 sort: `MiningSentence`, `SentenceScore`, `Nplus` (`/v1/mining/*`) |
| `health.py` | `HealthResponse` / `DictStatus` for the public `/health` endpoint |
| `errors.py` | `ErrorResponse` / `ErrorBody` - the one error shape every failure is serialized into |

Most request models are batch-shaped (a list of inputs) and the matching response carries results aligned to that input order.

## Usage

```python
from shared.text import TokenizeRequest, TokenizeResponse
from shared.vocab import VocabWord, FilterByStatusRequest
```

The package layout is `src/shared/` (a src-layout hatchling package). The backend depends on it via `[tool.uv.sources] shared = { workspace = true }`; the add-on never declares it as a dependency - it is vendored at build time instead.
