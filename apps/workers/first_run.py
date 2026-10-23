"""The work behind "Meet your agent" (D-855), from the outbox: hear, ask, build.

1. HEAR one spoken piece of the brief (`hear_first_run_recording`): speech-to-text with the
   owner's language as a hint, metered at our cost under its own feature, and the audio
   DELETED as soon as the words exist (founder, 23 Oct 2026: the screen says the audio is not
   kept, so it is not). Failed or not, nothing is left in the bucket.
2. ASK (`write_first_run_questions`): the model WRITES two to four follow-up questions the
   brief leaves open, each with its kind of answer (D-863); what it writes reaches the screen
   only through `first_run/questions.written_questions`, which drops any item that breaks a
   rule. Without a model, or with nothing left, the fixed questions for the profile's empty
   sections are asked instead: the step never stops for lack of AI.
3. BUILD the first agent (`build_first_agent`), each step written to the row as it lands so
   the screen ticks what really happened:
   - **voice**: a woman's Studio voice for its language, or Clear when Studio cannot be used
     here or has no woman's voice (`agents/voice_pick`), for the agent named "Anjali"
     (`first_run/names`);
   - **script**: the agent created from its job's ready-made script, then the script written
     from the brief by the script writer (`script_assist.draft_script`) and applied at once
     as its first version. Without a usable answer the ready-made script stays, and the
     step says so;
   - **greeting**: an opening line that fits the first-agent rule (under 120 characters,
     ending with a question, no textbook word, every word in the language's own letters but
     the business's and the agent's names) and the engine's ceiling, else the starter's
     reviewed line for its language;
   - **notice**: the AI notice switched on, said after the greeting on every call (D-864),
     unless the owner switched it off for this agent or the greeting leaves no room.

The model reads only the owner's own words about their business (the tenant-authored class
`script_assist` serves), never a caller's, and none of it is logged (hard rule 6). Every model
call is metered under `ASSIST_FEATURE_FIRST_RUN`, ours to pay for.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Final
from uuid import UUID

import httpx
from calevate_shared.call_script import CallScript
from calevate_shared.spoken_guard import latin_words, textbook_problem
from sqlalchemy import text

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.lifecycle import create_agent, update_agent
from apps.api.agents.publishing import audit_action_for, set_disclosure_posture
from apps.api.agents.script_builder import (
    load_agent_script,
    replace_opening_line,
    rewrite_script,
    save_agent_script,
)
from apps.api.agents.script_proposals import brief_for
from apps.api.agents.starters import StarterJob, direction_of_jobs, starter_jobs, starter_script
from apps.api.agents.voice_pick import pick_voice
from apps.api.billing.ai_quota import new_assist_ref, platform_brake_tripped
from apps.api.billing.models import ASSIST_FEATURE_FIRST_RUN
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run.models import MAX_QUESTIONS, MAX_RECORDING_WORDS, MIN_BRIEF_CHARS
from apps.api.first_run.names import FIRST_AGENT_NAME, identity_with_name
from apps.api.first_run.questions import (
    HINT_MAX,
    MAX_OPTIONS,
    MAX_WRITTEN,
    MIN_OPTIONS,
    MIN_WRITTEN,
    OPTION_MAX,
    PROFILE_TOPICS,
    PROMPT_MAX,
    QUESTION_KINDS,
    Question,
    answered_topics,
    fallback_questions,
    written_questions,
)
from apps.api.first_run.service import (
    BUILD_JOB,
    HEAR_JOB,
    QUESTIONS_JOB,
    answers_for_script,
    store_questions,
)
from apps.api.tenancy.business_profile import Profile, load_profile
from apps.workers.script_assist import JsonAnswer, ScriptDraft, ask_json, draft_script
from apps.workers.speech_to_text import meter_clip, transcribe
from apps.workers.storage import delete_objects, read_kb_object

log = get_logger(__name__)

#: `usage_events.meta.feature` for hearing a spoken brief. Absorbed, as the teach box's is.
ASSIST_FEATURE_FIRST_RUN_VOICE: Final = "first_run_voice"

#: The first-agent greeting rule, the one D-854's card and Pip's guide use
#: (`copilot/screen_guides.FIRST_GREETING_MAX_CHARS`).
GREETING_MAX_CHARS: Final = 120

#: The switch the notice step turns on (`agents.ai_disclosure_enabled`).
AI_NOTICE: Final = "ai_disclosure_enabled"

#: What the script writer is told about each job beyond its calling direction.
_JOB_CONTEXT: Final[dict[str, str]] = {
    "answer_calls": "It answers the business's phone when customers call.",
    "call_new_leads": (
        "It calls each person within minutes of their enquiry, while it is fresh, so it can "
        "thank them for the enquiry they just made."
    ),
    "call_leads": (
        "It runs calling campaigns: it calls people on the business's list who showed "
        "interest earlier."
    ),
}
#: Said once when the agent does more than one job (D-863).
_SEVERAL_JOBS: Final = (
    "It is ONE agent doing all of these jobs, so the script keeps a separate part for "
    "calls the person made and calls the agent makes."
)

QUESTIONS_INSTRUCTION: Final = (
    "A small Indian business owner has described the phone agent they want. Write "
    f"{MIN_WRITTEN} to {MAX_WRITTEN} short follow-up questions that would help the agent "
    "serve THIS business and that the description does NOT already answer, most useful "
    "first. Plain English only: no links, no markdown, no emoji, no other script. Each "
    f"question: prompt (at most {PROMPT_MAX} characters), hint (one helpful sentence, at "
    f"most {HINT_MAX} characters), kind, options and maps_to. kind is one of: choices (tick "
    "all that apply), single_choice (pick one), text, address, services (a list of what "
    f"they offer with prices), hours (opening hours). choices and single_choice need "
    f"{MIN_OPTIONS} to {MAX_OPTIONS} options of at most {OPTION_MAX} characters; every other "
    "kind has options []. maps_to names the business profile section the answer belongs "
    "in, or null: trade (choices or single_choice about what kinds of thing they offer), "
    "location (address), offer (services), hours (hours), booking (text about how a "
    "booking is made). address, services and hours must use their section. "
    "Never use a section listed as already known. Return ONLY JSON: "
    '{"questions": [{"prompt": "...", "hint": "...", "kind": "...", "options": [...], '
    '"maps_to": ... }]}.'
)


# --------------------------------------------------------------------------- hear


async def _recording_failed(tenant_id: UUID, recording_id: UUID, code: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE first_run_recordings SET status = 'failed', error_code = :code, "
                "object_key = NULL, updated_at = now() "
                "WHERE id = :id AND status = 'hearing'"
            ),
            {"id": recording_id, "code": code},
        )


async def hear_first_run_recording(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Hear one spoken piece of the brief, keep its words, delete its audio."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    recording_id = UUID(str(payload["recording_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE first_run_recordings SET status = 'hearing', updated_at = now() "
                    "WHERE id = :id AND status = 'queued' "
                    "RETURNING object_key, content_type, language"
                ),
                {"id": recording_id},
            )
        ).first()
    if claimed is None:
        return "not_queued"
    key, content_type, language = claimed
    try:
        data = await read_kb_object(str(key)) if key else None
        if data is None:
            await _recording_failed(tenant_id, recording_id, "upload_missing")
            return "failed"
        try:
            words = await transcribe(data, str(content_type or ""), language=str(language))
        except (httpx.HTTPError, RuntimeError, ValueError) as failure:
            log.warning("first_run_stt_failed", extra={"error": type(failure).__name__})
            await _recording_failed(tenant_id, recording_id, "voice_unreadable")
            return "failed"
        finally:
            # The audio has done its job either way; only the words are kept.
            await delete_objects([str(key)])
        await meter_clip(tenant_id, feature=ASSIST_FEATURE_FIRST_RUN_VOICE)
        words = " ".join(words.split())[:MAX_RECORDING_WORDS]
        if not words:
            await _recording_failed(tenant_id, recording_id, "nothing_heard")
            return "failed"
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE first_run_recordings SET status = 'heard', words = :words, "
                    "object_key = NULL, updated_at = now() "
                    "WHERE id = :id AND status = 'hearing'"
                ),
                {"id": recording_id, "words": words},
            )
    except Exception:
        log.exception("first_run_hear_crashed", extra={"recording_id": str(recording_id)})
        await _recording_failed(tenant_id, recording_id, "crashed")
        return "failed"
    return "heard"


# --------------------------------------------------------------------------- ask


def _questions_parser(profile: Profile) -> Any:
    """The model's questions through the gate; None (no answer) when none survive, so the
    next leg of the ladder gets its chance and the fixed questions come last."""

    def parse(raw: dict[str, Any]) -> list[Question] | None:
        written = raw.get("questions")
        if not isinstance(written, list):
            return None
        return written_questions(written, profile) or None

    return parse


#: The paid leg's strict schema. Lengths and patterns are the gate's to enforce: a strict
#: schema rejects `maxLength`, and the gate must run on every leg anyway.
QUESTIONS_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "first_run_questions",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string"},
                            "hint": {"type": "string"},
                            "kind": {"type": "string", "enum": list(QUESTION_KINDS)},
                            "options": {"type": "array", "items": {"type": "string"}},
                            "maps_to": {
                                "type": ["string", "null"],
                                "enum": [*PROFILE_TOPICS, None],
                            },
                        },
                        "required": ["prompt", "hint", "kind", "options", "maps_to"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
}


async def write_first_run_questions(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Write the follow-up questions for one brief and store them on the run."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    run_id = UUID(str(payload["run_id"]))
    digest = payload.get("brief_hash")
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT r.brief, r.jobs, r.questions_status, r.questions_brief_hash, "
                    "o.vertical_template FROM first_runs r "
                    "JOIN organizations o ON o.id = r.tenant_id WHERE r.id = :id"
                ),
                {"id": run_id},
            )
        ).first()
        if row is None or row.questions_status != "writing" or row.questions_brief_hash != digest:
            return "not_pending"
        vertical = None if row.vertical_template is None else str(row.vertical_template)
        profile = await load_profile(session, tenant_id=tenant_id)
        tenant_leg = await account_assist_leg(session)
        braked = await platform_brake_tripped(session)
    questions = fallback_questions(profile, vertical, limit=MAX_QUESTIONS)
    disclosure: str | None = None
    known = ", ".join(sorted(answered_topics(profile))) or "none"
    jobs = "; ".join(_JOB_CONTEXT[job] for job in row.jobs or [] if job in _JOB_CONTEXT)
    try:
        answer: JsonAnswer[list[Question]] = await ask_json(
            f"The owner's description:\n{row.brief}\n\nWhat the agent does: {jobs or 'not said'}"
            f"\nBusiness profile sections already known: {known}",
            QUESTIONS_INSTRUCTION,
            parse=_questions_parser(profile),
            azure_format=QUESTIONS_FORMAT,
            tenant_leg=tenant_leg,
            quota_exhausted=braked,
            max_tokens=900,
            temperature=0.3,
            health_leg="script",
        )
    except ProblemError as refused:
        log.info("first_run_questions_fixed", extra={"reason": refused.code})
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=ASSIST_FEATURE_FIRST_RUN
            )
    else:
        questions = answer.value
        disclosure = answer.capability.disclosure
        await _meter(tenant_id, answer)
    async with tenant_session(tenant_id) as session:
        stored = await store_questions(
            session,
            run_id=run_id,
            brief_hash=None if digest is None else str(digest),
            questions=questions,
            disclosure=disclosure,
        )
    return "ready" if stored else "not_pending"


async def _meter(tenant_id: UUID, answer: JsonAnswer[Any] | ScriptDraft) -> None:
    """A completed run is money spent, recorded in its own transaction (crm/assist §4)."""
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=ASSIST_FEATURE_FIRST_RUN
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            model=answer.model,
            feature=ASSIST_FEATURE_FIRST_RUN,
        )


# --------------------------------------------------------------------------- build


async def _tick(
    tenant_id: UUID, run_id: UUID, build: int, step: str, state: dict[str, Any]
) -> bool:
    """Write one finished step. False when the build was replaced or failed meanwhile."""
    async with tenant_session(tenant_id) as session:
        done = (
            await session.execute(
                text(
                    "UPDATE first_runs SET build_steps = build_steps || "
                    "jsonb_build_object(CAST(:step AS text), CAST(:state AS jsonb)), "
                    "updated_at = now() WHERE id = :id AND build_status = 'building' "
                    "AND build_runs = :build RETURNING id"
                ),
                {"id": run_id, "build": build, "step": step, "state": json.dumps(state)},
            )
        ).first()
    return done is not None


async def _finish_build(
    tenant_id: UUID, run_id: UUID, build: int, status: str, disclosure: str | None
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE first_runs SET build_status = :status, build_disclosure = :disclosure, "
                "updated_at = now() WHERE id = :id AND build_status = 'building' "
                "AND build_runs = :build"
            ),
            {"id": run_id, "build": build, "status": status, "disclosure": disclosure},
        )


def greeting_fits(line: str, language: str, *, names: Sequence[str] = ()) -> bool:
    """The first-agent greeting rule: short, ending on a question that hands the turn over,
    with no textbook word callers do not say, and every word in the language's own letters
    apart from `names` (D-861, D-864)."""
    clean = line.strip()
    return (
        bool(clean)
        and len(clean) <= GREETING_MAX_CHARS
        and clean.endswith("?")
        and textbook_problem("opening_line", clean, language) is None
        and not latin_words(clean, language, names=names)
    )


def _jobs(run: Any) -> tuple[StarterJob, ...]:
    return starter_jobs(list(run.jobs or []))


async def _create(
    tenant_id: UUID, run: Any, *, name: str, voice_id: str | None, created_by: UUID | None
) -> tuple[UUID, bool]:
    """The ONE agent for every job picked, from their ready-made script, with its voice.
    Returns (id, voice set)."""
    jobs = _jobs(run)
    async with tenant_session(tenant_id) as session:
        agent_id = await create_agent(
            session,
            tenant_id=tenant_id,
            name=name,
            direction=direction_of_jobs(jobs),
            language_primary=str(run.language_primary),
            languages_extra=list(run.languages_extra or []),
            starter=jobs,
            created_by=created_by,
        )
        voiced = False
        if voice_id is not None:
            try:
                async with session.begin_nested():
                    await update_agent(
                        session,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        engine_voice_id=voice_id,
                        set_engine_voice_id=True,
                    )
                voiced = True
            except ProblemError as refused:
                log.info("first_run_voice_refused", extra={"reason": refused.code})
        await session.execute(
            text("UPDATE first_runs SET agent_id = :aid, updated_at = now() WHERE id = :id"),
            {"aid": agent_id, "id": run.id},
        )
    return agent_id, voiced


async def _write_script(
    tenant_id: UUID, agent_id: UUID, run: Any, *, name: str, created_by: UUID | None
) -> tuple[dict[str, Any], str | None]:
    """The script from the brief, applied as the agent's version; the ready-made one when
    the brief is too short or no model gives a usable answer. Returns (step state,
    disclosure)."""
    brief = (run.brief or "").strip()
    draft: ScriptDraft | None = None
    if len(brief) >= MIN_BRIEF_CHARS:
        async with tenant_session(tenant_id) as session:
            context = await brief_for(session, tenant_id, agent_id)
            tenant_leg = await account_assist_leg(session)
            braked = await platform_brake_tripped(session)
        jobs = _jobs(run)
        what_it_does = " ".join(_JOB_CONTEXT[job] for job in jobs)
        if len(jobs) > 1:
            what_it_does += f" {_SEVERAL_JOBS}"
        answers = answers_for_script(run.answers or [])
        description = (
            f"{brief}\n{what_it_does}\n"
            + (f"The owner's answers to follow-up questions:\n{answers}\n" if answers else "")
            + f"The agent's name is {name}; it gives this name when it introduces itself or is "
            "asked. Keep the opening line under "
            f"{GREETING_MAX_CHARS} characters, ending with a question to the person."
        )
        try:
            draft = await draft_script(
                replace(context, description=description),
                tenant_leg=tenant_leg,
                quota_exhausted=braked,
            )
        except ProblemError as refused:
            log.info("first_run_script_ready_made", extra={"reason": refused.code})
            async with tenant_session(tenant_id) as session:
                await crm_assist.meter_refusal(
                    session, tenant_id=tenant_id, refusal=refused, feature=ASSIST_FEATURE_FIRST_RUN
                )
        else:
            await _meter(tenant_id, draft)
    async with tenant_session(tenant_id) as session:
        if draft is not None:
            script = draft.script.model_copy(
                update={"identity": identity_with_name(draft.script.identity, name)}
            )
            await save_agent_script(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                script=script,
                notes="Written from your own words",
                created_by=created_by,
            )
            return {"state": "done"}, draft.capability.disclosure
        current: CallScript = (await load_agent_script(session, agent_id)).script
        await rewrite_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=current.model_copy(
                update={"identity": identity_with_name(current.identity, name)}
            ),
            notes="Ready-made starter, named",
            created_by=created_by,
        )
    return {"state": "ready_made"}, None


async def _write_greeting(
    tenant_id: UUID, agent_id: UUID, run: Any, *, name: str, created_by: UUID | None
) -> dict[str, Any]:
    """Keep the written greeting when it fits the rule, else the starter's reviewed line."""
    language = str(run.language_primary)
    async with tenant_session(tenant_id) as session:
        current = (await load_agent_script(session, agent_id)).script.opening_line.strip()
        business = (
            await session.execute(text("SELECT name, vertical_template FROM organizations LIMIT 1"))
        ).one()
    if greeting_fits(current, language, names=(str(business[0]), name)):
        return {"state": "done"}
    starter_line = starter_script(
        None if business[1] is None else str(business[1]),
        _jobs(run),
        business=str(business[0]),
        language=language,
    ).opening_line
    if starter_line.strip() == current:
        return {"state": "kept"}
    try:
        async with tenant_session(tenant_id) as session:
            # The engine's own ceiling is checked here too (D-846).
            await replace_opening_line(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                opening_line=starter_line,
                created_by=created_by,
            )
    except ProblemError as refused:
        log.info("first_run_greeting_kept", extra={"reason": refused.code})
        return {"state": "kept"}
    return {"state": "ready_made"}


async def _switch_on_ai_notice(tenant_id: UUID, agent_id: UUID) -> dict[str, Any]:
    """Switch the AI notice on, so the first agent says it after its greeting (D-864).

    Every agent is created with both notices off (D-669), and this step used to only read
    back that the sentence was on file, so the first run's agent opened with no AI notice
    while the build said "Adding its AI notice". The recording notice is left as created:
    it is the owner's choice (D-669, D-163). An owner who has already switched the AI notice
    off for this agent keeps that choice on a rebuild. Through `set_disclosure_posture`, the
    one writer of the switch, so the greeting budget is checked (D-846) and a live agent is
    republished; audited as the system, as the switch route audits the owner."""
    async with tenant_session(tenant_id) as session:
        line = (
            await session.execute(
                text("SELECT ai_disclosure_line FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
        owner_off = (
            await session.execute(
                text("SELECT 1 FROM audit_log WHERE action = :a AND object_id = :o LIMIT 1"),
                {"a": audit_action_for(AI_NOTICE, enabled=False), "o": str(agent_id)},
            )
        ).first()
    if not (line or "").strip():
        return {"state": "missing"}
    if owner_off is not None:
        return {"state": "off"}
    try:
        result = await set_disclosure_posture(
            tenant_id=tenant_id,
            agent_id=agent_id,
            ai_disclosure_enabled=True,
            recording_notice_enabled=None,
        )
    except ProblemError as refused:
        log.info("first_run_notice_refused", extra={"reason": refused.code})
        return {"state": "no_room"}
    if result.changed:
        async with tenant_session(tenant_id) as session:
            await write_audit(
                session,
                action=audit_action_for(AI_NOTICE, enabled=True),
                tenant_id=tenant_id,
                object_type="agent",
                object_id=str(agent_id),
                summary={"engine_synced": result.engine_synced, "by": "first_run"},
            )
    return {"state": "done"}


async def build_first_agent(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Build (or rebuild from a changed brief) the first agent, one ticked step at a time."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    run_id = UUID(str(payload["run_id"]))
    build = int(payload["build"])
    raw_by = payload.get("requested_by")
    created_by = UUID(str(raw_by)) if raw_by else None
    async with tenant_session(tenant_id) as session:
        # Taken once: a second delivery of the same build finds the claim and stops.
        run = (
            await session.execute(
                text(
                    "UPDATE first_runs SET build_steps = build_steps || '{\"claimed\": true}' "
                    "WHERE id = :id AND build_status = 'building' AND build_runs = :build "
                    "AND NOT build_steps ? 'claimed' RETURNING id, jobs, language_primary, "
                    "languages_extra, brief, answers, agent_id"
                ),
                {"id": run_id, "build": build},
            )
        ).first()
        held_voice = None
        if run is not None and run.agent_id is not None:
            held_voice = (
                await session.execute(
                    text("SELECT engine_voice_id, name FROM agents WHERE id = :aid"),
                    {"aid": run.agent_id},
                )
            ).first()
    if run is None:
        return "not_pending"
    try:
        language = str(run.language_primary)
        agent_id: UUID
        if run.agent_id is not None and held_voice is not None:
            agent_id, name = run.agent_id, str(held_voice[1])
            voice_state: dict[str, Any] = {"state": "kept" if held_voice[0] else "none"}
        else:
            picked = await pick_voice(tenant_id, language)
            voice = picked.row if picked else None
            name = FIRST_AGENT_NAME
            agent_id, voiced = await _create(
                tenant_id,
                run,
                name=name,
                voice_id=voice.voice_id if voice else None,
                created_by=created_by,
            )
            voice_state = (
                {
                    "state": "done",
                    "label": picked.row.label,
                    "rung": picked.rung,
                    "fallback": picked.fallback,
                    "not_female": picked.not_female,
                }
                if picked and voiced
                else {"state": "none"}
            )
        if not await _tick(tenant_id, run_id, build, "voice", voice_state):
            return "replaced"
        script_state, disclosure = await _write_script(
            tenant_id, agent_id, run, name=name, created_by=created_by
        )
        if not await _tick(tenant_id, run_id, build, "script", script_state):
            return "replaced"
        greeting_state = await _write_greeting(
            tenant_id, agent_id, run, name=name, created_by=created_by
        )
        if not await _tick(tenant_id, run_id, build, "greeting", greeting_state):
            return "replaced"
        if not await _tick(
            tenant_id, run_id, build, "notice", await _switch_on_ai_notice(tenant_id, agent_id)
        ):
            return "replaced"
        await _finish_build(tenant_id, run_id, build, "built", disclosure)
    except Exception:
        log.exception("first_run_build_crashed", extra={"run_id": str(run_id)})
        await _finish_build(tenant_id, run_id, build, "failed", None)
        return "failed"
    log.info("first_run_built", extra={"run_id": str(run_id), "agent_id": str(agent_id)})
    return "built"


#: The outbox job names, as `first_run/service.py` queues them.
JOB_NAMES: Final = (HEAR_JOB, QUESTIONS_JOB, BUILD_JOB)

__all__ = [
    "ASSIST_FEATURE_FIRST_RUN_VOICE",
    "JOB_NAMES",
    "build_first_agent",
    "greeting_fits",
    "hear_first_run_recording",
    "write_first_run_questions",
]
