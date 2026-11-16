"""The first run on the new model (Phase 3b of docs/design/CAMPAIGN-WORKER-PLAN.md).

Founder, 16 Nov 2026: the business and its work are the centre, and an agent is staff, a name,
a voice and settings, with no script of its own. So the first run no longer builds an agent
from a written script. After "About your business":

1. **Name and voice** (`save_agent`): the agent is made with the default agent's name
   (`agents/default_agent`), its voice and its languages, and nothing else. Its AI notice is
   switched on by a job, as the build's last step did for the agent it made (D-864). The
   company training is drafted from the owner's words and saved at once as version 1
   (`_queue_training`), with no review.
2. **What first?** (`start_work`): "Answer my calls" drafts an inbound line in the agent's
   voice, with no number needed; "Call people" drafts a campaign. Either one's script is
   written by Pip from the owner's words and documents and saved at once (`auto_save`), so
   the test call has something to say.

The test call then rings the draft's own engine agent: a line's test holder
(`POST /v1/inbound-lines/{id}/test-call`) or the campaign's test call.

An owner who finished or put aside the first run before this release is never sent here
again (`service.due_for`), so nothing here touches their account.
"""

from __future__ import annotations

import json
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import company_training
from apps.api.agents.languages import published_extra_languages
from apps.api.agents.lifecycle import create_agent, update_agent
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.first_run.documents import read_documents
from apps.api.first_run.service import NOTICE_JOB, RunState, ensure_run, read_state
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

FirstWork = Literal["answer_calls", "call_leads"]
FIRST_WORKS: Final[tuple[FirstWork, ...]] = ("answer_calls", "call_leads")

#: What Pip writes from when the owner gave only files, not words: the work's own purpose.
DEFAULT_TASK: Final[dict[FirstWork, str]] = {
    "answer_calls": (
        "Answer people who call the business: help with what they ask, and note what each "
        "caller needs and how to reach them."
    ),
    "call_leads": (
        "Call people who asked to hear from the business: say why you are calling, answer "
        "their questions, and find out who is interested."
    ),
}
#: The first campaign's name; the owner renames it on its page.
FIRST_CAMPAIGN_NAME: Final = "Your first calls"
#: The new-campaign form's own default (`campaigns/routes.CreateCampaignIn.concurrency`).
FIRST_CAMPAIGN_CONCURRENCY: Final = 3


def _no_agent() -> ProblemError:
    return ProblemError.business_rule(
        "first_run_no_agent",
        "Your agent has no name yet.",
        remediation="Go back one step and give it a name.",
    )


async def agent_status(session: AsyncSession, agent_id: UUID | None) -> str | None:
    if agent_id is None:
        return None
    value = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).scalar()
    return None if value is None or str(value) == "archived" else str(value)


async def save_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    language_primary: str,
    languages_extra: list[str],
    voice: dict[str, object] | None,
    user_id: UUID | None,
    may_spend_ai: bool,
) -> RunState:
    """Make the first agent, or rename it and change its languages before its first call.

    `voice` is the voice picked for a NEW agent (`{"voice_id", "label", "rung", "fallback",
    "not_female"}`, from the default agent or `voice_pick`); an agent already made keeps its
    voice, which the owner changes with the voice picker. Refused once the agent is set up
    for calls: a rename then belongs on its own page, where putting it live is shown."""
    row = await ensure_run(session, tenant_id=tenant_id)
    clean = " ".join(name.split())
    extra = published_extra_languages(language_primary, languages_extra)
    status = await agent_status(session, row.agent_id)
    if status is not None and status != "draft":
        raise ProblemError.conflict(
            "first_run_rename_after_ready",
            "Your agent is already set up for calls.",
            remediation="Change its name or languages on its own page.",
        )
    if status is None:
        agent_id = await create_agent(
            session,
            tenant_id=tenant_id,
            name=clean,
            # Answering is what a new agent does until "What first?" says otherwise.
            direction="inbound",
            language_primary=language_primary,
            languages_extra=extra,
            created_by=user_id,
        )
        voice_state: dict[str, object] = {"state": "none"}
        voice = voice or {}
        voice_id = voice.get("voice_id")
        if isinstance(voice_id, str) and voice_id:
            try:
                async with session.begin_nested():
                    await update_agent(
                        session,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        engine_voice_id=voice_id,
                        set_engine_voice_id=True,
                    )
                voice_state = {"state": "done", **{k: v for k, v in voice.items() if k != "voice_id"}}
            except ProblemError as refused:
                log.info("first_run_voice_refused", extra={"reason": refused.code})
        await enqueue_outbox(
            session,
            job=NOTICE_JOB,
            payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
        )
        await session.execute(
            text(
                "UPDATE first_runs SET agent_id = :aid, language_primary = :lang, "
                "languages_extra = :extra, "
                "build_steps = jsonb_build_object('voice', CAST(:voice AS jsonb)), "
                "updated_at = now() WHERE id = :id"
            ),
            {
                "aid": agent_id,
                "lang": language_primary,
                "extra": extra,
                "voice": json.dumps(voice_state),
                "id": row.id,
            },
        )
    else:
        assert row.agent_id is not None
        await update_agent(
            session,
            tenant_id=tenant_id,
            agent_id=row.agent_id,
            name=clean,
            language_primary=language_primary,
            languages_extra=extra,
        )
        await session.execute(
            text(
                "UPDATE first_runs SET language_primary = :lang, languages_extra = :extra, "
                "updated_at = now() WHERE id = :id"
            ),
            {"lang": language_primary, "extra": extra, "id": row.id},
        )
    if may_spend_ai:
        await _queue_training(session, tenant_id=tenant_id, user_id=user_id)
    return await read_state(session, tenant_id=tenant_id)


async def _queue_training(session: AsyncSession, *, tenant_id: UUID, user_id: UUID | None) -> None:
    """Pip drafts the company training from the owner's words, saved at once as version 1
    (founder, 16 Nov 2026). Only while none is saved and none is being written, and only
    within the account's AI allowance: without it the owner writes it under How they speak."""
    training = await company_training.read_training(session, tenant_id)
    if training.version > 0 or not training.overview.strip():
        return
    if training.proposal is not None and training.proposal.status in ("drafting", "ready"):
        return
    quota = await read_ai_quota(session, tenant_id=tenant_id)
    if quota.at_ceiling or quota.platform_paused:
        return
    await company_training.request_proposal(
        session, tenant_id=tenant_id, requested_by=user_id, auto_save=True
    )


async def start_work(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job: FirstWork,
    user_id: UUID | None,
    may_spend_ai: bool,
) -> RunState:
    """Draft the owner's first work for the agent and have Pip write its script.

    A second press for the same work returns what was drafted; choosing the other card
    drafts that one too, so going back never loses a script already written. The agent
    takes the work's direction while it is still a draft (an answering line or a campaign
    that places calls), which decides how its test call opens."""
    from apps.api.campaigns import service as campaigns_service
    from apps.api.campaigns import workspace
    from apps.api.inbound import lines

    row = await ensure_run(session, tenant_id=tenant_id)
    status = await agent_status(session, row.agent_id)
    if status is None or row.agent_id is None:
        raise _no_agent()
    agent_id = UUID(str(row.agent_id))
    task = (row.brief or "").strip() or DEFAULT_TASK[job]
    documents = [
        d for d in await read_documents(session, list(row.document_ids or [])) if d.state == "read"
    ]
    if status == "draft":
        await update_agent(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            direction="inbound" if job == "answer_calls" else "outbound",
        )
    if job == "answer_calls" and row.line_id is None:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, main_task=task, created_by=user_id
        )
        sources = await _source_ids(session, [d.upload_id for d in documents])
        if sources:
            await lines.set_sources(
                session,
                tenant_id=tenant_id,
                line_id=line_id,
                kb_source_ids=sources,
                created_by=user_id,
            )
        if may_spend_ai:
            await lines.request_proposal(
                session,
                tenant_id=tenant_id,
                line_id=line_id,
                requested_by=user_id,
                auto_save=True,
            )
        await session.execute(
            text("UPDATE first_runs SET line_id = :lid WHERE id = :id"),
            {"lid": line_id, "id": row.id},
        )
    elif job == "call_leads" and row.campaign_id is None:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=FIRST_CAMPAIGN_NAME,
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=FIRST_CAMPAIGN_CONCURRENCY,
        )
        await workspace.save_main_task(session, campaign_id, task)
        for document in documents:
            await workspace.add_material(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                kind="file",
                title=document.name,
                url=None,
                note=None,
                kb_upload_id=document.upload_id,
                created_by=user_id,
            )
        if may_spend_ai:
            await workspace.request_proposal(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                requested_by=user_id,
                auto_save=True,
            )
        await session.execute(
            text("UPDATE first_runs SET campaign_id = :cid WHERE id = :id"),
            {"cid": campaign_id, "id": row.id},
        )
    await session.execute(
        text("UPDATE first_runs SET jobs = ARRAY[CAST(:job AS text)], updated_at = now() WHERE id = :id"),
        {"job": job, "id": row.id},
    )
    return await read_state(session, tenant_id=tenant_id)


async def _source_ids(session: AsyncSession, upload_ids: list[UUID]) -> list[UUID]:
    """The knowledge sources behind the run's documents, which a line is written from."""
    if not upload_ids:
        return []
    rows = await session.execute(
        text("SELECT source_id FROM kb_uploads WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": [str(i) for i in upload_ids]},
    )
    return [UUID(str(r[0])) for r in rows.all()]


__all__ = [
    "DEFAULT_TASK",
    "FIRST_CAMPAIGN_NAME",
    "FIRST_WORKS",
    "FirstWork",
    "save_agent",
    "start_work",
]
