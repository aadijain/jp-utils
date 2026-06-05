"""`python -m app.dicts` -> build the read-only dictionary cache."""

from app.dicts.cache import _main

if __name__ == "__main__":
    raise SystemExit(_main())
