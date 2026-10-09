"""Every outcome an action can report has words on the client's screen.

The test button and the run log show `RUN_STATUS_LABELS[status]`; a status with no label
reached the owner as "Result: unreadable_time". The set of statuses is read from the
executors, so a new outcome fails here until it has a label.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIONS = REPO_ROOT / "apps" / "api" / "actions"
LABELS = REPO_ROOT / "apps" / "web" / "src" / "lib" / "api" / "actions.ts"

_EMITTED = re.compile(r'(?:_refused\(\s*|status=)"([a-z_]+)"')


def _emitted() -> set[str]:
    found: set[str] = set()
    for path in ACTIONS.glob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        found |= set(_EMITTED.findall(path.read_text(encoding="utf-8")))
    return found


def _labelled() -> set[str]:
    source = LABELS.read_text(encoding="utf-8")
    block = source.split("export const RUN_STATUS_LABELS", 1)[1].split("};", 1)[0]
    return set(re.findall(r"^\s+([a-z_]+):", block, re.M))


def test_every_action_outcome_has_a_label() -> None:
    missing = sorted(_emitted() - _labelled())
    assert not missing, (
        f"{missing}: an action can report these and RUN_STATUS_LABELS in "
        "apps/web/src/lib/api/actions.ts has no words for them"
    )


def test_the_scan_finds_the_executors_outcomes() -> None:
    assert {"booked", "unreadable_time", "slot_taken"} <= _emitted()
