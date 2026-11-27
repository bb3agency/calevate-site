"""The first run on the new model (Phase 3b of docs/design/CAMPAIGN-WORKER-PLAN.md).

Founder, 16 Nov 2026: the business and its work are the centre, and an agent is staff, a name,
a voice and settings, with no script of its own. So the first run no longer builds an agent
from a written script. After "About your business":

1. **Name and voice** (`save_agent`): the agent is made with the default agent's name
   (`agents/default_agent`), its voice and its languages, and nothing else. Its AI notice is
   switched on by a job, as the build's last step did for the agent it made (D-864). Making
   it queues Pip's company training in the background (`lifecycle.create_agent`, D-1034).
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
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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

if TYPE_CHECKING:
    from apps.api.campaigns.script_history import HolderKind

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
#: Why the first run saved a script, shown in its Versions list (`campaigns/script_history`).
READY_MADE_REASON: Final = "The ready-made script for this job."
RENAMED_REASON: Final = "The agent's new name was put in the script."


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
                text("SELECT name, language_primary FROM agents WHERE id = :aid"),
                {"aid": row.agent_id},
            )
        ).one()
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
        if clean != before.name:
            await _rename_in_work(session, row=row, name=clean)
        if language_primary != before.language_primary:
            await _rewrite_in_language(
                session,
                tenant_id=tenant_id,
                row=row,
                language=language_primary,
                user_id=user_id,
                may_spend_ai=may_spend_ai,
            )
    return await read_state(session, tenant_id=tenant_id)


#: Whether the owner ever touched a holder's script, and whether the first run's ready-made
#: script was saved to it. One literal statement per holder table.
_HISTORY_SQL: Final[dict[str, str]] = {
    "line": (
        "SELECT coalesce(bool_or(owner_made OR author = ANY(:owner)), false) AS touched, "
        "coalesce(bool_or(reason = :ready), false) AS ready_made "
        "FROM script_versions WHERE inbound_line_id = :h"
    ),
    "campaign": (
        "SELECT coalesce(bool_or(owner_made OR author = ANY(:owner)), false) AS touched, "
        "coalesce(bool_or(reason = :ready), false) AS ready_made "
        "FROM script_versions WHERE campaign_id = :h"
    ),
}
#: The owner's own acts on a script (`campaigns/script_history._OWNER_ACTIONS`).
_OWNER_ACTS: Final = ("owner", "restored", "copied")


async def _rewrite_in_language(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    row: Any,
    language: str,
    user_id: UUID | None,
    may_spend_ai: bool,
) -> None:
    """The run's line and campaign speak the agent's new main language. The job is posted
    as soon as the agent is made, so its script is usually written (or being written) in the
    language the owner first picked; changing it on Name and voice afterwards used to leave
    that script in the old language.

    Per holder, by who wrote what it holds:
    * a first draft still being written is stopped and asked again, because a job already
      running read the old language (the writer reads its context when it runs, D-1031);
    * a script Pip wrote and the owner never touched is rewritten whole, as the rules
      rewrite is (`ask.rewrite`, `workers/campaign_script._save_if_rewrite`), which saves
      it only while it is still the one it was written from;
    * the ready-made script, saved when Pip could not write, is saved again in the new
      language;
    * a script the owner edited is theirs, and is left in their words."""
    from apps.api.campaigns import workspace
    from apps.api.campaigns.script_history import pip_owns
    from apps.api.inbound import lines

    pip_writes = may_spend_ai and await _within_ai_allowance(session, tenant_id)
    line_id, campaign_id = await live_work_ids(session, row)
    holders: tuple[tuple[HolderKind, UUID | None], ...] = (
        ("line", line_id),
        ("campaign", campaign_id),
    )
    for kind, holder_id in holders:
        if holder_id is None:
            continue
        if kind == "line":
            line = await lines.read_line(session, holder_id)
            script, proposal = line.script, line.proposal
        else:
            space = await workspace.read_workspace(session, holder_id)
            script, proposal = space.script, space.proposal
        drafting = proposal is not None and proposal.status == "drafting"
        try:
            async with session.begin_nested():
                if script is None:
                    if drafting and pip_writes:
                        assert proposal is not None
                        if kind == "line":
                            await lines.clear_proposal(session, holder_id, proposal.id)
                        else:
                            await workspace.clear_proposal(session, holder_id, proposal.id)
                        await _ask_pip(
                            session,
                            kind,
                            holder_id,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            auto_save=True,
                        )
                    continue
                history = (
                    await session.execute(
                        text(_HISTORY_SQL[kind]),
                        {"h": holder_id, "owner": list(_OWNER_ACTS), "ready": READY_MADE_REASON},
                    )
                ).one()
                if history.touched:
                    continue
                if await pip_owns(session, kind, holder_id):
                    if pip_writes and not drafting:
                        await _ask_pip(
                            session,
                            kind,
                            holder_id,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            ask={"rewrite": f"language:{language}"},
                        )
                elif history.ready_made:
                    await save_ready_made(
                        session,
                        tenant_id=tenant_id,
                        line_id=holder_id if kind == "line" else None,
                        campaign_id=holder_id if kind == "campaign" else None,
                        replace=True,
                    )
        except ProblemError as refused:
            # The old script stays; the owner can still ask Pip on the work's own page.
            log.info(
                "first_run_language_rewrite_not_asked",
                extra={"kind": kind, "holder_id": str(holder_id), "reason": refused.code},
            )


async def _ask_pip(
    session: AsyncSession,
    kind: HolderKind,
    holder_id: UUID,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    auto_save: bool = False,
    ask: dict[str, str] | None = None,
) -> None:
    """Pip's draft for one holder, through the holder's own request (metered as every draft)."""
    from apps.api.campaigns import workspace
    from apps.api.inbound import lines

    if kind == "line":
        await lines.request_proposal(
            session,
            tenant_id=tenant_id,
            line_id=holder_id,
            requested_by=user_id,
            auto_save=auto_save,
            ask=ask,
        )
    else:
        await workspace.request_proposal(
            session,
            tenant_id=tenant_id,
            campaign_id=holder_id,
            requested_by=user_id,
            auto_save=auto_save,
            ask=ask,
        )


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
            await lines.save_script(
                session, line_id, line_script, author="system", reason=RENAMED_REASON
            )
    if campaign_id is not None:
        campaign_script = renamed((await workspace.read_workspace(session, campaign_id)).script)
        if campaign_script is not None:
            await workspace.save_script(
                session, campaign_id, campaign_script, author="system", reason=RENAMED_REASON
            )


async def _within_ai_allowance(session: AsyncSession, tenant_id: UUID) -> bool:
    quota = await read_ai_quota(session, tenant_id=tenant_id)
    return not (quota.at_ceiling or quota.platform_paused)


#: What leads the owner's answers in the work's main task.
ANSWERS_LEAD: Final = "The owner also said:"


def _answer_lines(row: Any) -> list[tuple[str, str]]:
    """Each answer as (its question, what the owner said), the choices ticked and the words
    typed; a price list or opening hours, which land in the business profile, are left out."""
    out: list[tuple[str, str]] = []
    for item in row.answers or []:
        if not isinstance(item, dict):
            continue
        said = [str(c) for c in item.get("choices") or []]
        if item.get("text"):
            said.append(str(item["text"]))
        if said:
            out.append((str(item.get("prompt") or ""), "; ".join(said)))
    return out


def calling_hours_of(row: Any) -> dict[str, str] | None:
    """The first campaign's calling window from what the owner said: an answer about when
    to call first, else their description ("Call only between 9am and 6pm"), narrowed to
    the platform's lawful hours. None when they gave none: the platform window applies."""
    from apps.api.agents.owner_words import calling_window, narrowed
    from apps.api.compliance.service import DEFAULT_WINDOW

    # A question and its answer are one sentence here, so "When may it call?" + "9am to 6pm"
    # reads as a window about calling.
    answered = [f"{prompt.rstrip(' ?')}: {said}" for prompt, said in _answer_lines(row)]
    for words in (*answered, row.brief or ""):
        window = calling_window(words)
        if window is not None:
            lawful = narrowed(window, DEFAULT_WINDOW)
            if lawful is None:
                return None
            return {"start": lawful[0].strftime("%H:%M"), "end": lawful[1].strftime("%H:%M")}
    return None


def owner_statements(row: Any) -> list[tuple[str, str]]:
    """The facts and rules the owner gave, as pinned facts (question, answer): each sentence
    of their description that states a fact about the business or sets the agent a rule,
    word for word, then each rule they ticked or typed in answer, then their answer to the
    one thing every caller should know, under its question."""
    from apps.api.agents.owner_words import stated_facts, stated_rules
    from apps.api.first_run.questions import ONE_THING

    brief = row.brief or ""
    pairs = [("", s) for s in (*stated_facts(brief), *stated_rules(brief))]
    for item in row.answers or []:
        if not isinstance(item, dict):
            continue
        if item.get("id") == ONE_THING.id and item.get("text"):
            pairs.append((ONE_THING.prompt, str(item["text"]).strip()))
            continue
        said = [*(str(c) for c in item.get("choices") or []), str(item.get("text") or "")]
        pairs += [("", rule) for words in said for rule in stated_rules(words)]
    return pairs


async def _pin_owner_statements(
    session: AsyncSession, *, tenant_id: UUID, row: Any, user_id: UUID | None
) -> None:
    """The owner's facts and rules (`owner_statements`) as the business's pinned facts, which
    every call of every agent carries (founder decision 9), rather than left only inside the
    work's main task, where the in-call model never reads them. Kept within the pinned
    section's room, so a long description never crowds out facts the owner pins themselves."""
    from apps.api.teach.pinned import pin_pairs

    pairs = owner_statements(row)
    if pairs:
        await pin_pairs(
            session,
            tenant_id=tenant_id,
            pairs=pairs,
            created_by=user_id,
            within_room=True,
        )


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
    drafts = (held_line if job == "answer_calls" else held_campaign) is None
    if drafts:
        # Before the draft is queued, so its script is written knowing them.
        await _pin_owner_statements(session, tenant_id=tenant_id, row=row, user_id=user_id)
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
            calling_hours=calling_hours_of(row),
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
    replace: bool = False,
) -> bool:
    """Give the first run's line or campaign the ready-made script for its job, while it has
    no script (or, with `replace`, in place of the ready-made one it holds, after the agent's
    language changed): Pip was not asked (no AI allowance left, or a view-as session) or could not
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
    if current is not None and not replace:
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
        await lines.save_script(session, line_id, script, author="system", reason=READY_MADE_REASON)
    else:
        assert campaign_id is not None
        await workspace.save_script(
            session, campaign_id, script, author="system", reason=READY_MADE_REASON
        )
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
