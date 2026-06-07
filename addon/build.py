#!/usr/bin/env python3
"""Build the jp-utils Anki add-on into an installable ``.ankiaddon`` zip.

Anki's bundled Python cannot ``pip install``, so the ``shared/`` contract package
is *vendored* (copied) into the add-on at build time, under
``jp_utils/_vendor/shared`` (gitignored). The zip's root holds the add-on's files
directly (``__init__.py``, ``manifest.json``, …) as Anki expects.

Stdlib-only, so it runs anywhere:

    python addon/build.py                      # -> addon/dist/jp-utils.ankiaddon
    python addon/build.py --install <addons21> # also drop an unzipped copy into a
                                               # local Anki addons folder (dev)
"""

import argparse
import shutil
import zipfile
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent
REPO_ROOT = ADDON_DIR.parent
PKG_DIR = ADDON_DIR / "src" / "jp_utils"
SHARED_PKG = REPO_ROOT / "shared" / "src" / "shared"
VENDOR_DIR = PKG_DIR / "_vendor"
DIST_DIR = ADDON_DIR / "dist"
OUTPUT = DIST_DIR / "jp-utils.ankiaddon"

# Cruft never shipped into the zip / install.
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def vendor_shared() -> None:
    """Copy the stdlib-only ``shared`` package into ``jp_utils/_vendor/shared``."""
    if VENDOR_DIR.exists():
        shutil.rmtree(VENDOR_DIR)
    VENDOR_DIR.mkdir(parents=True)
    (VENDOR_DIR / "__init__.py").write_text(
        '"""Vendored third-party/shared code (copied at build time; do not edit)."""\n',
        encoding="utf-8",
    )
    shutil.copytree(SHARED_PKG, VENDOR_DIR / "shared", ignore=_IGNORE)


def _package_files() -> list[Path]:
    return [
        p
        for p in sorted(PKG_DIR.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
    ]


def build_zip() -> Path:
    """Zip the add-on package (files at the zip root) into the ``.ankiaddon``."""
    DIST_DIR.mkdir(exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in _package_files():
            zf.write(path, path.relative_to(PKG_DIR).as_posix())
    return OUTPUT


def install(addons_dir: Path) -> Path:
    """Drop an unzipped copy into a local Anki ``addons21`` dir (dev convenience)."""
    target = addons_dir / "jp_utils"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(PKG_DIR, target, ignore=_IGNORE)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        type=Path,
        metavar="ADDONS21_DIR",
        help="also copy the built add-on into this Anki addons21 directory",
    )
    args = parser.parse_args()

    vendor_shared()
    output = build_zip()
    size_kb = output.stat().st_size / 1024
    print(f"Built {output.relative_to(REPO_ROOT)} ({size_kb:.1f} KiB)")

    if args.install:
        target = install(args.install)
        print(f"Installed into {target}")


if __name__ == "__main__":
    main()
