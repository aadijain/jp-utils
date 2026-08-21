"""Static guards on the module boundaries the design leans on.

These parse source rather than importing it, so they cost milliseconds and cannot
be defeated by a module that fails to import. Each one covers a rule that no other
check in the project can see.
"""

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"
ADDON = ROOT / "addon" / "src" / "jp_utils"
SHARED = ROOT / "shared" / "src" / "shared"


def _sources(root: pathlib.Path) -> list[pathlib.Path]:
    """Every .py under root, minus the vendored copy (a build artifact, not source)."""
    return sorted(p for p in root.rglob("*.py") if "_vendor" not in p.parts)


def _imports(path: pathlib.Path) -> set[str]:
    """Absolute module names imported by one file. Relative imports are internal
    by definition, so they are skipped."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _importers(root: pathlib.Path, *prefixes: str) -> list[str]:
    """Files under root importing any of the given top-level modules."""
    hits = []
    for path in _sources(root):
        for name in _imports(path):
            if any(name == p or name.startswith(f"{p}.") for p in prefixes):
                hits.append(f"{path.relative_to(ROOT)} imports {name}")
    return hits


def test_text_and_vocab_never_import_each_other() -> None:
    """The extraction boundary: either module must stay liftable without the other."""
    assert _importers(BACKEND / "text", "app.vocab") == []
    assert _importers(BACKEND / "vocab", "app.text") == []


def test_sudachi_stays_behind_the_tokenizer_adapter() -> None:
    """Swapping the tokenizer must touch one file, not every caller."""
    adapter = BACKEND / "text" / "tokenizer.py"
    leaked = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in _sources(BACKEND)
        if path != adapter
        for name in _imports(path)
        if name.split(".")[0] == "sudachipy"
    ]
    assert leaked == []


def test_addon_imports_only_stdlib_and_anki() -> None:
    """Anki cannot pip install. This also catches `from shared.x import ...`, which
    resolves under the uv workspace so the tests pass, then raises inside Anki
    because nothing puts the vendored copy on sys.path."""
    allowed = sys.stdlib_module_names | {"aqt", "anki", "PyQt6", "jp_utils"}
    leaked = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in _sources(ADDON)
        for name in _imports(path)
        if name.split(".")[0] not in allowed
    ]
    assert leaked == []


def test_shared_imports_only_stdlib() -> None:
    """It is vendored into the stdlib-only add-on, so a dependency here breaks Anki
    rather than the backend, and the backend suite would never notice."""
    leaked = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in _sources(SHARED)
        for name in _imports(path)
        if name.split(".")[0] not in sys.stdlib_module_names | {"shared"}
    ]
    assert leaked == []


def test_backend_never_touches_anki() -> None:
    """All Anki I/O is in-process via the add-on; the backend only speaks HTTP."""
    assert _importers(BACKEND, "anki", "aqt") == []
