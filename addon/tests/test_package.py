def test_package_imports_without_anki() -> None:
    # The package's Anki wiring is guarded behind an aqt import, so importing it
    # outside Anki (tests/tooling) must not raise.
    import jp_utils  # noqa: F401
