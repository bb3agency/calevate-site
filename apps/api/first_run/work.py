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
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import company_training
from apps.api.agents.languages import published_extra_languages
from apps.api.agents.lifecycle import create_agent, update_agent
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.first_run.documents import read_documents
from apps.api.first_run.names import identity_with_name
from apps.api.first_run.service import RunState, ensure_run, live_work_ids, read_state
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.business_copy import queue_generation

log = get_logger(__name__)

FirstWork = Literal["answer_calls", "call_leads"]
FIRST_WORKS: Final[tuple[FirstWork, ...]] = ("answer_calls", "call_leads")

#: The first agent's AI notice switched on (`workers/first_run.switch_on_first_notice`).
NOTICE_JOB: Final = "switch_on_first_notice"

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
                voice_state = {
                    "state": "done",
                    **{k: v for k, v in voice.items() if k != "voice_id"},
                }
            except ProblemError as refused:
                log.info("first_run_voice_refused", extra={"reason": refused.code})
        await enqueue_outbox(
            session,
            job=NOTICE_JOB,
            payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
        )
        if may_spend_ai and (row.brief or "").strip():
            # The business's examples written again from the owner's own words, once, when its
            # first agent is made: the signup run had only the business type and name. The
            # run checks the allowance itself and keeps the examples it has when spent.
            await queue_generation(session, tenant_id=tenant_id, trigger="first_run")
        # A run that had an agent before (deleted since) forgets that agent's draft work too:
        # "What first?" would otherwise hand back a line or campaign of the archived agent,
        # whose test call cannot ring.
        await session.execute(
            text(
                "UPDATE first_runs SET agent_id = :aid, language_primary = :lang, "
                "languages_extra = :extra, "
                "build_steps = jsonb_build_object('voice', CAST(:voice AS jsonb)), "
                "line_id = NULL, campaign_id = NULL, jobs = '{}', "
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
        before = (
            await session.execute(
                text("SELECT name FROM agents WHERE id = :aid"), {"aid": row.agent_id}
            )
        ).scalar_one()
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
        if clean != before:
            await _rename_in_work(session, row=row, name=clean)
    if may_spend_ai:
        await _queue_training(session, tenant_id=tenant_id, user_id=user_id)
    return await read_state(session, tenant_id=tenant_id)


async def _rename_in_work(session: AsyncSession, *, row: Any, name: str) -> None:
    """The run's line and campaign scripts give the agent's new name. Their identity was
    written with the old one (`save_ready_made`, Pip's draft), and the call's opening already
    introduces the agent by its current name, so without this a renamed agent says one name
    and answers "who is this?" with the other."""
    from apps.api.campaigns import workspace
    from apps.api.inbound import lines

    def renamed(script: CallScript | None) -> CallScript | None:
        # A version 1 script has no identity section to carry the name.
        if script is None or script.schema_version < 2:
            return None
        return script.model_copy(update={"identity": identity_with_name(script.identity, name)})

    line_id, campaign_id = await live_work_ids(session, row)
    if line_id is not None:
        line_script = renamed((await lines.read_line(session, line_id)).script)
        if line_script is not None:
            await lines.save_script(session, line_id, line_script)
    if campaign_id is not None:
        campaign_script = renamed((await workspace.read_workspace(session, campaign_id)).script)
        if campaign_script is not None:
            await workspace.save_script(session, campaign_id, campaign_script)


async def _within_ai_allowance(session: AsyncSession, tenant_id: UUID) -> bool:
    quota = await read_ai_quota(session, tenant_id=tenant_id)
    return not (quota.at_ceiling or quota.platform_paused)


async def _queue_training(session: AsyncSession, *, tenant_id: UUID, user_id: UUID | None) -> None:
    """Pip drafts the company training from the owner's words, saved at once as version 1
    (founder, 16 Nov 2026). Only while none is saved and none is being written, and only
    within the account's AI allowance: without it the owner writes it under How they speak."""
    training = await company_training.read_training(session, tenant_id)
    if training.version > 0 or not training.overview.strip():
        return
    if training.proposal is not None and training.proposal.status in ("drafting", "ready"):
        return
    if not await _within_ai_allowance(session, tenant_id):
        return
    await company_training.request_proposal(
        session, tenant_id=tenant_id, requested_by=user_id, auto_save=True
    )


#: What leads the owner's answers in the work's main task.
ANSWERS_LEAD: Final = "The owner also said:"


def main_task_of(row: Any, job: FirstWork) -> str:
    """The first work's main task: the owner's words, then their answers to the follow-up
    questions that name no business-profile section, the one thing every caller should know
    among them (D-945). An answer that names a section is in the business profile already,
    which every agent reads; these have nowhere else to go, and the main task is what Pip
    writes the line's or campaign's script from, and what the owner edits on its page. The
    answers are kept whole; the words before them are cut to fit."""
    from apps.api.campaigns.workspace import MAIN_TASK_MAX
    from apps.api.first_run.service import answers_for_script

    words = (row.brief or "").strip() or DEFAULT_TASK[job]
    unmapped = [a for a in row.answers or [] if isinstance(a, dict) and not a.get("maps_to")]
    said = answers_for_script(unmapped)
    if not said:
        return words[:MAIN_TASK_MAX]
    tail = f"\n\n{ANSWERS_LEAD}\n{said}"[:MAIN_TASK_MAX]
    return f"{words[: max(0, MAIN_TASK_MAX - len(tail))].rstrip()}{tail}".strip()


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
    task = main_task_of(row, job)
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
    pip_writes = may_spend_ai and await _within_ai_allowance(session, tenant_id)
    # An archived line or campaign reads as none, so this drafts another one.
    held_line, held_campaign = await live_work_ids(session, row)
    if job == "answer_calls" and held_line is None:
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
        await session.execute(
            text("UPDATE first_runs SET line_id = :lid WHERE id = :id"),
            {"lid": line_id, "id": row.id},
        )
        if pip_writes:
            await lines.request_proposal(
                session,
                tenant_id=tenant_id,
                line_id=line_id,
                requested_by=user_id,
                auto_save=True,
            )
        else:
            await save_ready_made(session, tenant_id=tenant_id, line_id=line_id)
    elif job == "call_leads" and held_campaign is None:
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
        sources = await _source_ids(session, [d.upload_id for d in documents])
        if sources:
            await workspace.set_sources(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                kb_source_ids=sources,
                created_by=user_id,
            )
        await session.execute(
            text("UPDATE first_runs SET campaign_id = :cid WHERE id = :id"),
            {"cid": campaign_id, "id": row.id},
        )
        if pip_writes:
            await workspace.request_proposal(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                requested_by=user_id,
                auto_save=True,
            )
        else:
            await save_ready_made(session, tenant_id=tenant_id, campaign_id=campaign_id)
    await session.execute(
        text(
            "UPDATE first_runs SET jobs = ARRAY[CAST(:job AS text)], updated_at = now() "
            "WHERE id = :id"
        ),
        {"job": job, "id": row.id},
    )
    return await read_state(session, tenant_id=tenant_id)


#: The run's `script` step when its work got the ready-made script because Pip could not
#: write one; the screen says so, and points at where to change it.
READY_MADE: Final = "ready_made"


async def save_ready_made(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> bool:
    """Give the first run's line or campaign the ready-made script for its job, while it has
    no script: Pip was not asked (no AI allowance left, or a view-as session) or could not
    write it. Without this the work has nothing to say and the first run cannot reach its
    test call, which the build it replaced never allowed: it fell back to the same starter.
    The script is the trade's own, fitted to the business, named for its agent, and saved
    through the holder's own save. True when saved."""
    from apps.api.agents.starters import StarterJob, ready_made_script
    from apps.api.campaigns import workspace
    from apps.api.inbound import lines

    job: StarterJob
    if (line_id is None) == (campaign_id is None):
        raise ValueError("a line or a campaign, not both")
    if line_id is not None:
        line = await lines.read_line(session, line_id)
        agent_id, current, job = line.agent_id, line.script, "answer_calls"
    else:
        assert campaign_id is not None
        space = await workspace.read_workspace(session, campaign_id)
        agent_id, current, job = space.agent_id, space.script, "call_leads"
    if current is not None:
        return False
    agent = (
        await session.execute(
            text(
                "SELECT a.name, a.language_primary, o.name AS business, o.vertical_template "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id WHERE a.id = :aid"
            ),
            {"aid": agent_id},
        )
    ).one()
    script = await ready_made_script(
        session,
        tenant_id=tenant_id,
        job=job,
        vertical_template=agent.vertical_template,
        business=str(agent.business),
        language=str(agent.language_primary),
    )
    script = script.model_copy(
        update={"identity": identity_with_name(script.identity, str(agent.name))}
    )
    if line_id is not None:
        await lines.save_script(session, line_id, script)
    else:
        assert campaign_id is not None
        await workspace.save_script(session, campaign_id, script)
    await session.execute(
        text(
            "UPDATE first_runs SET build_steps = build_steps || "
            "jsonb_build_object('script', jsonb_build_object('state', CAST(:state AS text))), "
            "updated_at = now() WHERE line_id = :hid OR campaign_id = :hid"
        ),
        {"state": READY_MADE, "hid": line_id or campaign_id},
    )
    return True


async def _source_ids(session: AsyncSession, upload_ids: list[UUID]) -> list[UUID]:
    """The knowledge sources behind the run's documents, which its line or campaign is
    written from."""
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
    "NOTICE_JOB",
    "READY_MADE",
    "FirstWork",
    "save_agent",
    "save_ready_made",
    "start_work",
]
