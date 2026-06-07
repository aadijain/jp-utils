"""Anki-facing UI for the add-on (PyQt6 dialog, runner, Browser action).

Everything here imports ``aqt``/Qt and so loads only inside Anki; the pure logic
(``client``, ``config``, ``ops``) it builds on is tested separately.
"""
