"""Download the Kanjium pitch accents. Usage: uv run python scripts/fetch_pitch_dict.py [--force]"""

from _dl import DictKind, main

if __name__ == "__main__":
    main(DictKind.PITCH)
