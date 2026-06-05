"""Reference-dictionary file locations.

Uses stable env-var names, filenames, and a shared default location so a single
copy of each downloaded zip can be reused across tools.

Resolution order for *reading* a dict (`resolve_dict_path`):
    1. the per-dict env var (e.g. JITENDEX_PATH)
    2. project-local backend/data/dict/<file>
    3. shared default ~/.local/share/japanese-dicts/<file>
       (Windows: %LOCALAPPDATA%\\japanese-dicts\\<file>)

Downloads (`download_target`) go to the env var if set, else the shared default
(skipping the project-local fallback).
"""

import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DictKind(StrEnum):
    JITENDEX = "jitendex"
    JPDB_FREQ = "jpdb_freq"
    JMDICT_FURIGANA = "jmdict_furigana"


@dataclass(frozen=True)
class DictSpec:
    kind: DictKind
    env_var: str
    filename: str


DICT_SPECS: dict[DictKind, DictSpec] = {
    DictKind.JITENDEX: DictSpec(DictKind.JITENDEX, "JITENDEX_PATH", "jitendex.zip"),
    DictKind.JPDB_FREQ: DictSpec(DictKind.JPDB_FREQ, "JPDB_FREQ_PATH", "jpdb-freq-list.zip"),
    DictKind.JMDICT_FURIGANA: DictSpec(
        DictKind.JMDICT_FURIGANA, "JMDICT_FURIGANA_PATH", "jmdict-furigana.json.zip"
    ),
}

DICT_FILENAMES: dict[DictKind, str] = {k: s.filename for k, s in DICT_SPECS.items()}

# Project-local fallback, relative to the repo root (two levels up from this file:
# backend/app/dicts/paths.py -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_DICT_DIR = _REPO_ROOT / "backend" / "data" / "dict"


def shared_dict_dir() -> Path:
    """Platform-aware shared dictionary directory."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "japanese-dicts"
    return Path.home() / ".local" / "share" / "japanese-dicts"


def _env_path(spec: DictSpec) -> Path | None:
    value = os.environ.get(spec.env_var)
    return Path(value) if value else None


def resolve_dict_path(kind: DictKind) -> Path | None:
    """Return the first existing path for `kind`, or None if none is present."""
    spec = DICT_SPECS[kind]
    candidates = [
        _env_path(spec),
        _LOCAL_DICT_DIR / spec.filename,
        shared_dict_dir() / spec.filename,
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return path
    return None


def download_target(kind: DictKind) -> Path:
    """Where a fetch script should write `kind`: env var if set, else shared default."""
    spec = DICT_SPECS[kind]
    return _env_path(spec) or (shared_dict_dir() / spec.filename)


def default_cache_path() -> Path:
    """Default location for the built read-only SQLite cache."""
    return _REPO_ROOT / "backend" / "data" / "cache" / "dict-cache.db"
