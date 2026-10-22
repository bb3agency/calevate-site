"""The first run, "Meet your agent": a new owner's first agent, from its job and their words.

D-855.

Founder, 23 Oct 2026. The first thing a new owner sees is their agent taking shape, not the
business setup wizard: its job, its languages, a brief in their own words (typed, spoken, or
the trade's own example), up to three follow-up questions, a build they watch step by step,
and a test call to their own phone. The wizard stays on the dashboard checklist and in
Settings.

WHERE THE OWNER IS LIVES IN ONE ROW (`first_runs`), so a reload, a second device or a return
next week lands on the same step, and the sign-in junction can tell a first-time owner from
one who has moved on (`is_due`). `business_profiles.setup_started_at` could not serve: any
profile save sets it, including the answers this flow writes.

NOTHING HERE CALLS A MODEL OR A SPEECH SERVICE. Hearing a recording, choosing the follow-up
questions and building the agent are worker jobs (`workers/first_run.py`) queued through the
outbox in the caller's transaction (BACKEND-PATTERNS §4); the screen polls this row. Every
write after a job is queued is a compare-and-set on the job's own state, so a second delivery
or a stale job never overwrites a newer request.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import published_extra_languages
from apps.api.agents.lifecycle import update_agent
from apps.api.agents.script_builder import load_agent_script, rewrite_script
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.first_run.models import (
    MAX_BUILD_RUNS,
    MAX_QUESTION_RUNS,
    MAX_QUESTIONS,
    MAX_RECORDINGS,
    MIN_BRIEF_CHARS,
)
from apps.api.first_run.names import identity_with_name
from apps.api.first_run.questions import QuestionKey, askable
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.business_copy import queue_generation
from apps.api.tenancy.business_profile import DAYS, Branch, DayHours, ServiceItem, load_profile
from apps.api.tenancy.profile_service import ProfilePatch, save_profile

#: The worker jobs (`workers/first_run.py`).
HEAR_JOB: Final = "hear_first_run_recording"
QUESTIONS_JOB: Final = "write_first_run_questions"
BUILD_JOB: Final = "build_first_agent"

#: The label of the branch the "Where are you?" answer creates.
MAIN_BRANCH_LABEL: Final = "Main branch"

_COLUMNS: Final = (
    "id, job, language_primary, languages_extra, brief, agent_id, questions_status, "
    "questions, questions_disclosure, question_runs, build_status, build_steps, "
    "build_disclosure, build_runs, finished_at, dismissed_at"
)


@dataclass(frozen=True, slots=True)
class RunState:
    #: None until the owner's first answer creates the row.
    id: UUID | None
    job: str | None
    language_primary: str | None
    languages_extra: list[str]
    brief: str | None
    agent_id: UUID | None
    questions_status: str
    questions: list[QuestionKey]
    questions_disclosure: str | None
    question_runs: int
    build_status: str
    build_steps: dict[str, Any]
    build_disclosure: str | None
    build_runs: int
    finished_at: datetime | None
    dismissed_at: datetime | None
    recordings_used: int = 0
    due: bool = False


def brief_hash(brief: str) -> str:
    return hashlib.sha256(" ".join(brief.split()).casefold().encode()).hexdigest()


def _state(row: Any, *, recordings_used: int, due: bool) -> RunState:
    return RunState(
        id=row.id,
        job=row.job,
        language_primary=row.language_primary,
        languages_extra=list(row.languages_extra or []),
        brief=row.brief,
        agent_id=row.agent_id,
        questions_status=str(row.questions_status),
        questions=[q["key"] for q in row.questions or [] if isinstance(q, dict) and "key" in q],
        questions_disclosure=row.questions_disclosure,
        question_runs=int(row.question_runs),
        build_status=str(row.build_status),
        build_steps=dict(row.build_steps or {}),
        build_disclosure=row.build_disclosure,
        build_runs=int(row.build_runs),
        finished_at=row.finished_at,
        dismissed_at=row.dismissed_at,
        recordings_used=recordings_used,
        due=due,
    )


async def _row(session: AsyncSession, *, lock: bool = False) -> Any:
    suffix = " FOR UPDATE" if lock else ""
    return (await session.execute(text(f"SELECT {_COLUMNS} FROM first_runs{suffix}"))).first()


async def _ensure(session: AsyncSession, *, tenant_id: UUID) -> Any:
    """The client's row, created on first use and locked for the caller's write."""
    await session.execute(
        text(
            "INSERT INTO first_runs (id, tenant_id) VALUES (:id, :tid) "
            "ON CONFLICT (tenant_id) DO NOTHING"
        ),
        {"id": uuid7(), "tid": tenant_id},
    )
    return await _row(session, lock=True)


async def _working_agents(session: AsyncSession) -> list[UUID]:
    rows = await session.execute(
        text("SELECT id FROM agents WHERE deleted_at IS NULL AND status <> 'archived' LIMIT 3")
    )
    return [r[0] for r in rows.all()]


def due_for(row: Any, agents: list[UUID]) -> bool:
    """Is this a first run still under way? Not finished or put aside, and no agent made any
    other way: an account whose owner built an agent on the Agents screen, or whose agents
    predate D-855, is past its first run whether or not this row exists."""
    if row is not None and (row.finished_at is not None or row.dismissed_at is not None):
        return False
    own = None if row is None else row.agent_id
    return all(agent == own for agent in agents)


async def _recordings_used(session: AsyncSession, run_id: UUID) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM first_run_recordings "
                    "WHERE first_run_id = :rid AND status <> 'failed'"
                ),
                {"rid": run_id},
            )
        ).scalar_one()
    )


async def read_state(session: AsyncSession, *, tenant_id: UUID) -> RunState:
    """The first run as the screen reads it. An account with no row yet reads as a run not
    started, which costs no write: a GET never creates the row."""
    row = await _row(session)
    agents = await _working_agents(session)
    due = due_for(row, agents)
    if row is None:
        return RunState(
            id=None,
            job=None,
            language_primary=None,
            languages_extra=[],
            brief=None,
            agent_id=None,
            questions_status="idle",
            questions=[],
            questions_disclosure=None,
            question_runs=0,
            build_status="idle",
            build_steps={},
            build_disclosure=None,
            build_runs=0,
            finished_at=None,
            dismissed_at=None,
            due=due,
        )
    return _state(row, recordings_used=await _recordings_used(session, row.id), due=due)


def _job_locked() -> ProblemError:
    return ProblemError.conflict(
        "first_run_job_locked",
        "Your agent is already built for this job.",
        remediation="Change what it does on its own page, under Script.",
    )


async def save_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job: str,
    language_primary: str,
    languages_extra: list[str],
) -> RunState:
    """The job and the languages. Once the agent is built its job stays, because the job set
    its calling direction and its ready-made script."""
    row = await _ensure(session, tenant_id=tenant_id)
    if row.agent_id is not None and row.job not in (None, job):
        raise _job_locked()
    extra = published_extra_languages(language_primary, languages_extra)
    await session.execute(
        text(
            "UPDATE first_runs SET job = :job, language_primary = :lang, "
            "languages_extra = :extra, updated_at = now() WHERE id = :id"
        ),
        {"id": row.id, "job": job, "lang": language_primary, "extra": extra},
    )
    return await read_state(session, tenant_id=tenant_id)


async def _vertical(session: AsyncSession) -> str | None:
    value = (
        await session.execute(text("SELECT vertical_template FROM organizations LIMIT 1"))
    ).scalar()
    return None if value is None else str(value)


async def save_brief(session: AsyncSession, *, tenant_id: UUID, brief: str) -> RunState:
    """Keep the brief and find the follow-up questions for it.

    A brief with something to read is sent to the model to choose questions (queued, once per
    distinct brief, at most `MAX_QUESTION_RUNS` times); a short one, or one past that bound,
    gets the profile's own gaps at once with no model at all.
    """
    row = await _ensure(session, tenant_id=tenant_id)
    cleaned = brief.strip()
    digest = brief_hash(cleaned) if cleaned else None
    await session.execute(
        text("UPDATE first_runs SET brief = :brief, updated_at = now() WHERE id = :id"),
        {"id": row.id, "brief": cleaned or None},
    )
    current = (
        await session.execute(
            text("SELECT questions_brief_hash FROM first_runs WHERE id = :id"), {"id": row.id}
        )
    ).scalar()
    if digest is not None and digest == current and row.questions_status in ("writing", "ready"):
        return await read_state(session, tenant_id=tenant_id)
    use_model = len(cleaned) >= MIN_BRIEF_CHARS and int(row.question_runs) < MAX_QUESTION_RUNS
    if use_model:
        await session.execute(
            text(
                "UPDATE first_runs SET questions_status = 'writing', questions = '[]'::jsonb, "
                "questions_disclosure = NULL, questions_brief_hash = :hash, "
                "question_runs = question_runs + 1, updated_at = now() WHERE id = :id"
            ),
            {"id": row.id, "hash": digest},
        )
        await enqueue_outbox(
            session,
            job=QUESTIONS_JOB,
            payload={"tenant_id": str(tenant_id), "run_id": str(row.id), "brief_hash": digest},
        )
    else:
        profile = await load_profile(session, tenant_id=tenant_id)
        keys = list(askable(profile, await _vertical(session)))[:MAX_QUESTIONS]
        await store_questions(
            session, run_id=row.id, brief_hash=digest, keys=keys, disclosure=None, writing=False
        )
    return await read_state(session, tenant_id=tenant_id)


async def store_questions(
    session: AsyncSession,
    *,
    run_id: UUID,
    brief_hash: str | None,
    keys: Sequence[str],
    disclosure: str | None,
    writing: bool = True,
) -> bool:
    """Write the questions for the brief they were chosen for. False when the owner has since
    changed the brief, so the job that chose them for the old one writes nothing."""
    guard = "AND questions_status = 'writing' AND questions_brief_hash = :hash" if writing else ""
    stored = (
        await session.execute(
            text(
                "UPDATE first_runs SET questions_status = 'ready', "
                "questions = CAST(:questions AS jsonb), questions_disclosure = :disclosure, "
                "questions_brief_hash = :hash, updated_at = now() "
                f"WHERE id = :id {guard} RETURNING id"
            ),
            {
                "id": run_id,
                "hash": brief_hash,
                "questions": json.dumps([{"key": key} for key in keys]),
                "disclosure": disclosure,
            },
        )
    ).first()
    return stored is not None


# ---------------------------------------------------------------------- the spoken brief


async def start_recording(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    recording_id: UUID,
    language: str,
    object_key: str,
    content_type: str,
) -> UUID:
    """Record one spoken piece and queue it to be heard, refusing a fourth."""
    row = await _ensure(session, tenant_id=tenant_id)
    if await _recordings_used(session, row.id) >= MAX_RECORDINGS:
        raise ProblemError.business_rule(
            "first_run_recordings_used",
            f"You have recorded {MAX_RECORDINGS} pieces, which is the most we take.",
            remediation="Type the rest into the box, or change the words you already have.",
        )
    await session.execute(
        text(
            "INSERT INTO first_run_recordings (id, tenant_id, first_run_id, status, language, "
            "object_key, content_type) VALUES (:id, :tid, :rid, 'queued', :lang, :key, :ctype)"
        ),
        {
            "id": recording_id,
            "tid": tenant_id,
            "rid": row.id,
            "lang": language,
            "key": object_key,
            "ctype": content_type,
        },
    )
    await enqueue_outbox(
        session,
        job=HEAR_JOB,
        payload={"tenant_id": str(tenant_id), "recording_id": str(recording_id)},
    )
    return recording_id


@dataclass(frozen=True, slots=True)
class Recording:
    id: UUID
    status: str
    words: str | None
    error_code: str | None


async def read_recording(session: AsyncSession, recording_id: UUID) -> Recording:
    row = (
        await session.execute(
            text("SELECT id, status, words, error_code FROM first_run_recordings WHERE id = :id"),
            {"id": recording_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Recording")
    return Recording(id=row.id, status=str(row.status), words=row.words, error_code=row.error_code)


# ---------------------------------------------------------------------- the answers


@dataclass(frozen=True, slots=True)
class OpenHours:
    """The hours question's whole answer: the same hours every day, closed on these days."""

    opens: str
    closes: str
    closed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Answers:
    trade: tuple[str, ...] = ()
    location: str | None = None
    offer: tuple[ServiceItem, ...] = ()
    hours: OpenHours | None = None
    booking: str | None = None


def _merged_services(
    existing: list[ServiceItem], added: tuple[ServiceItem, ...]
) -> list[ServiceItem]:
    """The profile's services with the answers added: one per name, a new price replacing an
    old one, nothing the owner had removed brought back."""
    out = list(existing)
    for item in added:
        name = item.name.strip()
        index = next((i for i, s in enumerate(out) if s.name.casefold() == name.casefold()), None)
        if index is None:
            out.append(item)
        elif item.price_inr is not None:
            out[index] = out[index].model_copy(update={"price_inr": item.price_inr})
    return out


async def save_answers(
    session: AsyncSession, *, tenant_id: UUID, answers: Answers, user_id: UUID | None
) -> set[str]:
    """Write the follow-up answers into the business profile, the store every agent reads.

    Through `save_profile`, the setup wizard's own save, so the facts reach every agent by the
    same fan-out. A list section is sent whole (that is the save's rule), so the answers are
    merged into what the profile already holds rather than replacing it.
    """
    profile = await load_profile(session, tenant_id=tenant_id)
    patch: dict[str, Any] = {}
    added = tuple(ServiceItem(name=name) for name in answers.trade) + answers.offer
    if added:
        patch["services"] = _merged_services(profile.services, added)
    if answers.location:
        patch["branches"] = [
            *profile.branches,
            Branch(label=MAIN_BRANCH_LABEL, address=answers.location.strip()),
        ]
    if answers.hours is not None:
        closed = set(answers.hours.closed)
        patch["hours"] = [
            DayHours.model_validate(
                {"day": day, "closed": True}
                if day in closed
                else {"day": day, "opens": answers.hours.opens, "closes": answers.hours.closes}
            )
            for day in DAYS
        ]
    if answers.booking:
        patch["booking_rules"] = answers.booking.strip()
    if not patch:
        return set()
    steps, _updated = await save_profile(
        session, tenant_id=tenant_id, patch=ProfilePatch(**patch), user_id=user_id
    )
    return steps


# ---------------------------------------------------------------------- the build


def _not_ready_to_build(remediation: str) -> ProblemError:
    return ProblemError.business_rule(
        "first_run_not_ready",
        "Choose your agent's job and language first.",
        remediation=remediation,
    )


async def request_build(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID | None
) -> RunState:
    """Queue the build. The first build creates the agent; a later one (after the brief
    changed) rewrites the same agent's script, never a second agent.

    The first build also queues the business's examples to be written again (D-827), so the
    hints on every screen use what the owner said rather than only the trade's defaults."""
    row = await _ensure(session, tenant_id=tenant_id)
    if row.job is None or row.language_primary is None:
        raise _not_ready_to_build("Go back to the first step and pick what it should do.")
    if row.build_status == "building":
        return await read_state(session, tenant_id=tenant_id)
    if int(row.build_runs) >= MAX_BUILD_RUNS:
        raise ProblemError.business_rule(
            "first_run_builds_used",
            "Your agent has been built as many times as this screen allows.",
            remediation="Change anything else on its own page, under Script.",
        )
    await session.execute(
        text(
            "UPDATE first_runs SET build_status = 'building', build_steps = '{}'::jsonb, "
            "build_disclosure = NULL, build_runs = build_runs + 1, "
            "build_requested_at = now(), updated_at = now() WHERE id = :id"
        ),
        {"id": row.id},
    )
    await enqueue_outbox(
        session,
        job=BUILD_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "run_id": str(row.id),
            "build": int(row.build_runs) + 1,
            "requested_by": None if user_id is None else str(user_id),
        },
    )
    if int(row.build_runs) == 0 and row.brief:
        await queue_generation(session, tenant_id=tenant_id, trigger="first_run")
    return await read_state(session, tenant_id=tenant_id)


async def rename_agent(
    session: AsyncSession, *, tenant_id: UUID, name: str, user_id: UUID | None
) -> RunState:
    """Rename the agent this run built, on the screen and in what it says about itself.

    Only before it is first got ready for a call: after that the calling system holds its
    script, and a rename belongs on its own page where putting the change live is shown."""
    row = await _ensure(session, tenant_id=tenant_id)
    if row.agent_id is None:
        raise ProblemError.business_rule(
            "first_run_no_agent", "Your agent is not built yet.", remediation="Build it first."
        )
    status = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": row.agent_id},
        )
    ).scalar()
    if status is None:
        raise ProblemError.not_found("Agent")
    if str(status) != "draft":
        raise ProblemError.conflict(
            "first_run_rename_after_ready",
            "Your agent is already set up for calls.",
            remediation="Rename it on its own page, then put the change live.",
        )
    clean = " ".join(name.split())
    await update_agent(session, tenant_id=tenant_id, agent_id=row.agent_id, name=clean)
    loaded = await load_agent_script(session, row.agent_id)
    await rewrite_script(
        session,
        tenant_id=tenant_id,
        agent_id=row.agent_id,
        script=loaded.script.model_copy(
            update={"identity": identity_with_name(loaded.script.identity, clean)}
        ),
        notes="Renamed",
        created_by=user_id,
    )
    return await read_state(session, tenant_id=tenant_id)


Marker = Literal["finished", "dismissed"]


async def mark(session: AsyncSession, *, tenant_id: UUID, marker: Marker) -> RunState:
    """The owner finished the flow, or put it aside for now. Either way the junction stops
    sending them here; the dashboard still offers it while they have no agent."""
    row = await _ensure(session, tenant_id=tenant_id)
    column = "finished_at" if marker == "finished" else "dismissed_at"
    await session.execute(
        text(
            f"UPDATE first_runs SET {column} = coalesce({column}, now()), updated_at = now() "
            "WHERE id = :id"
        ),
        {"id": row.id},
    )
    return await read_state(session, tenant_id=tenant_id)


__all__ = [
    "BUILD_JOB",
    "HEAR_JOB",
    "MAIN_BRANCH_LABEL",
    "QUESTIONS_JOB",
    "Answers",
    "Marker",
    "OpenHours",
    "Recording",
    "RunState",
    "brief_hash",
    "due_for",
    "mark",
    "read_recording",
    "read_state",
    "rename_agent",
    "request_build",
    "save_answers",
    "save_brief",
    "save_job",
    "start_recording",
    "store_questions",
]
