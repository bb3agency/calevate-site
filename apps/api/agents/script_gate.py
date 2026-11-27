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
from apps.api.agents.prompt_size import SCRIPT_TARGET_CHARS, PromptSize
from apps.api.agents.script_heal import HolderKind, holder_lint_context, table_of
from apps.api.agents.script_lint import plain
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

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


class ScriptSizeOut(BaseModel):
    """How long the saved script is against its target and its box, in characters, as a
    publish would send it (`script_builder.job_size`). The target never refuses anything."""

    model_config = ConfigDict(extra="forbid")

    #: The script as the engine receives it (`PromptSize.script_chars`).
    script_chars: int
    #: `prompt_size.SCRIPT_TARGET_CHARS`.
    target_chars: int
    over_target: bool
    #: The longest the script can be beside the platform's layers now; null where the
    #: engine has no box. Over it, Put it live and Start refuse (`PromptTooLongError`).
    limit_chars: int | None
    fits: bool


class ScriptChecksOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ScriptCheckOut]
    #: Whether Put it live (and Start) would refuse this script now.
    blocks_live: bool
    #: Null while there is no script, or when it cannot be measured now.
    size: ScriptSizeOut | None = None


async def _holder(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> tuple[UUID, UUID, CallScript | None]:
    """The holder's tenant, agent and saved script."""
    row = (
        await session.execute(
            text(f"SELECT tenant_id, agent_id, script FROM {table_of(kind)} WHERE id = :h"),
            {"h": holder_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign" if kind == "campaign" else "Inbound line")
    script = CallScript.model_validate(row[2]) if row[2] else None
    return UUID(str(row[0])), UUID(str(row[1])), script


async def holder_findings(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> list[script_checks.Finding]:
    """Every check's findings on the holder's saved script; [] while it has none."""
    _tenant_id, agent_id, script = await _holder(session, kind, holder_id)
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


def size_out(size: PromptSize | None) -> ScriptSizeOut | None:
    if size is None:
        return None
    return ScriptSizeOut(
        script_chars=size.script_chars,
        target_chars=SCRIPT_TARGET_CHARS,
        over_target=size.over_target,
        limit_chars=size.script_limit,
        fits=size.fits,
    )


def checks_out(
    findings: list[script_checks.Finding],
    script: CallScript | None = None,
    size: PromptSize | None = None,
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
        size=size_out(size),
    )


async def _measured(
    session: AsyncSession, kind: HolderKind, holder_id: UUID, tenant_id: UUID
) -> PromptSize | None:
    """The saved script measured as Put it live or Start would send it. A config the publish
    path refuses for another reason leaves the size unknown: the findings are still worth
    showing, and that refusal is Put it live's to state, in its own words."""
    from apps.api.agents.script_builder import job_size

    try:
        return await job_size(session, kind=kind, tenant_id=tenant_id, job_id=holder_id)
    except ProblemError as exc:
        log.info("script_size_unmeasured", extra={"holder_id": str(holder_id), "code": exc.code})
        return None


async def holder_checks(
    session: AsyncSession, kind: HolderKind, holder_id: UUID
) -> ScriptChecksOut:
    """The checks endpoint's answer: every finding on the holder's saved script, and its
    size against the target and the box."""
    tenant_id, agent_id, script = await _holder(session, kind, holder_id)
    if script is None:
        return checks_out([])
    lint = await holder_lint_context(session, kind, holder_id, agent_id)
    size = await _measured(session, kind, holder_id, tenant_id)
    return checks_out(script_checks.run(script, lint), script, size)


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
    "ScriptSizeOut",
    "blocking_findings",
    "checks_out",
    "holder_checks",
    "holder_findings",
    "refusal_reason",
    "refuse_if_blocked",
    "size_out",
]
