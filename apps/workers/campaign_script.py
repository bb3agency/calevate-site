"""Pip writes a campaign's script (D-992) and an inbound line's (D-997) from the holder's
main task and the sources it picked from What your agents know, by the same steps: one
writer for both holders, so a line and a campaign are written and checked alike.

Queued by `campaigns/workspace.request_proposal` and `inbound/lines.request_proposal`. The
script is written by the one script writer (`workers/script_assist.draft_script`) in the
holder's agent's language and business context (`agents/script_proposals.brief_for`). A first
script is written whole, from the trade's step plan like any new script; one that already
exists gets an edit of it, so the owner's own wording survives wherever the sources do not
change it. Documents are read
the way onboarding reads them (`first_run.documents_block`: redacted, fenced, one word budget).

What Pip wrote then goes through what every Pip script does before an owner reviews it
(`script_proposal.finish_written`): the call-mistake checks and their repair (D-989), then the
opening rule and its repair (D-957). Every write back is a compare-and-set on the proposal id,
so a draft the owner stopped or replaced is never resurrected.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.languages import LANGUAGE_LABELS
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.campaigns import workspace
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers.first_run import documents_block
from apps.workers.opening_line import WrittenOpening
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    AskTrace,
    JsonAnswer,
    LeftOut,
    ScriptDraft,
    draft_script,
)
from apps.workers.script_proposal import (
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_REQUEST_TIMEOUT_S,
    finish_written,
    refusal_note,
)

log = get_logger(__name__)

#: The last step's name (founder, 16 Nov 2026): a booking is one scenario of many, so the step
#: that reads back and closes is the call's own, never "the booking".
CLOSING_STEP: Final = (
    ' Name the last step "Finalise the call": it reads back what was agreed and closes. A '
    "booking, where one fits, is a step of its own before it."
)

#: The ask, shared by a first script and an edit; each adds its own last sentence.
CAMPAIGN_ASK: Final = (
    "Write this campaign's call script. Every call this agent places for the campaign follows "
    "it. The campaign's main task, in the owner's words, says what the calls must achieve; the "
    "owner's notes, links and documents below say what to tell people and how. Write the "
    "opening line for the call it places, the steps that get to the main task one at a time, "
    "quick facts (the faqs list: a question people ask and a short spoken answer, at most "
    "eight), the objections people raise with how to answer, and how the call ends. Where a "
    "note or document says how the agent should handle the call, follow it."
) + CLOSING_STEP
#: An inbound line's ask (D-997): the calls are answered, not placed.
LINE_ASK: Final = (
    "Write this phone line's call script. Every call to this number is answered with it. "
    "The main task, in the owner's words, says what callers need; the sources below say "
    "what to tell them and how. Write the greeting the agent says when it answers, the steps "
    "that get to the main task one at a time, quick facts (the faqs list: a question callers "
    "ask and a short spoken answer, at most eight), the objections callers raise with how to "
    "answer, and how the call ends. Where a source says how the agent should handle the "
    "call, follow it."
) + CLOSING_STEP
UNUSABLE_NOTE: Final = (
    "Pip's script still broke a call rule after its repairs. Press Generate to try again, or "
    "add a note saying what the calls should say."
)
EDIT_TAIL: Final = (
    " Keep anything already in the script that the main task and sources do not change."
)


def owners_words(main_task: str, notes: str) -> str:
    """The campaign in the owner's own words: a line Pip took from them word for word is
    theirs, and is not judged by the opening rule (`finish_written`)."""
    return "\n".join(part for part in (main_task.strip(), notes) if part)


#: One part rewritten in a chosen language (founder, 16 Nov 2026); the rest stays word for word.
PART_ASK: Final = (
    "Rewrite only this part of the campaign's call script: {part}. Write it in {language}, as "
    "it should be spoken on the call. Leave every other part of the script exactly as it is. "
    "The main task and the owner's notes below say what the part must cover."
)


#: The part name the Script section's "Let Pip map the scenarios" sends (`CampaignFlow`).
FLOW_PART: Final = "flow"
#: The call's steps rewritten as the ways it is likely to go, each with its way out.
FLOW_ASK: Final = (
    "Rewrite only the steps of the campaign's call script as a flow of scenarios. Predict the "
    "ways a call is likely to go: for example the person recognises the business, does not "
    "remember it, is busy, is not interested, or has already done what the call asks. Make a "
    "step for each scenario worth handling, and give each step its ways out (branches): when "
    "the person says or does this, go to the step that handles it, to a call back, or to the "
    "end of the call. Write each step's instruction in plain English and its sounds-like line "
    "in {language}. Leave every other part of the script exactly as it is."
) + CLOSING_STEP


def campaign_change(
    main_task: str,
    notes: str,
    documents: str,
    *,
    edit: bool,
    ask: str = CAMPAIGN_ASK,
    part_ask: str | None = None,
) -> str:
    """What the script is written from: the ask, the main task, the notes and the documents.
    A one-part rewrite replaces the whole ask, edit tail included."""
    lead = part_ask if part_ask is not None else f"{ask}{EDIT_TAIL if edit else ''}"
    change = f"{lead}\nMAIN TASK:\n{main_task.strip()}\n"
    if notes:
        change += f"OWNER'S NOTES AND LINKS:\n{notes}\n"
    return change + documents


def _proposal(
    proposal_id: UUID, base: CallScript | None, request: str
) -> script_proposals.ScriptProposal:
    """The campaign's request in the agent proposal's shape, which `finish_written` reads: a
    `change` of the campaign's script, or a `whole` first script, so a finding the owner's own
    script already had stays theirs to fix."""
    return script_proposals.ScriptProposal(
        id=proposal_id,
        mode="change" if base is not None else "whole",
        status="drafting",
        request=request,
        answers={},
        base_script=base or CallScript(),
        requested_by=None,
        requested_at=datetime.now(UTC),
    )


def _failed_note(refused: ProblemError, trace: AskTrace) -> str:
    """The agent page's note, except for an answer that broke a rule on every try with no
    part named: its words speak of a change, and a campaign script is written whole."""
    if refused.code == ANSWER_UNUSABLE_CODE and not trace.unwritten:
        return UNUSABLE_NOTE
    return refusal_note(refused, trace)


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
                    "jsonb_build_object('claimed', true) WHERE id = :hid "
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
                f"FROM {_table_of(holder)} WHERE id = :hid AND script_proposal->>'id' = :pid"
            ),
            {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
        )
    ).first()
    if row is None or row.auto != "true" or not row.empty:
        return
    try:
        async with session.begin_nested():
            if holder.table == "inbound_lines":
                await lines.save_script(session, holder.holder_id, script)
            else:
                await workspace.save_script(session, holder.holder_id, script)
            await session.execute(
                text(f"UPDATE {_table_of(holder)} SET script_proposal = NULL WHERE id = :hid"),
                {"hid": holder.holder_id},
            )
    except ProblemError as refused:
        log.info("holder_script_kept_for_review", extra={"reason": refused.code})
        # The draft waits for the owner's review; the first run still needs something to
        # ring, so the ready-made script stands in until they keep the draft.
        await _ready_made(session, holder)


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
                    f"SELECT script_proposal->>'auto_save' FROM {holder.table} "
                    "WHERE id = :hid AND script_proposal->>'id' = :pid AND script IS NULL"
                ),
                {"hid": holder.holder_id, "pid": str(holder.proposal_id)},
            )
        ).scalar_one_or_none()
        if auto != "true":
            return
        await _ready_made(session, holder)
        await session.execute(
            text(
                f"UPDATE {holder.table} SET script_proposal = NULL WHERE id = :hid "
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
        await _store(session, holder, update)


@dataclass(frozen=True)
class _Inputs:
    """What a holder's script is written from, read in one tenant session."""

    agent_id: UUID
    main_task: str
    base: CallScript | None
    notes: str
    words: list[tuple[str, str]]
    context: Any
    tenant_leg: Any
    quota_exhausted: bool


async def draft_campaign_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """A campaign's script, from its main task and the sources it picked from What your
    agents know: typed notes and documents alike are read as documents."""
    from apps.workers.company_training_draft import knowledge_words

    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    campaign_id = UUID(str(payload["campaign_id"]))
    holder = _campaign(tenant_id, campaign_id, UUID(str(payload["proposal_id"])))
    if not await _claim(holder):
        return "not_pending"
    started = time.monotonic()
    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
        words = await knowledge_words(session, only=space.sources) if space.sources else []
        # Written in the campaign's main language when it sets one over the agent's.
        main_language, focus = (
            await session.execute(
                text(
                    "SELECT settings_overrides->>'language_primary', script_proposal->'focus' "
                    "FROM campaigns WHERE id = :c"
                ),
                {"c": campaign_id},
            )
        ).one()
        part_language = focus.get("language") if isinstance(focus, dict) else None
        context = await script_proposals.brief_for(
            session, tenant_id, space.agent_id, language=part_language or main_language
        )
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    # Written from the script the request was made from, as the review lists its changes
    # against it: a script saved since would otherwise be shown as Pip's change.
    inputs = _Inputs(
        agent_id=space.agent_id,
        main_task=space.main_task,
        base=space.proposal.base_script if space.proposal is not None else space.script,
        notes="",
        words=words,
        context=context,
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling or quota.platform_paused,
    )
    language_name = LANGUAGE_LABELS.get(str(part_language), str(part_language))
    is_flow = isinstance(focus, dict) and focus.get("part") == FLOW_PART
    part_ask = (
        FLOW_ASK.format(language=language_name)
        if is_flow and part_language
        else PART_ASK.format(
            part=str(focus.get("part")),
            language=language_name,
        )
        if isinstance(focus, dict) and part_language
        else None
    )
    return await _write(holder, inputs, CAMPAIGN_ASK, started, part_ask=part_ask)


async def draft_line_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """An inbound line's script (D-997), from its main task and the sources it picked from
    What your agents know: typed notes and documents alike are read as documents."""
    from apps.api.inbound import lines
    from apps.workers.company_training_draft import knowledge_words

    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    line_id = UUID(str(payload["line_id"]))
    holder = _line(tenant_id, line_id, UUID(str(payload["proposal_id"])))
    if not await _claim(holder):
        return "not_pending"
    started = time.monotonic()
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        words = await knowledge_words(session, only=line.sources) if line.sources else []
        context = await script_proposals.brief_for(session, tenant_id, line.agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    inputs = _Inputs(
        agent_id=line.agent_id,
        main_task=line.main_task,
        base=line.proposal.base_script if line.proposal is not None else line.script,
        notes="",
        words=words,
        context=context,
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling or quota.platform_paused,
    )
    return await _write(holder, inputs, LINE_ASK, started)


async def _write(
    holder: _Holder, inputs: _Inputs, ask: str, started: float, *, part_ask: str | None = None
) -> str:
    """Write, check, store and meter one holder's draft."""
    tenant_id = holder.tenant_id
    base = inputs.base
    notes = inputs.notes
    change = campaign_change(
        inputs.main_task,
        notes,
        documents_block(inputs.words),
        edit=base is not None,
        ask=ask,
        part_ask=part_ask,
    )
    proposal = _proposal(holder.proposal_id, base, owners_words(inputs.main_task, notes))
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    trace = AskTrace()
    write = partial(
        draft_script,
        tenant_leg=inputs.tenant_leg,
        quota_exhausted=inputs.quota_exhausted,
        timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
        max_tokens=PROPOSAL_MAX_TOKENS,
        trace=trace,
        repair_rounds=get_settings().campaign_script_repair_rounds,
        # The standby's 4,096-token ceiling cuts a whole Telugu script off, so an answer that
        # broke a rule is repaired by the account's model, never handed to it.
        standby_after_answer=False,
        owners_words=owners_words(inputs.main_task, notes),
    )
    log_ids = {holder.log_key: str(holder.holder_id)}
    try:
        if base is None:
            # A first script: written whole from the trade's step plan, the holder's words as
            # the owner's description, so every figure in them may be spoken.
            draft: ScriptDraft = await write(replace(inputs.context, description=change))
        else:
            draft = await write(inputs.context, edit_of=base, change=change)
    except ProblemError as refused:
        log.info(
            "holder_script_refused",
            extra={
                **log_ids,
                "reason": refused.code,
                "repairs": trace.repairs,
                "truncated": trace.truncated,
            },
        )
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        await _fail(holder, _failed_note(refused, trace), trace.unwritten, reason=refused.code)
        await _ready_made_if_asked(holder)
        return "refused"
    except Exception:
        log.exception("holder_script_crashed", extra=log_ids)
        await _fail(holder, workspace.FAILED_NOTE, reason="crashed")
        await _ready_made_if_asked(holder)
        return "failed"

    finished = await finish_written(tenant_id, inputs.agent_id, proposal, draft.script, started)
    spends: list[ScriptDraft | JsonAnswer[WrittenOpening] | ProblemError] = [
        draft,
        *finished.repairs,
        *finished.opening_spends,
    ]
    update = {
        "status": "ready",
        "script": finished.script.model_dump(mode="json"),
        # A draft or repair the standby answered is disclosed with it (D-127 G-6).
        "disclosure": next(
            (
                spent.capability.disclosure
                for spent in (draft, *finished.repairs)
                if not isinstance(spent, ProblemError) and spent.capability.disclosure
            ),
            None,
        ),
        "left_out": script_proposals.left_out_record([*trace.left_out, *finished.left_out]),
    }
    # A completed run is money spent: metered in the same transaction that stores the draft.
    async with tenant_session(tenant_id) as session:
        stored = await _store(session, holder, update)
        if stored:
            await _save_if_asked(session, holder, finished.script)
        for spent in spends:
            if isinstance(spent, ProblemError):
                await crm_assist.meter_refusal(
                    session, tenant_id=tenant_id, refusal=spent, feature=feature
                )
                continue
            await crm_assist.meter_earlier(
                session, tenant_id=tenant_id, earlier=spent.earlier, feature=feature
            )
            await crm_assist.meter_assist(
                session,
                tenant_id=tenant_id,
                ref=new_assist_ref(),
                result=spent,
                model=spent.model,
                feature=feature,
            )
    log.info(
        "holder_script_written",
        extra={
            **log_ids,
            "stored": stored,
            "repairs": trace.repairs,
            "checked_repairs": len(finished.repairs),
        },
    )
    return "ready" if stored else "not_pending"


__all__ = [
    "LINE_ASK",
    "campaign_change",
    "draft_campaign_script",
    "draft_line_script",
    "owners_words",
]
