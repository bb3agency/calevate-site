"""Guardrail: no shipped module imports a `*_test.py` file.

The server image leaves out every `**/*_test.py` (`.dockerignore`), because the runtime runs
no tests. A runtime module named `*_test.py` therefore exists in the working tree, where every
local check imports it, and is missing from the image, where the import fails at start-up.
That shipped once (`engine/forwarding_test.py`, 11 Oct 2026) and crash-looped the workers on
deploy while the whole local gate set was green.
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
