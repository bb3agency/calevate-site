"""Guardrail: .env.example ⟷ Settings parity, all THREE directions
(ENGINEERING-PRACTICES §2; fail-fast config doctrine, DEV-SETUP §4).

Every key in `.env.example` must be a Settings field, every Settings field must appear
in `.env.example` — and every environment variable the code actually READS must be a
Settings field. That third direction is the one a worker slips through: a job that
calls `os.getenv("SOME_NEW_KEY")` is config that nobody documented, nobody validates at
boot, and that is simply absent in production until someone notices the feature is off.

Run: uv run python -m scripts.check_env_parity
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from calevate_shared.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = ("apps", "packages", "scripts")
EXCLUDED_PARTS = ("__pycache__", "check_env_parity.py")

# Process/infra variables that are not application config: they are set by the runtime,
# the CI provider or the container, and have no business being a Settings field.
INFRA_ENV_KEYS: frozenset[str] = frozenset(
    {
        "CI",
        "PATH",
        "HOME",
        "PORT",
        "PYTHONPATH",
        "TZ",
        "GITHUB_SHA",
        "HOSTNAME",
    }
)

_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=")
_ENV_READERS = ("getenv", "environ")


def example_keys(path: Path) -> tuple[set[str], list[str]]:
    """Keys declared in `.env.example`, plus any declared twice (the second wins
    silently when the file is sourced, so a duplicate is a real trap)."""
    seen: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _KEY_RE.match(line.strip())
        if match:
            seen.append(match.group(1).lower())
    duplicates = sorted({key for key in seen if seen.count(key) > 1})
    return set(seen), duplicates


def _env_reads(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """`os.getenv("X")`, `os.environ["X"]`, `os.environ.get("X")` — the ways config
    gets read without going through Settings."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            receiver = getattr(func, "value", None)
            is_environ_get = (
                name == "get" and isinstance(receiver, ast.Attribute) and receiver.attr == "environ"
            )
            if name == "getenv" or is_environ_get:
                for arg in node.args[:1]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        yield node.lineno, arg.value
        elif isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "environ":
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield node.lineno, key.value


def direct_env_reads(root: Path | None = None) -> dict[str, list[str]]:
    """key -> where it is read. Pure enough to test: point it at any tree."""
    root = root or REPO_ROOT
    found: dict[str, list[str]] = {}
    for directory in SEARCH_DIRS:
        for path in (root / directory).rglob("*.py"):
            if any(part in str(path) for part in EXCLUDED_PARTS):
                continue
            if not any(reader in path.read_text(encoding="utf-8") for reader in _ENV_READERS):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for lineno, key in _env_reads(tree):
                found.setdefault(key, []).append(f"{path.relative_to(root)}:{lineno}")
    return found


def evaluate(
    declared: set[str],
    settings_fields: set[str],
    reads: dict[str, list[str]],
    duplicates: list[str] | None = None,
) -> list[str]:
    failures: list[str] = []
    only_example = sorted(declared - settings_fields)
    only_settings = sorted(settings_fields - declared)
    if only_example:
        failures.append(f"in .env.example but not Settings: {only_example}")
    if only_settings:
        failures.append(f"in Settings but not .env.example: {only_settings}")
    for key in duplicates or []:
        failures.append(f"{key.upper()} is declared twice in .env.example")
    for key, sites in sorted(reads.items()):
        if key in INFRA_ENV_KEYS or key.lower() in settings_fields:
            continue
        failures.append(
            f"{key} is read directly from the environment ({', '.join(sorted(sites))}) "
            "but is not a Settings field — config that never fails fast"
        )
    return failures


def main() -> int:
    declared, duplicates = example_keys(REPO_ROOT / ".env.example")
    settings_fields = set(Settings.model_fields)
    reads = direct_env_reads()

    failures = evaluate(declared, settings_fields, reads, duplicates)
    if failures:
        print("ENV PARITY: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nA new key goes in BOTH .env.example and calevate_shared.config.Settings, "
            "and is read through Settings — never os.getenv (DEV-SETUP §4)."
        )
        return 1
    print(
        f"ENV PARITY: OK ({len(settings_fields)} keys aligned, "
        f"{len(reads)} direct environment reads accounted for)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
