"""Guardrail: nothing the image needs is named `*_test.py`.

The server image leaves out every `**/*_test.py` (`.dockerignore`), because the runtime runs
no tests. A runtime module named `*_test.py` therefore exists in the working tree, where every
local check imports it, and is missing from the image, where the import fails at start-up.
That shipped once (`engine/forwarding_test.py`, 11 Oct 2026) and crash-looped the workers on
deploy while the whole local gate set was green. A migration file is loaded by alembic from
the image too: `b9e4c2d7a316_pip_prepares_a_call_test.py` broke the revision chain on the
19 Oct 2026 deploy (`KeyError: 'b9e4c2d7a316'`) the same way.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOTS = (_ROOT / "apps", _ROOT / "packages" / "shared" / "src")


def _dotted(path: Path) -> str:
    base = _ROOT / "packages" / "shared" / "src" if "packages" in path.parts else _ROOT
    return ".".join(path.relative_to(base).with_suffix("").parts)


def _python_files() -> list[Path]:
    return [
        p for root in _SOURCE_ROOTS for p in root.rglob("*.py") if "node_modules" not in p.parts
    ]


def test_no_runtime_module_imports_a_file_the_image_excludes() -> None:
    files = _python_files()
    excluded = {_dotted(p) for p in files if p.name.endswith("_test.py")}
    offenders: list[str] = []
    for path in files:
        if path.name.endswith("_test.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            hit = next((n for n in names if n in excluded), None)
            if hit:
                offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno} imports {hit}")
    assert not offenders, (
        "These shipped modules import a *_test.py file, which .dockerignore leaves out of the "
        "image, so the import fails in production. Rename the imported module:\n"
        + "\n".join(offenders)
    )


def test_no_migration_file_is_named_like_a_test() -> None:
    named_like_tests = sorted(
        p.name for p in (_ROOT / "alembic" / "versions").glob("*.py") if p.name.endswith("_test.py")
    )
    assert not named_like_tests, (
        "These migrations end in `_test.py`, which .dockerignore leaves out of the image, so "
        "alembic in production cannot find them and every later revision fails. Rename the "
        "file (the revision id inside it is what alembic reads):\n" + "\n".join(named_like_tests)
    )
