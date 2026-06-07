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

**Aliases** are logical field names (`word`, `sentence`). You map each alias to a real field on each of your note types once; operations refer to aliases, so the same pipeline works across note types with different field names.

**Operations** are the units of work. Each reads one or more input aliases and either writes an output field, reorders new cards, or generates new notes.

**Pipelines** are an ordered list of operations bound to a **(deck, note type)** pair. A pipeline runs its operations against the matching notes, manually or automatically.

## Development

```bash
cd addon && uv run pytest   # add-on tests (client over a real http.server, config over a fake mw)
```

The UI and entry modules import `aqt`/PyQt6 and are exercised inside Anki, not unit-tested. Linting is via the repo-root ruff config.

## Layout

```
src/jp_utils/
  __init__.py        guards all Anki wiring behind a successful aqt import
  client.py          BackendClient - the only network seam (urllib)
  config.py          AddonConfig: aliases, note-type field maps, pipelines
  ops/               the operations (see registry.py for the assembled list)
  manifest.json / config.json / config.md   add-on packaging
build.py             vendors shared/ and zips the .ankiaddon
tests/               pytest suite
```
