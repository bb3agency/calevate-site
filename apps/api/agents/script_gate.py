"""The script checks on a campaign's or an inbound line's saved script, where the owner meets
them: Save and Keep warn, Put it live and Start refuse (script rebuild DESIGN §3.4).

`script_checks.run` decides what is wrong; this module only reads the holder's script and the
context every path checks it against (`script_heal.holder_lint_context`) and applies the
severity. A Save or a Keep is never refused on a check: the owner's own words are kept, the
findings are what the holder's checks endpoint shows, and Pip repairs what it can
(`script_heal.queue_after_save`). Putting the script on calls is refused while a `block`
check finds something, with the lines named, because those faults are wrong on every call
that hears them.

A test call is not refused: it is how an owner hears what a line does, and it reaches only
them.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_checks
from apps.api.agents.script_heal import HolderKind, holder_lint_context, table_of
from apps.api.agents.script_lint import plain
from apps.api.core.errors import ProblemError

#: The refusal's code, and the launch checklist's rule name for the same refusal.
SCRIPT_NEEDS_FIX: Final = "script_needs_fix"
#: Lines named in a refusal; the checks endpoint lists every one.
_NAMED_IN_REFUSAL: Final = 3


class ScriptCheckOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The registered check (`script_checks.CHECKS`).
    check: str
    #: The line's path in the script JSON, steps by their place in the list
    #: (`stages.2.examples.te-IN.turns.0`, `stages.0.procedure.1.action`).
    path: str
    #: The `id` of the step `path` is in, for an editor that keys steps by id; null for a
    #: place outside the steps (an opening, the whole script).
    stage_id: str | None
    #: Where it is and what to change, in the owner's words ("Step 3: ...").
    message: str
    #: What to change in the line, without the place ("opens with the reaction ...").
    detail: str
    #: The line it is about, as the owner saved it; "" for a place that is not one line.
    #: Named `line`, not `text`: `text` is the transcript field hard rule 5 guards.
    line: str
    #: `block` stops Put it live and Start; `warn` never stops anything.
    severity: Literal["block", "warn"]


class ScriptChecksOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ScriptCheckOut]
    #: Whether Put it live (and Start) would refuse this script now.
    blocks_live: bool


async def _holder(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> tuple[UUID, CallScript | None]:
    row = (
        await session.execute(
            text(f"SELECT agent_id, script FROM {table_of(kind)} WHERE id = :h"),
            {"h": holder_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign" if kind == "campaign" else "Inbound line")
    return UUID(str(row[0])), CallScript.model_validate(row[1]) if row[1] else None


async def holder_findings(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> list[script_checks.Finding]:
    """Every check's findings on the holder's saved script; [] while it has none."""
    agent_id, script = await _holder(session, kind, holder_id)
    if script is None:
        return []
    lint = await holder_lint_context(session, kind, holder_id, agent_id)
    return script_checks.run(script, lint)


def _stage_id(script: CallScript | None, path: str) -> str | None:
    parts = path.split(".")
    if script is None or parts[0] != "stages" or len(parts) < 2 or not parts[1].isdigit():
        return None
    index = int(parts[1])
    return script.stages[index].id if index < len(script.stages) else None


def checks_out(
    findings: list[script_checks.Finding], script: CallScript | None = None
) -> ScriptChecksOut:
    return ScriptChecksOut(
        findings=[
            ScriptCheckOut(
                check=f.check,
                path=f.path,
                stage_id=_stage_id(script, f.path),
                message=plain(f.text),
                detail=f.problem,
                line=f.line,
                severity=f.severity,
            )
            for f in findings
        ],
        blocks_live=bool(script_checks.blocking(findings)),
    )


async def holder_checks(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> ScriptChecksOut:
    """The checks endpoint's answer: every finding on the holder's saved script."""
    agent_id, script = await _holder(session, kind, holder_id)
    if script is None:
        return checks_out([])
    lint = await holder_lint_context(session, kind, holder_id, agent_id)
    return checks_out(script_checks.run(script, lint), script)


def refusal_reason(blocking: list[script_checks.Finding]) -> str:
    """The lines that stop the script going on calls, in the owner's words."""
    named = "; ".join(plain(f.text) for f in blocking[:_NAMED_IN_REFUSAL])
    more = len(blocking) - _NAMED_IN_REFUSAL
    return f"{named}{f' (and {more} more)' if more > 0 else ''}"


async def blocking_findings(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> list[script_checks.Finding]:
    return script_checks.blocking(await holder_findings(session, kind, holder_id))


async def refuse_if_blocked(session: AsyncSession, kind: HolderKind, holder_id: UUID) -> None:
    """Refuse putting the holder's saved script on calls while a `block` check faults it."""
    blocking = await blocking_findings(session, kind, holder_id)
    if not blocking:
        return
    raise ProblemError.business_rule(
        SCRIPT_NEEDS_FIX,
        f"Some lines would go wrong on every call: {refusal_reason(blocking)}",
        remediation="Change those lines, then put it live again. Your saved script is kept.",
    )


__all__ = [
    "SCRIPT_NEEDS_FIX",
    "ScriptCheckOut",
    "ScriptChecksOut",
    "blocking_findings",
    "checks_out",
    "holder_checks",
    "holder_findings",
    "refusal_reason",
    "refuse_if_blocked",
]
