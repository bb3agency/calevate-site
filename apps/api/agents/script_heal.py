"""Pip repairs the lines of an existing script that the script checks fault (founder, 24 Nov
2026: anything Pip can fix is fixed automatically, never left for the owner or our team).

The script checks run when Pip writes a draft, so a campaign's or inbound line's script
written before a check existed, or by hand, keeps its fault on every call: a step that asks
"is now a good time?" again after the opening, lines that all open with one reaction or end
with one tag, a repeat in brackets, a textbook word. This module names those faults
(`heal_findings`) and queues the repair pass (`workers/script_heal.repair_holder_script`),
which has Pip rewrite exactly the faulted lines (`script_proposals.kept_to_paths`) and saves
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

from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from calevate_shared.spoken_guard import textbook_problem
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import agent_pass
from apps.api.agents.agent_pass import dead_sql
from apps.api.agents.call_rules import opening_redone_line_problems, reacted_line_problems
from apps.api.agents.mistake_fixes import fix_paths
from apps.api.agents.mistake_lints import SCRIPT_FIXABLE_KINDS, mistake_findings, script_mistakes
from apps.api.agents.script_lint import LintContext, agent_lines, flow_problems
from apps.api.agents.script_shape import line_problems
from apps.api.agents.script_structure import (
    ways_out_wired,
    without_echo_ways,
    without_judged_asks,
)
from apps.api.campaigns.script_history import REWRITE_RULES
from apps.api.copilot.consent import account_content_may_reach_models

#: The ARQ name of the pass (`workers/script_heal`).
JOB: Final = "repair_holder_script"
#: A pass starts this long after the last save that asked for it, so an owner saving the flow
#: several times in a row gets one pass over the script they ended with.
DEBOUNCE_S: Final = 30
#: Joined to the script before it is hashed into `script_heal_inputs`: a new or changed check
#: changes it, so every script is checked once more by the next sweep.
CHECKS_VERSION: Final = "heal-4"
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


def _node(script: CallScript, path: str) -> Any:
    node: Any = script.model_dump(mode="json")
    for part in path.split("."):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _repairable(script: CallScript, finding: str) -> bool:
    """Whether a repair may rewrite the place `finding` names: one line, never an opening or
    its notices, never a step outcome."""
    path = finding.partition(": ")[0]
    return (
        not path.startswith("step_outcomes")
        and bool(fix_paths([finding]))
        and isinstance(_node(script, path), str)
    )


def _textbook(script: CallScript, language: str) -> list[str]:
    if not language:
        return []
    lines = [
        *agent_lines(script),
        *(
            (f"stages.{i}.procedure.{j}.action", step.action)
            for i, stage in enumerate(script.stages)
            for j, step in enumerate(stage.procedure)
        ),
    ]
    return [
        problem
        for path, line in lines
        if line.strip() and (problem := textbook_problem(path, line, language))
    ]


def heal_findings(script: CallScript | None, lint: LintContext) -> list[str]:
    """Every fault a repair may clear in `script`, each once, as script check findings
    ("<path>: <problem>"): the call's shape (`flow_problems`, brackets included), a step's
    line that redoes the opening or opens with a reaction, every call-mistake check, textbook
    words in the call language, and a line giving several actions or noting what the caller
    does (`script_shape.line_problems`). [] for no script or a hand-written one, which has no
    lines to point at."""
    if script is None or script.raw_override or not script.stages:
        return []
    found = [
        *flow_problems(script),
        *opening_redone_line_problems(script),
        *reacted_line_problems(script),
        *script_mistakes(script, lint),
        *_textbook(script, lint.language),
        *line_problems(script),
    ]
    return list(dict.fromkeys(f for f in found if _repairable(script, f)))


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
    if script is None:
        return set()
    return {
        kind
        for kind in SCRIPT_FIXABLE_KINDS
        if any(_repairable(script, f) for f in mistake_findings(script, lint, kind))
    }


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
        elif working and mistake in SCRIPT_FIXABLE_KINDS:
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
