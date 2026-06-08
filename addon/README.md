# jp-utils Anki add-on

A thin, in-process Anki add-on (PyQt6) that enriches cards and reorders decks by calling the [jp-utils backend](../backend/) over HTTP. It does only three things: in-Anki UX (menus, dialogs, progress), reading and writing notes via `mw.col`, and HTTP calls to the backend. All the language processing lives in the backend.

The runtime is **stdlib-only** - Anki's bundled Python cannot `pip install`, so the [`shared/`](../shared/) contract package is vendored into the `.ankiaddon` zip at build time.

## Install

The add-on is a self-contained `.ankiaddon` zip. Build it from the repo root:

```bash
python addon/build.py                       # -> addon/dist/jp-utils.ankiaddon
python addon/build.py --install <addons21>  # dev: also drop an unzipped copy into a
                                            # local Anki addons21 folder
```

The build script is stdlib-only and runs with bare `python`. Install the built `addon/dist/jp-utils.ankiaddon` in Anki via **Tools -> Add-ons -> Install from file…**, then restart Anki.

## Concepts

**Aliases** are logical field names (`word`, `sentence`, `word-reading`, `word-furigana`, `sentence-furigana`, `definition`, `frequency`, `word-audio`, `rank`). You map each alias to a real field on each of your note types once; operations refer to aliases, so the same pipeline works across note types with different field names.

**Operations** are the units of work. Each reads one or more input aliases and either writes an output field, reorders new cards, or generates new notes.

**Pipelines** are an ordered list of operations bound to a **(deck, note type)** pair. A pipeline runs its operations against the matching notes, manually or automatically.

## Operations

| Operation | Label | Reads | Writes / effect |
|---|---|---|---|
| `word-reading` | Fetch word reading | `word` | `word-reading` |
| `word-furigana` | Add word furigana | `word` | `word-furigana` |
| `sentence-furigana` | Add sentence furigana | `sentence` | `sentence-furigana` (HTML-aware) |
| `word-definition` | Fetch definition | `word` | `definition` (sense-aware) |
| `frequency` | Fetch frequency rank | `word` | `frequency` |
| `word-audio` | Fetch word audio | `word`, `word-reading` | `word-audio` (attaches media, writes `[sound:…]`) |
| `nplus1-sequence` | Assign n+1 sequence | `sentence` | `rank` (n+1 order over the whole batch) |
| `int-sort` | Sort by rank | `rank` (configurable field) | reorders the deck's new cards |
| `generate-vocab` | Generate vocab cards | `sentence` | creates new vocab notes for words new to you |

Field-writing ops are idempotent (a value is written only when it differs); most accept an `only_if_empty` option. `int-sort` and `generate-vocab` operate over the whole target deck, not just a selected subset.

## Configuration

Configure from **Tools -> jp-utils Settings…**, which has three tabs:

- **Backend** - the `server_url` and `token` of your running backend (**Test connection** verifies both).
- **Field mappings** - per note-type alias maps: bind each logical alias to the actual field on that note type. Seeded for the **Lapis** note type; remap or add note types here.
- **Pipelines** - a list of pipelines plus an editor. Each pipeline picks a **(deck, note type)**, an **Enabled** toggle, optional **auto-run triggers** (e.g. run on Anki start), and an ordered list of operation steps with per-step options. Invalid pipelines (unset deck/note type, unmapped aliases, duplicate targets) are flagged with a `⚠`.

## Running pipelines

- **Manual** - the Pipelines tab's **Run now** button (runs the pipeline over its deck), or the Browser **Notes -> jp-utils: Run pipeline** action over the selected notes.
- **Automatic** - a pipeline that opts into the **start** trigger runs silently when Anki starts.

## The mining loop

The operations compose into a single-user study loop:

1. Mine sentence cards from jp media into a mining deck.
2. `nplus1-sequence` + `int-sort` auto-order the new cards so each introduces as few new words as possible.
3. `sentence-furigana` (and friends) auto-enrich the mined cards.
4. `generate-vocab` auto-creates vocab notes in a Word deck for the sentence's words that are new to you (checked against the backend vocab store).
5. The word enrichment ops (reading, definition, frequency, audio) enrich each new vocab card.
6. `int-sort` orders the Word deck ascending by frequency rank.

Each new vocab card records an `encountered` event in the vocab store, so it is never regenerated.

## Development

```bash
cd addon && uv run pytest   # add-on tests (client over a real http.server, config over a fake mw)
```

The UI and entry modules import `aqt`/PyQt6 and are exercised inside Anki, not unit-tested. Linting is via the repo-root ruff config.

## Layout

```
src/jp_utils/
  __init__.py        guards all Anki wiring behind a successful aqt import
  entry.py           setup(): Tools menu, Browser hook, auto-run lifecycle hooks
  client.py          BackendClient - the only network seam (urllib)
  config.py          AddonConfig: aliases, note-type field maps, pipelines
  generation.py      pure helpers for vocab-card generation (no aqt)
  ops/               the operations (see registry.py for the assembled list)
  ui/                config_dialog, params_dialog, run (the pipeline runner), auto, browser
  manifest.json / config.json / config.md   add-on packaging
build.py             vendors shared/ and zips the .ankiaddon
tests/               pytest suite
```
