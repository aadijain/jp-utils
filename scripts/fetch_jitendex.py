"""Download the Jitendex dictionary. Usage: uv run python scripts/fetch_jitendex.py [--force]"""

from _dl import DictKind, main

if __name__ == "__main__":
    main(DictKind.JITENDEX)
