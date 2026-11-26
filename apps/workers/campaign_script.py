"""Pip writes a campaign's script (D-992) and an inbound line's (D-997): one job for both
holders, so a line and a campaign are written and checked alike.

Queued by `campaigns/workspace.request_proposal` and `inbound/lines.request_proposal`. The
job reads the holder's context once (`workers/script_context.holder_context`: main task,
sources, settings, details, language, direction, the owner's request) and hands one request
to THE script writer (`workers/script_writer.write_script`), which plans the steps in code
and writes each step by its own small request. Which request:

- a first script, a request that lays out the steps itself (`owner_plan`), and the rewrite
  under the current rules (`workers/script_heal._ask_rewrite`) are written `whole`;
- "Generate again" and an owner's free-form ask on an existing script are `whole` from that
  script: its shape is kept unless the ask changes it, which a checked outline does;
- the flow ask ("Let Pip map the scenarios") is `whole` from a fresh outline;
- a one-part ask is `steps` for a step, `opening` for the opening, `lines` for any other part.

Every write back is a compare-and-set on the proposal id, so a draft the owner stopped or
replaced is never resurrected; every request is metered, refusals included (hard rule 7).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import MAX_SCRIPT_STAGES, CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals
from apps.api.agents.prompt_size import PromptSize
from apps.api.campaigns import script_history, workspace
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.workers.campaign_script_ask import FLOW_PART, TOO_LONG_RULE, task_steps_note
from apps.workers.script_assist import ANSWER_UNUSABLE_CODE, LeftOut
from apps.workers.script_context import HolderKind, ScriptContext, holder_context, measured
from apps.workers.script_writer import (
    WriteRefusedError,
    WriteRequest,
    WriteResult,
    meter,
    write_script,
)

log = get_logger(__name__)

#: The stage fields an examples-only ask takes from the step writer's answer.
EXAMPLES_ONLY: Final = frozenset({"examples"})

UNUSABLE_NOTE: Final = (
    "Pip could not write a clean script this time. Your script is unchanged. "
    "Try again, or add a note saying what the calls should say."
)


@dataclass(frozen=True)
class _Holder:
    """Where a draft lives: the table whose `script_proposal` it is written into, and the
    row. `table` is one of our two constants, never input."""

    table: str
    holder_id: UUID
    tenant_id: UUID
    proposal_id: UUID
    log_key: str


def _table_of(holder: _Holder) -> str:
    """The holder's table as a literal, so the SQL it is spliced into is built only from text
    written here (`scripts/check_raw_sql.py`)."""
    return "inbound_lines" if holder.table == "inbound_lines" else "campaigns"


def _campaign(tenant_id: UUID, campaign_id: UUID, proposal_id: UUID) -> _Holder:
    return _Holder("campaigns", campaign_id, tenant_id, proposal_id, "campaign_id")


def _line(tenant_id: UUID, line_id: UUID, proposal_id: UUID) -> _Holder:
    return _Holder("inbound_lines", line_id, tenant_id, proposal_id, "line_id")


async def _claim(holder: _Holder) -> bool:
    """Take the request once: the outbox delivers at least once."""
    async with tenant_session(holder.tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    f"UPDATE {_table_of(holder)} SET script_proposal = script_proposal || "
                    "jsonb_build_object('claimed', true, 'phase', 'reading') WHERE id = :hid "
                    "AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' "
                    "AND script_proposal->>'claimed' IS NULL RETURNING id"
                ),
                {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
            )
        ).first()
    return claimed is not None


async def _store(session: AsyncSession, holder: _Holder, update: dict[str, Any]) -> bool:
    """Write into the draft by compare-and-set on its id: a stopped draft stays stopped."""
    stored = (
        await session.execute(
            text(
                f"UPDATE {_table_of(holder)} SET script_proposal = script_proposal || "
                "CAST(:u AS jsonb) WHERE id = :hid AND script_proposal->>'id' = :pid "
                "RETURNING id"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id), "u": json.dumps(update)},
        )
    ).first()
    return stored is not None


class _DraftStoppedError(Exception):
    """The draft was stopped or replaced while this job wrote it (`script_draft.cancel_draft`,
    the page's Stop): the job ends at the next phase instead of spending on further passes."""


async def _phase(holder: _Holder, phase: str) -> None:
    """Tell the draft stream where the writer is, and stop if the draft is gone.

    The cancel is cooperative, checked here between the writer's passes, rather than an arq
    `Job.abort()`: an abort raises `CancelledError` inside a model request whose answer is
    then never metered (hard rule 7), and the worker runs with `allow_abort_jobs` off. A pass
    already under way finishes and is metered; nothing after it runs or is stored."""
    async with tenant_session(holder.tenant_id) as session:
        if not await _store(session, holder, {"phase": phase}):
            raise _DraftStoppedError


async def _save_if_asked(session: AsyncSession, holder: _Holder, script: CallScript) -> None:
    """A draft asked for with `auto_save` (the first run's, Phase 3b) becomes the holder's
    script at once, with no review, while the holder still has none: a script the owner
    saved meanwhile is never replaced. Saved through the holder's own save, so its length is
    held to the agent's limits; a draft refused there stays for the owner to review."""
    from apps.api.inbound import lines

    row = (
        await session.execute(
            text(
                f"SELECT script IS NULL AS empty, script_proposal->>'auto_save' AS auto "
                # Locked, so an owner's save in flight is waited for and then seen.
                f"FROM {_table_of(holder)} WHERE id = :hid AND script_proposal->>'id' = :pid "
                "FOR UPDATE"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )
    ).first()
    if row is None or row.auto != "true" or not row.empty:
        return
    try:
        async with session.begin_nested():
            if holder.table == "inbound_lines":
                await lines.save_script(
                    session,
                    holder.holder_id,
                    script,
                    author="pip_draft",
                    reason=script_history.FIRST_RUN_REASON,
                )
            else:
                await workspace.save_script(
                    session,
                    holder.holder_id,
                    script,
                    author="pip_draft",
                    reason=script_history.FIRST_RUN_REASON,
                )
            await session.execute(
                text(f"UPDATE {_table_of(holder)} SET script_proposal = NULL WHERE id = :hid"),
                {"hid": holder.holder_id},
            )
    except ProblemError as refused:
        log.info("holder_script_kept_for_review", extra={"reason": refused.code})
        # The draft waits for the owner's review; the first run still needs something to
        # ring, so the ready-made script stands in until they keep the draft.
        await _ready_made(session, holder)


async def _dropped_if_rewrite(session: AsyncSession, holder: _Holder) -> bool:
    """Clear a rewrite's draft (`workers/script_heal._ask_rewrite`), by compare-and-set on its
    id: nobody asked for it, so a rewrite that cannot be saved leaves no draft or failure on
    the owner's page. True when the draft was a rewrite and is gone."""
    return (
        await session.execute(
            text(
                f"UPDATE {_table_of(holder)} SET script_proposal = NULL WHERE id = :hid "
                "AND script_proposal->>'id' = :pid "
                "AND script_proposal->'ask'->>'rewrite' IS NOT NULL RETURNING id"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )
    ).first() is not None


async def _save_if_rewrite(
    session: AsyncSession, holder: _Holder, script: CallScript, *, clean: bool
) -> None:
    """A rewrite under the current rules (founder, 25 Nov 2026) becomes the holder's script
    at once, through the holder's own Save, which keeps it as a `pip_draft` version (so the
    Versions list and Put back reach the script before it), and is then put on the calls of a
    holder that takes them (`notes_live.queue_put_live`, as the heal pass's repairs are).
    Nobody reviews it (founder, 26 Nov 2026: a non-technical owner should not have to), so
    only a CLEAN draft is saved: one the writer left warnings on (`clean` False) is dropped
    and the script keeps its line repairs, rather than saved with its warnings thrown away.
    Only while the script is still the one the rewrite was written from and still Pip's
    (`script_history.pip_owns`): an owner's save meanwhile wins, and the draft is dropped.
    A save refused for its length drops it too."""
    from apps.api.campaigns.notes_live import queue_put_live
    from apps.api.inbound import lines

    if not clean:
        if await _dropped_if_rewrite(session, holder):
            log.info("holder_script_rewrite_dropped", extra={"reason": "warnings"})
        return

    kind: script_history.HolderKind = "line" if holder.table == "inbound_lines" else "campaign"
    row = (
        await session.execute(
            text(
                f"SELECT script, script_proposal->'base_script' AS base, "
                f"script_proposal->'ask'->>'rewrite' AS rewrite FROM {_table_of(holder)} "
                # Locked, so an owner's save in flight is waited for and then seen.
                "WHERE id = :hid AND script_proposal->>'id' = :pid FOR UPDATE"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )
    ).first()
    if row is None or row.rewrite is None:
        return
    if row.script != row.base or not await script_history.pip_owns(session, kind, holder.holder_id):
        log.info("holder_script_rewrite_dropped", extra={"reason": "changed"})
        await _dropped_if_rewrite(session, holder)
        return
    try:
        async with session.begin_nested():
            if kind == "line":
                await lines.save_script(
                    session,
                    holder.holder_id,
                    script,
                    author="pip_draft",
                    reason=script_history.REWRITE_REASON,
                )
            else:
                await workspace.save_script(
                    session,
                    holder.holder_id,
                    script,
                    author="pip_draft",
                    reason=script_history.REWRITE_REASON,
                )
            await _dropped_if_rewrite(session, holder)
            await queue_put_live(
                session,
                tenant_id=holder.tenant_id,
                jobs=[("line" if kind == "line" else "campaign", holder.holder_id)],
            )
    except ProblemError as refused:
        log.info("holder_script_rewrite_dropped", extra={"reason": refused.code})
        await _dropped_if_rewrite(session, holder)


async def _ready_made(session: AsyncSession, holder: _Holder) -> None:
    """The first run's work (`auto_save`) gets the ready-made script when Pip's own cannot
    be saved, so the owner still reaches the test call (`first_run.work.save_ready_made`).
    A refusal leaves the holder as it was: the screen then offers to write it by hand."""
    from apps.api.first_run.work import save_ready_made

    ids = (
        {"line_id": holder.holder_id}
        if holder.table == "inbound_lines"
        else {"campaign_id": holder.holder_id}
    )
    try:
        async with session.begin_nested():
            await save_ready_made(session, tenant_id=holder.tenant_id, **ids)
    except ProblemError as refused:
        log.info("holder_ready_made_refused", extra={"reason": refused.code})


async def _ready_made_if_asked(holder: _Holder) -> None:
    """After a failed draft: the ready-made script for a first-run holder still without one.
    The failed draft is cleared with it, since the holder now has a script to change."""
    async with tenant_session(holder.tenant_id) as session:
        auto = (
            await session.execute(
                text(
                    f"SELECT script_proposal->>'auto_save' FROM {_table_of(holder)} "
                    "WHERE id = :hid AND script_proposal->>'id' = :pid AND script IS NULL "
                    "FOR UPDATE"
                ),
                {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
            )
        ).scalar_one_or_none()
        if auto != "true":
            return
        await _ready_made(session, holder)
        await session.execute(
            text(
                f"UPDATE {_table_of(holder)} SET script_proposal = NULL WHERE id = :hid "
                "AND script_proposal->>'id' = :pid AND script IS NOT NULL"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )


async def _fail(
    holder: _Holder,
    note: str,
    left_out: list[LeftOut] | None = None,
    *,
    reason: str,
) -> None:
    update = {
        "status": "failed",
        "note": note[:400],
        "reason": reason,
        "left_out": script_proposals.left_out_record(left_out or []),
    }
    async with tenant_session(holder.tenant_id) as session:
        if not await _dropped_if_rewrite(session, holder):
            await _store(session, holder, update)


async def draft_campaign_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """A campaign's script, from its main task and the sources it picked."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    holder = _campaign(
        tenant_id, UUID(str(payload["campaign_id"])), UUID(str(payload["proposal_id"]))
    )
    if not await _claim(holder):
        return "not_pending"
    return await _write(holder, "campaign", time.monotonic())


async def draft_line_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """An inbound line's script (D-997), from its main task and the sources it picked."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    holder = _line(tenant_id, UUID(str(payload["line_id"])), UUID(str(payload["proposal_id"])))
    if not await _claim(holder):
        return "not_pending"
    return await _write(holder, "line", time.monotonic())


def _part_request(context: ScriptContext, base: CallScript, started: float) -> WriteRequest:
    """A one-part ask (`focus.part`, the part's name as the review shows it) as a request:
    the step it names, the opening, or the lines of the part it names; the flow ask is a
    whole script from a fresh outline."""
    part = (context.part or "").strip()
    folded = part.casefold()
    named = [s.id for s in base.stages if s.name.strip() and s.name.casefold() in folded]
    if context.want == "examples":
        # "Let Pip write examples": only the example turns, of the step named or of every
        # step, the instructions and actions kept word for word.
        return WriteRequest(
            "steps",
            context,
            started,
            base=base,
            step_ids=tuple(named[:1] or [s.id for s in base.stages]),
            fields=EXAMPLES_ONLY,
        )
    if part == FLOW_PART:
        return WriteRequest("whole", context, started, base=base, outline=True)
    if "opening" in folded:
        return WriteRequest("opening", context, started, base=base)
    if named:
        return WriteRequest("steps", context, started, base=base, step_ids=tuple(named[:1]))
    paths = script_proposals.part_paths(base, part)
    if paths:
        rule = f"rewrite it in {context.part_language or context.language}, as said on the call"
        return WriteRequest(
            "lines", context, started, base=base, problems=tuple(f"{p}: {rule}" for p in paths)
        )
    return WriteRequest("whole", context, started, base=base)


def write_request(context: ScriptContext, started: float) -> WriteRequest:
    """The request a holder's draft is: see the module."""
    base = context.asked_from
    if context.part is not None and base is not None:
        return _part_request(context, base, started)
    if context.rewrite or base is None:
        return WriteRequest("whole", context, started)
    return WriteRequest("whole", context, started, base=base)


def too_long_left(size: PromptSize | None) -> list[LeftOut]:
    """The warning for a script that would not fit the engine's box."""
    if size is None or size.fits:
        return []
    parts = ", ".join(part.label for part in size.longest_script_parts(2)) or "the steps"
    return [LeftOut("script", "", TOO_LONG_RULE.format(over=size.over, parts=parts), unfixed=True)]


def over_plan_left(context: ScriptContext) -> list[LeftOut]:
    """Each of the owner's steps the step limit could not hold."""
    plan = context.owner_plan
    return [
        LeftOut(
            "stages",
            "",
            f'Only {MAX_SCRIPT_STAGES} steps fit a script, so "{step.name}" is not in it; '
            "merge two steps or take one out to make room.",
            unfixed=True,
        )
        for step in (plan.over if plan is not None else ())
    ]


def _failed_note(refused: ProblemError) -> str:
    if refused.code == ANSWER_UNUSABLE_CODE:
        return UNUSABLE_NOTE
    note = " ".join(p for p in (refused.detail, refused.remediation) if p)
    return note or script_proposals.FAILED_NOTE


def _disclosure(result: WriteResult) -> str | None:
    """A request the standby answered is disclosed with the draft (D-127 G-6)."""
    return next(
        (
            spent.capability.disclosure
            for spent in result.spends
            if not isinstance(spent, ProblemError) and spent.capability.disclosure
        ),
        None,
    )


async def _write(holder: _Holder, kind: HolderKind, started: float) -> str:
    """Write, check, store and meter one holder's draft."""
    tenant_id = holder.tenant_id
    log_ids = {holder.log_key: str(holder.holder_id)}
    context = await holder_context(tenant_id, kind, holder.holder_id)
    try:
        await _phase(holder, "writing")
    except _DraftStoppedError:
        log.info("holder_script_cancelled", extra={**log_ids, "spends": 0})
        return "cancelled"
    request = write_request(context, started)
    try:
        result = await write_script(request)
    except WriteRefusedError as refused:
        log.info("holder_script_refused", extra={**log_ids, "reason": refused.refused.code})
        async with tenant_session(tenant_id) as session:
            await meter(session, tenant_id, refused.spends)
        await _fail(holder, _failed_note(refused.refused), reason=refused.refused.code)
        await _ready_made_if_asked(holder)
        return "refused"
    except Exception:
        log.exception("holder_script_crashed", extra=log_ids)
        await _fail(holder, workspace.FAILED_NOTE, reason="crashed")
        await _ready_made_if_asked(holder)
        return "failed"
    try:
        await _phase(holder, "checking")
    except _DraftStoppedError:
        async with tenant_session(tenant_id) as session:
            await meter(session, tenant_id, result.spends)
        log.info("holder_script_cancelled", extra={**log_ids, "spends": len(result.spends)})
        return "cancelled"
    left_out = [
        *result.left_out,
        *too_long_left(await measured(context, result.script)),
        *over_plan_left(context),
    ]
    why = {"step_outcomes": task_steps_note(result.task_plan)} if result.task_plan else {}
    update = {
        "status": "ready",
        "script": result.script.model_dump(mode="json"),
        "disclosure": _disclosure(result),
        "left_out": script_proposals.left_out_record(left_out),
        "why": why,
    }
    # A completed run is money spent: metered in the same transaction that stores the draft.
    async with tenant_session(tenant_id) as session:
        stored = await _store(session, holder, update)
        if stored:
            await _save_if_asked(session, holder, result.script)
            await _save_if_rewrite(session, holder, result.script, clean=not left_out)
        await meter(session, tenant_id, result.spends)
    log.info(
        "holder_script_written",
        extra={
            **log_ids,
            "stored": stored,
            "mode": request.mode,
            "requests": len(result.spends),
            "left": len(left_out),
        },
    )
    return "ready" if stored else "not_pending"


__all__ = [
    "UNUSABLE_NOTE",
    "draft_campaign_script",
    "draft_line_script",
    "over_plan_left",
    "too_long_left",
    "write_request",
]
