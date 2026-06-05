"""Download the JPDB frequency list. Usage: uv run python scripts/fetch_freq_dict.py [--force]"""

from _dl import DictKind, main

if __name__ == "__main__":
    main(DictKind.JPDB_FREQ)
