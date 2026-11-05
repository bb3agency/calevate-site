"""Writes the script change Pip was asked for (D-820), from the outbox.

`agents/script_proposals.request_proposal` records the request and queues this job; the job
writes the proposal with `script_assist.draft_script` — the same call, prompt, repair and
ladder the Script page's own helper used — meters it, and stores it for review. It never
touches the draft and never puts anything live. An opening line the model wrote that breaks
the opening rule is repaired by the opening writer before it is stored (`opening_line`, D-957).

A job rather than a call inside Pip's answer: the draft is two model legs at most, which does
not belong inside the action's database transaction (D-748's reason for the improve job) nor
inside Pip's own answer budget.

SUBJECT → GATE → RUN → METER, `crm/resummarise.second_reading`'s order: the request is the subject;
the action's planner and executor ran the gate (`require_ai_assist`), and the ceiling is read
again here and passed to the ladder, which then answers on the platform's standby as every
dashboard assist does; each completed or refused paid leg is metered in its own transaction
under `ASSIST_FEATURE_SCRIPT_DRAFT`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript, unplaced_lines
from sqlalchemy import text

from apps.api.agents import script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run.documents import document_words, read_documents
from apps.api.kb.service import knowledge_agents
from apps.workers.extraction import TenantModelLeg
from apps.workers.first_run import documents_block
from apps.workers.opening_line import opening_problems, rewrite_problem, write_opening
from apps.workers.script_assist import (
    CONVERT_INSTRUCTION,
    JsonAnswer,
    ScriptBrief,
    ScriptDraft,
    draft_script,
)

log = get_logger(__name__)

JOB_NAME: Final = script_proposals.PROPOSAL_JOB


async def _claim(tenant_id: UUID, agent_id: UUID, proposal_id: UUID) -> bool:
    """Take the request once. The outbox delivers at least once, and a second delivery must
    not spend the allowance on a second draft of the same request."""
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE agents SET script_proposal = script_proposal || "
                    "jsonb_build_object('claimed', true) WHERE id = :aid "
                    "AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' "
                    "AND script_proposal->>'claimed' IS NULL RETURNING id"
                ),
                {"aid": agent_id, "pid": str(proposal_id)},
            )
        ).first()
    return claimed is not None


#: What a `knowledge` proposal asks of the edit (D-923): what onboarding's writer does with the
#: owner's documents (`first_run._write_script`), as a change to the script the owner already
#: has, so their own wording stays wherever the documents do not contradict it.
KNOWLEDGE_CHANGE: Final = (
    "The owner added the documents below to the business's knowledge. Work in what they tell "
    "callers and keep everything already in the script that they do not contradict: add or "
    "correct quick facts (the faqs list: a question callers ask and a short spoken answer, at "
    "most eight); update a step's instruction, an objection's answer or the opening line{calls} "
    "only where the documents change it; where a document contradicts the script, follow the "
    "document. Where a document says how the agent should handle the call (how to greet, "
    "what to ask first, what to do when the person is busy or stuck, how to guide them one "
    "step at a time), put that into the opening line, the steps and the objections, "
    "in the business's own words. Leave every other field exactly as it is."
)


def knowledge_change(documents: str, *, both: bool) -> str:
    """The change a `knowledge` proposal is written from: the ask, then the redacted block."""
    calls = " and the opening line when it calls" if both else ""
    return f"{KNOWLEDGE_CHANGE.format(calls=calls)}\n{documents}"


async def _documents(tenant_id: UUID, proposal: script_proposals.ScriptProposal) -> str:
    """The proposal's documents as onboarding's writer reads them (`first_run.documents_block`:
    redacted, fenced, one shared word budget), whether or not a PDF's words reach the agents
    on calls, as at onboarding. A document removed since is left out."""
    async with tenant_session(tenant_id) as session:
        found = await read_documents(session, proposal.documents)
        words = [
            (doc.name, await document_words(session, doc.upload_id))
            for doc in found
            if doc.state == "read"
        ]
    return documents_block(words)


async def _introduced_opening(
    context: ScriptBrief,
    base: CallScript,
    tenant_leg: TenantModelLeg | None,
    *,
    quota_exhausted: bool,
) -> ScriptDraft:
    """`base` with its opening line written again to be said after the agent's own
    introduction (D-865): no greeting, no name of the agent or the business. Asked when the AI
    notice, which introduces the agent, is switched on over an opening that already does
    (`publishing.OPENING_INTRODUCES_CODE`). The notice is still off while this is written, so
    the brief is told it introduces."""
    brief = replace(context, introduced=True)
    line = base.opening_line.strip()
    names = (brief.business_name, brief.agent_name)
    answer = await write_opening(
        brief,
        line=line,
        problems=opening_problems(line, brief.language, names=names, introduced=True),
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
    )
    return ScriptDraft(
        script=base.model_copy(update={"opening_line": answer.value}),
        capability=answer.capability,
        usage=answer.usage,
        model=answer.model,
        earlier=answer.earlier,
    )


def _written_problems(line: str, field: str, brief: ScriptBrief) -> list[str]:
    """What a `written` proposal asks of a line: written fresh when there is none, else
    written again with the rules it breaks (`opening_problems`) and `rewrite_problem`."""
    if not line:
        return []
    names = (brief.business_name, brief.agent_name)
    return [
        *opening_problems(
            line,
            brief.language,
            names=names,
            introduced=brief.introduced,
            where=field,
            woven=brief.woven,
        ),
        rewrite_problem(field),
    ]


async def _written_opening(
    context: ScriptBrief,
    base: CallScript,
    tenant_leg: TenantModelLeg | None,
    *,
    quota_exhausted: bool,
) -> ScriptDraft:
    """`base` with the opening callers who ring hear written for this business in the agent's
    main language (D-965). A "both" agent's opening for the calls it places is written after
    it by `_opening_repaired`, so each line's spend is metered on its own."""
    line = base.opening_line.strip()
    answer = await write_opening(
        context,
        line=line,
        problems=_written_problems(line, "opening_line", context),
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
    )
    return ScriptDraft(
        script=base.model_copy(update={"opening_line": answer.value}),
        capability=answer.capability,
        usage=answer.usage,
        model=answer.model,
        earlier=answer.earlier,
    )


async def _draft(
    tenant_id: UUID, agent_id: UUID, proposal: script_proposals.ScriptProposal
) -> ScriptDraft:
    async with tenant_session(tenant_id) as session:
        context = await script_proposals.brief_for(session, tenant_id, agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    exhausted = quota.at_ceiling or quota.platform_paused
    base = proposal.base_script
    if proposal.mode == script_proposals.OPENING_MODE:
        return await _introduced_opening(context, base, tenant_leg, quota_exhausted=exhausted)
    if proposal.mode == script_proposals.WRITTEN_MODE:
        return await _written_opening(context, base, tenant_leg, quota_exhausted=exhausted)
    if proposal.mode == "steps":
        # The brief the conversion has always used: the hand-written text and the three
        # facts that decide its register, nothing else.
        brief = ScriptBrief(
            description=f"Convert this hand-written prompt:\n{base.raw_override or ''}",
            business_type=context.business_type,
            direction=context.direction,
            language=context.language,
        )
        return await draft_script(
            brief, tenant_leg=tenant_leg, quota_exhausted=exhausted, instruction=CONVERT_INSTRUCTION
        )
    if proposal.mode == script_proposals.STARTER_MODE:
        drafted = await draft_script(context, tenant_leg=tenant_leg, quota_exhausted=exhausted)
        # An opening already on the agent was typed by the owner at creation: theirs, kept.
        kept = {
            field: line
            for field, _placed in _OPENINGS
            if (line := str(getattr(base, field)).strip())
        }
        if not kept:
            return drafted
        return replace(drafted, script=drafted.script.model_copy(update=kept))
    if proposal.mode == "whole":
        return await draft_script(
            replace(context, answers=tuple(proposal.answers.items())),
            tenant_leg=tenant_leg,
            quota_exhausted=exhausted,
        )
    if proposal.mode == script_proposals.KNOWLEDGE_MODE:
        documents = await _documents(tenant_id, proposal)
        if not documents:
            raise ProblemError.conflict(
                "knowledge_proposal_no_words",
                "Your new document has no words we could read.",
                remediation="Check it on the Knowledge page, then add it again.",
            )
        return await draft_script(
            context,
            tenant_leg=tenant_leg,
            quota_exhausted=exhausted,
            edit_of=base,
            change=knowledge_change(documents, both=context.direction == "both"),
        )
    return await draft_script(
        context,
        tenant_leg=tenant_leg,
        quota_exhausted=exhausted,
        edit_of=base,
        change=proposal.request or "",
    )


#: The lines the engine speaks first, each with whether it opens the calls a "both" agent
#: places (D-920). Both are held to one rule and repaired the same way (D-957, D-959).
_OPENINGS: Final = (("opening_line", False), ("outbound_opening_line", True))


def openings_kept(script: CallScript, base: CallScript) -> CallScript:
    """`script` with any opening line the model left blank put back from `base`.

    A blank opening is never a fix: the agent would open the call with nothing, and the
    judging below skips a blank line, so without this a suggestion that dropped the opening
    ("Fix them first" on Put it live) replaced the owner's line with nothing."""
    restored = {
        field: kept
        for field, _placed in _OPENINGS
        if not str(getattr(script, field)).strip() and (kept := str(getattr(base, field)).strip())
    }
    return script.model_copy(update=restored) if restored else script


async def _opening_repaired(
    tenant_id: UUID, agent_id: UUID, proposal: script_proposals.ScriptProposal, script: CallScript
) -> tuple[CallScript, list[JsonAnswer[str] | ProblemError]]:
    """The proposal's script with each opening line the model wrote that breaks the opening
    rule repaired by the opening writer, as onboarding's are (`first_run._write_greeting`,
    `first_run._write_placed_opening`), and what the repairs spent. A conversion keeps the
    owner's sentences, and a line the owner already had or asked for in their own words is
    theirs: neither is judged. A repair that gives no line leaves the proposal as drafted, for
    the owner to review. A `written` proposal (D-965) has a "both" agent's opening for the
    calls it places written here, whatever it held."""
    written = proposal.mode == script_proposals.WRITTEN_MODE
    if not written:
        script = openings_kept(script, proposal.base_script)
    if proposal.mode in ("steps", script_proposals.OPENING_MODE):
        return script, []
    owners = " ".join([proposal.request or "", *proposal.answers.values()])
    judged = [
        (field, placed, line)
        for field, placed in _OPENINGS
        if (line := str(getattr(script, field)).strip())
        and line != str(getattr(proposal.base_script, field)).strip()
        and line not in owners
    ]
    if not judged and not written:
        return script, []
    async with tenant_session(tenant_id) as session:
        context = await script_proposals.brief_for(session, tenant_id, agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    if written:
        placed_line = script.outbound_opening_line.strip()
        both = context.direction == "both"
        judged = [("outbound_opening_line", True, placed_line)] if both else []
    spends: list[JsonAnswer[str] | ProblemError] = []
    for field, placed, line in judged:
        problems = (
            _written_problems(line, field, context)
            if written
            else opening_problems(
                line,
                context.language,
                names=(context.business_name, context.agent_name),
                introduced=context.introduced,
                woven=context.woven,
            )
        )
        if line and not problems:
            continue
        try:
            answer = await write_opening(
                replace(context, answers=tuple(proposal.answers.items())),
                line=line,
                problems=problems,
                tenant_leg=tenant_leg,
                quota_exhausted=quota.at_ceiling or quota.platform_paused,
                placed=placed,
            )
        except ProblemError as refused:
            log.info(
                "script_proposal_opening_unrepaired",
                extra={"reason": refused.code, "field": field},
            )
            spends.append(refused)
            continue
        spends.append(answer)
        script = script.model_copy(update={field: answer.value})
    return script, spends


async def _fail(tenant_id: UUID, agent_id: UUID, proposal_id: UUID, note: str) -> None:
    async with tenant_session(tenant_id) as session:
        await script_proposals.store_failed(
            session, agent_id=agent_id, proposal_id=proposal_id, note=note
        )


async def draft_script_proposal(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    proposal_id = UUID(str(payload["proposal_id"]))
    if not await _claim(tenant_id, agent_id, proposal_id):
        # Discarded, replaced, or already taken by an earlier delivery.
        return "not_pending"
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
    if proposal is None or proposal.id != proposal_id:
        return "not_pending"

    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    try:
        draft = await _draft(tenant_id, agent_id, proposal)
    except ProblemError as refused:
        log.info(
            "script_proposal_refused", extra={"agent_id": str(agent_id), "reason": refused.code}
        )
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        # The refusal's own sentences: written for the person, the same ones the Script
        # page's helper showed.
        note = " ".join(p for p in (refused.detail, refused.remediation) if p)
        await _fail(tenant_id, agent_id, proposal_id, note or script_proposals.FAILED_NOTE)
        return "refused"
    except Exception:
        # The Script page waits on this proposal until it is ready or failed, so a crash is
        # written down for the owner as well as logged for us.
        log.exception("script_proposal_crashed", extra={"agent_id": str(agent_id)})
        await _fail(tenant_id, agent_id, proposal_id, script_proposals.FAILED_NOTE)
        return "failed"

    try:
        script, opening_spends = await _opening_repaired(
            tenant_id, agent_id, proposal, draft.script
        )
    except Exception:
        # The draft is already paid for: a failure in the optional opening repair must not
        # lose its meter row (hard rule 7) nor leave the request `drafting` until it goes
        # stale. The proposal is stored as drafted, for the owner to review.
        log.exception("script_proposal_opening_crashed", extra={"agent_id": str(agent_id)})
        script, opening_spends = draft.script, []
    unplaced = (
        unplaced_lines(proposal.base_script.raw_override or "", draft.script)
        if proposal.mode == "steps"
        else []
    )
    # A completed run is money spent, recorded in the transaction that stores the proposal:
    # committed first, a store that failed left the account paying for a proposal it never
    # got (the retry finds the claim spent).
    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.store_ready(
            session,
            agent_id=agent_id,
            proposal_id=proposal_id,
            script=script,
            unplaced=unplaced,
            disclosure=draft.capability.disclosure,
        )
        applied = (
            stored
            and proposal.mode == script_proposals.STARTER_MODE
            and await script_proposals.apply_untouched_starter(
                session, tenant_id=tenant_id, agent_id=agent_id, proposal=proposal, script=script
            )
        )
        spends: list[ScriptDraft | JsonAnswer[str] | ProblemError | None] = [
            draft,
            *opening_spends,
        ]
        for spent in spends:
            if spent is None:
                continue
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
        "script_proposal_written",
        extra={
            "agent_id": str(agent_id),
            "mode": proposal.mode,
            "stored": stored,
            "applied": applied,
        },
    )
    if applied:
        return "applied"
    return "ready" if stored else "not_pending"


async def suggest_scripts_from_document(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """A file added to the knowledge after onboarding, live: a `knowledge` proposal for every
    agent of the client (D-923), so it shapes their scripts as an onboarding document shapes
    the first agent's, for the owner to keep or dismiss. Queued once per upload by
    `kb_ingest.ingest_kb_source` once it is published.

    Not for an onboarding document (`first_runs.document_ids`): its words already wrote the
    first script. Not for a web page: onboarding takes files only."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    upload_id = UUID(str(payload["upload_id"]))
    async with tenant_session(tenant_id) as session:
        onboarding = (
            await session.execute(
                text("SELECT 1 FROM first_runs WHERE :uid = ANY(document_ids)"),
                {"uid": upload_id},
            )
        ).first()
        if onboarding is not None:
            return "onboarding_document"
        found = await read_documents(session, [upload_id])
        agents = await knowledge_agents(session, tenant_id=tenant_id)
    if not found or found[0].source_kind == "url":
        return "not_a_file"
    document = found[0]
    if document.state != "read":
        return "no_words"
    suggested = 0
    for agent_id in agents:
        # One transaction per agent, so one agent's refusal never costs the others theirs.
        async with tenant_session(tenant_id) as session:
            made = await script_proposals.request_knowledge_proposal(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                upload_ids=[upload_id],
                names=[document.name],
            )
        suggested += made is not None
    log.info(
        "knowledge_script_suggestions_queued",
        extra={"upload_id": str(upload_id), "agents": len(agents), "suggested": suggested},
    )
    return f"suggested:{suggested}"


__all__ = [
    "JOB_NAME",
    "KNOWLEDGE_CHANGE",
    "draft_script_proposal",
    "knowledge_change",
    "suggest_scripts_from_document",
]
