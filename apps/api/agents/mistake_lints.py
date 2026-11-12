"""PLACEHOLDER for lane L of D-985: which lines of an agent's script cause a call-mistake kind.

Lane L writes the real module (a script check for every kind in `call_mistakes.LESSONS`);
this file implements its contract for the three kinds that already had a script check, so
the healer (`workers/mistake_fix`) can be built and tested against it. It is replaced
wholesale at merge.

A finding is a `script_lint` finding: `"<path>: <what is wrong>"`, the path in the script
JSON (`stages.2.instruction`), so `script_proposals.request_proposal(mode="change",
paths=...)` can be asked to change exactly those lines.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from calevate_shared.call_script import CallScript

from apps.api.agents import script_lint
from apps.api.agents.script_lint import LintContext

_CHECKS: Final[dict[str, Callable[[CallScript], list[str]]]] = {
    "opened_again": script_lint.opening_redone_problems,
    "same_opening": script_lint.same_opener_problems,
    "said_again": script_lint.repeated_line_problems,
}

#: The kinds a change to the agent's own script can cause, and so fix.
SCRIPT_FIXABLE_KINDS: Final[frozenset[str]] = frozenset(_CHECKS)


def mistake_findings(script: CallScript, context: LintContext, kind: str) -> list[str]:
    """The findings in `script` that cause `kind` on calls; [] for a kind no line causes."""
    del context
    check = _CHECKS.get(kind)
    if check is None or script.raw_override:
        return []
    return check(script)


__all__ = ["SCRIPT_FIXABLE_KINDS", "mistake_findings"]
