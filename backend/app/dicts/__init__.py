"""Reference-dictionary layer.

Parses the three Yomitan/JmdictFurigana source zips into a read-only SQLite
cache (parsed once, never per-request), and exposes lookups through `DictCache`.
The text service reaches reference data only through this package (the
dictionary-provider seam); no zip/format types leak out. Path resolution uses
stable env-var names, filenames, and a shared default location so a single copy
of each dictionary can be reused across tools.
"""

from app.dicts.cache import DictCache, build_cache
from app.dicts.paths import DICT_FILENAMES, DictKind, resolve_dict_path

__all__ = [
    "DICT_FILENAMES",
    "DictCache",
    "DictKind",
    "build_cache",
    "resolve_dict_path",
]
