"""jp-utils Anki add-on: a thin, stdlib-only client for the jp-utils backend.

The heavy lifting (tokenizer, dictionaries, vocab) lives in the backend. This
add-on only reads/writes notes via ``mw.col``, calls the backend over HTTP, and
surfaces a small config UI.

The Anki wiring runs ONLY inside Anki: importing the package's pure modules
(``client``, ``config``, ``ops``) outside Anki - e.g. from unit tests or tooling
- must not require ``aqt``/PyQt6, so the wiring is guarded behind a successful
``aqt`` import. The host integration (Tools menu, Browser action) is attached by
``entry.setup`` once it lands.
"""

try:
    import aqt  # noqa: F401
except ImportError:
    # Not running inside Anki (tests, tooling): wire nothing.
    pass
else:
    from .entry import setup

    setup()
