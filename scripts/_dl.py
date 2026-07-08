"""Shared download helper for the dict fetch scripts.

Stdlib-only (urllib). Reuses the backend's path resolution so downloads land
where the backend reads them (env var if set, else the shared dict dir). Run via
`uv run python scripts/fetch_*.py` so the workspace venv (with `app` installed)
is on the path.
"""

import sys
import urllib.request

from app.dicts.paths import DictKind, download_target

# Release URLs.
URLS: dict[DictKind, str] = {
    DictKind.JITENDEX: (
        "https://github.com/stephenmk/stephenmk.github.io/releases/latest/download/"
        "jitendex-yomitan.zip"
    ),
    DictKind.JPDB_FREQ: (
        "https://github.com/MarvNC/jpdb-freq-list/releases/download/2022-05-09/"
        "Freq.JPDB_2022-05-10T03_27_02.930Z.zip"
    ),
    DictKind.JMDICT_FURIGANA: (
        "https://github.com/Doublevil/JmdictFurigana/releases/latest/download/"
        "JmdictFurigana.json.zip"
    ),
    DictKind.PITCH: (
        "https://github.com/toasted-nutbread/yomichan-pitch-accent-dictionary/releases/"
        "download/1.0.0/kanjium_pitch_accents.zip"
    ),
}


def _report(label: str, blocks: int, block_size: int, total: int) -> None:
    if total <= 0:
        return
    pct = min(100, int(blocks * block_size * 100 / total))
    sys.stdout.write(f"\r  {label}: {pct}% ({total / 1e6:.1f} MB)")
    sys.stdout.flush()


def fetch(kind: DictKind, *, force: bool) -> int:
    label = kind.value
    dest = download_target(kind)

    if dest.is_file() and not force:
        print(f"[{label}] already exists: {dest}")
        print("  Pass --force to re-download.")
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = URLS[kind]
    print(f"[{label}] downloading -> {dest}")
    try:
        urllib.request.urlretrieve(url, dest, reporthook=lambda b, bs, t: _report(label, b, bs, t))
    except OSError as exc:
        sys.stdout.write("\n")
        print(f"[{label}] download failed: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write("\n")
    print(f"[{label}] saved. Run `python -m app.dicts.cache --force` to rebuild the cache.")
    return 0


def run(kind: DictKind) -> int:
    force = "--force" in sys.argv[1:]
    return fetch(kind, force=force)


def main(kind: DictKind) -> None:
    raise SystemExit(run(kind))
