"""Download JmdictFurigana. Usage: uv run python scripts/fetch_jmdict_furigana.py [--force]"""

from _dl import DictKind, main

if __name__ == "__main__":
    main(DictKind.JMDICT_FURIGANA)
