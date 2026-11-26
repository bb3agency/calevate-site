"""Pip repairs the lines of an existing script that the script checks fault (founder, 24 Nov
2026: anything Pip can fix is fixed automatically, never left for the owner or our team).

The script checks run when Pip writes a draft, so a campaign's or inbound line's script
written before a check existed, or by hand, keeps its fault on every call: a step that asks
"is now a good time?" again after the opening, lines that all open with one reaction or end
with one tag, a repeat in brackets, a textbook word. This module names those faults
(`heal_findings`) and queues the repair pass (`workers/script_heal.repair_holder_script`),
which has Pip rewrite exactly the faulted lines (`script_writer.write_script`, `lines`) and saves
the script by compare-and-set, as the owner's Save would, and puts it on the calls.

THREE TRIGGERS. The owner's save of the script (`queue_after_save`, debounced so a burst of
saves is one pass); a call whose review found a mistake the script causes, through the
healer's fix (`workers/mistake_fix`, `queue_now`); and the hourly sweep over every open
script not checked in its current form (`workers/script_heal.sweep_script_heal`). A pass over
a script with no fault asks no model, so all three can be generous.

WHAT A REPAIR NEVER TOUCHES. The openings and their notice records (`mistake_fixes.
PROTECTED_PARTS`: the AI and recording notices are said in them, D-971); the step outcomes,
which their own pass writes (`campaigns/step_outcomes`); any part that is not one line (a
whole step, the list of steps). A line the owner wrote by hand is changed only when a check
faults that line. The one structural edit is code's, never the model's: a way out a step
states only in words ("if they cannot, offer to call back") becomes that step's branch
(`wired_ways_out`), its words kept. The pass and the step-outcomes pass may read one script
at once; each writes by compare-and-set on what it read (a line's `version`, a campaign's
script itself, which has no version), and the one that loses queues itself again rather
than overwrite.

The queue is the shared agent pass (`agents/agent_pass`), so a pass asked for while one waits
or runs is coalesced and a change made mid-pass is never lost.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import agent_pass, script_checks
from apps.api.agents.agent_pass import dead_sql
from apps.api.agents.script_lint import LintContext
from apps.api.agents.script_structure import (
    ways_out_wired,
    without_echo_ways,
    without_judged_asks,
)
from apps.api.campaigns.script_history import REWRITE_RULES
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.errors import ProblemError

#: The ARQ name of the pass (`workers/script_heal`).
JOB: Final = "repair_holder_script"
#: A pass starts this long after the last save that asked for it, so an owner saving the flow
#: several times in a row gets one pass over the script they ended with.
DEBOUNCE_S: Final = 30
#: Joined to the script before it is hashed into `script_heal_inputs`: a new or changed check
#: changes it, so every script is checked once more by the next sweep.
CHECKS_VERSION: Final = "heal-6"
#: The key in `script_heal_fixed` that records a whole-script rewrite asked for under the
#: current rules (`workers/script_heal._ask_rewrite`), so it is asked once per holder.
REWRITE_KEY: Final = f"pip_rewrite:{REWRITE_RULES}"

HolderKind = Literal["campaign", "line"]

SLOTS: Final[dict[HolderKind, agent_pass.PassSlot]] = {
    "campaign": agent_pass.PassSlot(
        "script_heal", JOB, table="campaigns", gone="archived_at", id_key="campaign_id"
    ),
    "line": agent_pass.PassSlot(
        "script_heal", JOB, table="inbound_lines", gone="archived_at", id_key="line_id"
    ),
}

#: What the call page says beside a mistake the script caused (`call_fix_states`).
CallFix = Literal["repaired", "repairing"]


def table_of(kind: HolderKind) -> str:
    """The holder's table, as a conditional of literals so `scripts/check_raw_sql.py` can
    read it."""
    return "campaigns" if kind == "campaign" else "inbound_lines"


def heal_findings(script: CallScript | None, lint: LintContext) -> list[str]:
    """Every fault a repair may clear in `script`, as "<path>: <problem>": every registered
    check, on the lines a repair may change (`script_checks.repairs`, which the writer's
    repair rounds read too). [] for no script or a hand-written one, which has no lines to
    point at."""
    if script is None or script.raw_override or not script.stages:
        return []
    return script_checks.repairs(script, lint)


def kind_findings(script: CallScript | None, lint: LintContext, kind: str) -> list[str]:
    """The faults of call mistake `kind` a repair may clear: the heal pass's own findings
    (`heal_findings`) of that kind's checks, so the healer's VERIFY (`workers/mistake_fix`)
    reads a script clean exactly when the repair pass does."""
    ids = script_checks.MISTAKE_CHECKS.get(kind)
    if script is None or script.raw_override or not script.stages or not ids:
        return []
    return script_checks.repairs(script, lint, ids=ids)


async def holder_lint_context(
    session: AsyncSession, kind: HolderKind, holder_id: UUID, agent_id: UUID
) -> LintContext:
    """What a holder's saved script is checked against, by every path that checks one (the
    heal pass, the healer's VERIFY, Save, Keep and Put it live): the agent's context
    (`lint_context_for`) in the holder's own call language, with its job's judged details;
    promo off, as the put-live dialog shows the promotional wording on its own (D-943)."""
    from apps.api.agents import script_builder
    from apps.api.agents.capability_manifest import lint_context_for

    tenant = await _tenant_of(session, kind, holder_id)
    if tenant is None:
        raise ProblemError.not_found("Campaign" if kind == "campaign" else "Inbound line")
    lint = await lint_context_for(session, tenant_id=tenant, agent_id=agent_id)
    details = await (
        script_builder.campaign_details if kind == "campaign" else script_builder.line_details
    )(session, holder_id)
    language = (
        (
            await session.execute(
                text("SELECT settings_overrides->>'language_primary' FROM campaigns WHERE id = :h"),
                {"h": holder_id},
            )
        ).scalar()
        if kind == "campaign"
        else None
    )
    return replace(
        lint, promo=False, language=str(language or lint.language), judged=details.judged
    )


def wired_ways_out(script: CallScript, lint: LintContext) -> CallScript:
    """`script` with every step's way out that is stated only in its instruction given as a
    branch (`script_structure.ways_out_wired`), and without the ways out that only name the
    step the call goes to anyway (`without_echo_ways`). Deterministic, so a repair pass
    applies it before asking the model anything. A hand-written script has no stages, so
    nothing to wire."""
    every = {stage.id for stage in script.stages}
    mended = without_echo_ways(ways_out_wired(script, every, lint.manifest), every)
    return without_judged_asks(mended, every)


def mistake_kinds(script: CallScript | None, lint: LintContext) -> set[str]:
    """The call mistake kinds whose script check faults a line a repair may change."""
    return {k for k in script_checks.SCRIPT_FIXABLE_KINDS if kind_findings(script, lint, k)}


def holder_kind(kind: str) -> HolderKind:
    """`mistake_fixes.HolderKind` ("inbound_line") in this module's words."""
    return "campaign" if kind == "campaign" else "line"


async def _tenant_of(session: AsyncSession, kind: HolderKind, holder_id: UUID) -> UUID | None:
    found = (
        await session.execute(
            text(f"SELECT tenant_id FROM {table_of(kind)} WHERE id = :hid"), {"hid": holder_id}
        )
    ).scalar()
    return None if found is None else UUID(str(found))


async def queue_after_save(
    session: AsyncSession, kind: HolderKind, holder_id: UUID, script: CallScript | None
) -> bool:
    """In the saving transaction: ask for a pass over the saved script. True when a job was
    promised. A pass already waiting is pushed back instead (`DEBOUNCE_S`).

    Nobody pressed a button for this pass, so an account whose owner has not turned Pip on is
    marked `skipped`, which the sweep asks again each hour."""
    if script is None or script.raw_override:
        return False
    tenant = await _tenant_of(session, kind, holder_id)
    if tenant is None:
        return False
    table = table_of(kind)
    if not await account_content_may_reach_models(session, tenant_id=tenant):
        await session.execute(
            text(
                f"UPDATE {table} SET script_heal_state = 'skipped', script_heal_at = now() "
                "WHERE id = :hid AND script_heal_state IS DISTINCT FROM 'running'"
            ),
            {"hid": holder_id},
        )
        return False
    if await agent_pass.queue(session, SLOTS[kind], tenant_id=tenant, row_id=holder_id):
        return True
    await session.execute(
        text(
            f"UPDATE {table} SET script_heal_at = now() "
            "WHERE id = :hid AND script_heal_state = 'queued'"
        ),
        {"hid": holder_id},
    )
    return False


async def queue_now(
    session: AsyncSession, kind: HolderKind, holder_id: UUID, *, tenant_id: UUID
) -> bool:
    """Ask for a pass that reads the script afresh, whatever the last one read: a call showed
    a mistake the script causes. True when a job was promised; False when one is already
    waiting or running, which reads the script it finds."""
    return await agent_pass.queue(
        session, SLOTS[kind], tenant_id=tenant_id, row_id=holder_id, force=True
    )


async def pending(session: AsyncSession, kind: HolderKind, holder_id: UUID) -> bool:
    """Is a pass waiting or running for this holder, with a live job behind it?"""
    return bool(
        (
            await session.execute(
                text(
                    f"SELECT script_heal_state IN ('queued', 'running') "
                    f"AND NOT {dead_sql(SLOTS[kind])} FROM {table_of(kind)} WHERE id = :hid"
                ),
                {"hid": holder_id},
            )
        ).scalar()
    )


async def call_fix_states(
    session: AsyncSession,
    *,
    campaign_id: UUID | None,
    inbound_line_id: UUID | None,
    call_started_at: datetime | None,
    kinds: list[str],
) -> dict[str, CallFix]:
    """For each mistake kind a call showed, whether the script it was spoken from has been
    repaired of it since the call (`repaired`), or a repair is under way (`repairing`).
    A kind left out is one no repair has reached: our team has it."""
    kind: HolderKind
    if campaign_id is not None:
        kind, holder_id = "campaign", campaign_id
    elif inbound_line_id is not None:
        kind, holder_id = "line", inbound_line_id
    else:
        return {}
    row = (
        await session.execute(
            text(
                f"SELECT script_heal_fixed, script_heal_state IN ('queued', 'running') "
                f"AND NOT {dead_sql(SLOTS[kind])} FROM {table_of(kind)} WHERE id = :hid"
            ),
            {"hid": holder_id},
        )
    ).first()
    if row is None:
        return {}
    fixed: dict[str, Any] = row[0] or {}
    working = bool(row[1])
    out: dict[str, CallFix] = {}
    for mistake in kinds:
        at = fixed.get(mistake)
        if at is not None and (
            call_started_at is None or datetime.fromisoformat(str(at)) >= call_started_at
        ):
            out[mistake] = "repaired"
        elif working and mistake in script_checks.SCRIPT_FIXABLE_KINDS:
            out[mistake] = "repairing"
    return out


__all__ = [
    "CHECKS_VERSION",
    "DEBOUNCE_S",
    "JOB",
    "REWRITE_KEY",
    "SLOTS",
    "CallFix",
    "HolderKind",
    "call_fix_states",
    "heal_findings",
    "holder_kind",
    "mistake_kinds",
    "pending",
    "queue_after_save",
    "queue_now",
    "table_of",
    "wired_ways_out",
]
