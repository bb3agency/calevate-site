"""No log call passes a LogRecord attribute name as an `extra` key.

The stdlib raises KeyError ("Attempt to overwrite 'name' in LogRecord") on such a key, at
the log line, after whatever the request already did, so the client meets a 500 for a
change that was then rolled back. It shipped once: an action's audit summary carried
`name`. A literal key is checked here; a mapping whose keys the caller does not control goes
through `core.logging.safe_extra`.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOTS = ("apps", "packages/shared/src", "scripts")
RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}
LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})


def _offenders() -> list[str]:
    found: list[str] = []
    for root in ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if "node_modules" in path.parts or ".venv" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in LOG_METHODS
                ):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                        continue
                    for key in keyword.value.keys:
                        if isinstance(key, ast.Constant) and key.value in RESERVED:
                            rel = path.relative_to(REPO_ROOT).as_posix()
                            found.append(f"{rel}:{node.lineno} extra key {key.value!r}")
    return found


def test_no_log_call_overwrites_a_log_record_attribute() -> None:
    offenders = _offenders()
    assert not offenders, (
        "these log calls pass a LogRecord attribute as an `extra` key, which raises "
        "KeyError at runtime; rename the key:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_sees_log_calls_at_all() -> None:
    """A walk that found no `extra=` would pass the test above on nothing."""
    seen = 0
    for path in (REPO_ROOT / "apps" / "api" / "compliance").rglob("*.py"):
        seen += path.read_text(encoding="utf-8").count("extra=")
    assert seen > 10
