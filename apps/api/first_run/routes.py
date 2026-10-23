"""The new owner's first run, "Meet your agent" (D-855).

    GET  /v1/first-run                       where the owner is, and whether it is still due
    PUT  /v1/first-run/job                   the job and the languages
    PUT  /v1/first-run/brief                 the brief; queues the follow-up questions
    POST /v1/first-run/recordings            one spoken piece of the brief (under 30 s)
    GET  /v1/first-run/recordings/{id}       what was heard
    POST /v1/first-run/answers               the follow-up answers, into the business profile
    POST /v1/first-run/build                 build the agent (a worker; the screen polls)
    PUT  /v1/first-run/name                  rename the agent before its first call
    POST /v1/first-run/finish | /dismiss     done, or put aside for now

All `org:manage`: building the account's first agent is the owner's act, the same permission
`POST /v1/agents` takes. Uploading a recording is NOT the knowledge base's `kb:write`, because
it teaches no agent anything: its words come back into the brief box. Every write is audited
with names and counts, never the words (hard rule 6).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import OfferedLanguage
from apps.api.agents.starters import StarterJob
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.first_run import service
from apps.api.first_run.models import BUILD_STEPS, MAX_BUILD_RUNS, MAX_RECORDINGS, BuildStep
from apps.api.first_run.schemas import (
    AnswersIn,
    BriefIn,
    BuildOut,
    BuildStepOut,
    FirstRunOut,
    JobIn,
    NameIn,
    QuestionOut,
    QuestionsOut,
    RecordingOut,
)
from apps.api.teach.routes import read_bounded_upload
from apps.api.teach.teaching import MAX_VOICE_BYTES, VOICE_CONTENT_TYPES

router = APIRouter(prefix="/v1/first-run", tags=["first-run"])

Session = Annotated[AsyncSession, Depends(db)]
Owner = Annotated[Principal, Depends(requires("org:manage"))]

_MANAGE = permission_meta("org:manage")


def _step_out(step: BuildStep, found: dict[str, Any]) -> BuildStepOut:
    """One build step as the worker wrote it; a step it has not reached is `waiting`."""
    return BuildStepOut(
        step=step,
        state=str(found.get("state", "waiting")),
        label=found.get("label"),
        rung=found.get("rung"),
        fallback=found.get("fallback"),
        not_female=bool(found.get("not_female", False)),
    )


async def _out(session: AsyncSession, tenant_id: UUID) -> FirstRunOut:
    state = await service.read_state(session, tenant_id=tenant_id)
    items = [
        QuestionOut(
            id=question.id,
            prompt=question.prompt,
            hint=question.hint,
            kind=question.kind,
            options=list(question.options),
            maps_to=question.maps_to,
        )
        for question in state.questions
    ]
    steps = [_step_out(step, state.build_steps.get(step) or {}) for step in BUILD_STEPS]
    return FirstRunOut(
        due=state.due,
        jobs=cast("list[StarterJob]", state.jobs),
        language_primary=state.language_primary,
        languages_extra=state.languages_extra,
        brief=state.brief,
        agent_id=state.agent_id,
        questions=QuestionsOut(
            status=state.questions_status, items=items, disclosure=state.questions_disclosure
        ),
        build=BuildOut(
            status=state.build_status,
            steps=steps,
            disclosure=state.build_disclosure,
            builds_left=max(0, MAX_BUILD_RUNS - state.build_runs),
        ),
        recordings_left=max(0, MAX_RECORDINGS - state.recordings_used),
        finished_at=state.finished_at,
        dismissed_at=state.dismissed_at,
    )


async def _audit(
    session: AsyncSession,
    principal: Principal,
    request: Request,
    action: str,
    summary: dict[str, object],
) -> None:
    assert principal.tenant_id is not None
    await write_audit(
        session,
        actor=principal,
        action=action,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary=summary,
    )


@router.get(
    "",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Where the owner is in their first run, and whether it is still due",
)
async def read_first_run(session: Session, principal: Owner) -> FirstRunOut:
    assert principal.tenant_id is not None
    return await _out(session, principal.tenant_id)


@router.put(
    "/job",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Choose the agent's jobs and the languages it speaks",
    description=(
        "One to three jobs, each once; ONE agent does every job picked (answering only: "
        "inbound; calling only: outbound; both: `both`). Refused with "
        "`first_run_job_locked` once the agent is built for other jobs: they set its calling "
        "direction and its ready-made script."
    ),
)
async def put_job(
    payload: JobIn, request: Request, session: Session, principal: Owner
) -> FirstRunOut:
    assert principal.tenant_id is not None
    await service.save_job(
        session,
        tenant_id=principal.tenant_id,
        jobs=list(payload.jobs),
        language_primary=payload.language_primary,
        languages_extra=list(payload.languages_extra),
    )
    await _audit(
        session,
        principal,
        request,
        "first_run.job",
        {"jobs": list(payload.jobs), "language": payload.language_primary},
    )
    return await _out(session, principal.tenant_id)


@router.put(
    "/brief",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Keep the brief and find its follow-up questions",
    description=(
        "A brief with something to read is sent to a worker whose AI writes two to four "
        "follow-up questions for this business, each with the kind of answer it wants "
        "(`questions.status` is `writing` until it answers; poll this resource). A short "
        "brief, or no usable answer from the AI, gets fixed questions about the business "
        "profile's own gaps."
    ),
)
async def put_brief(
    payload: BriefIn, request: Request, session: Session, principal: Owner
) -> FirstRunOut:
    assert principal.tenant_id is not None
    await service.save_brief(session, tenant_id=principal.tenant_id, brief=payload.brief)
    await _audit(
        session, principal, request, "first_run.brief", {"characters": len(payload.brief.strip())}
    )
    return await _out(session, principal.tenant_id)


@router.post(
    "/recordings",
    response_model=RecordingOut,
    status_code=201,
    openapi_extra=_MANAGE,
    summary="Hear one spoken piece of the brief (under 30 seconds)",
    description=(
        f"Up to {MAX_RECORDINGS} pieces per first run. A worker turns it into words "
        "(`status` `heard`, poll `GET /v1/first-run/recordings/{recording_id}`) and deletes the "
        "audio as soon as it has; only the words are kept."
    ),
)
async def post_recording(
    request: Request,
    session: Session,
    principal: Owner,
    file: Annotated[UploadFile, File()],
    language: Annotated[OfferedLanguage, Form()],
) -> RecordingOut:
    assert principal.tenant_id is not None
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in VOICE_CONTENT_TYPES:
        raise ProblemError.business_rule(
            "first_run_recording_kind",
            "We could not play that recording.",
            remediation="Record it again here, or type it.",
        )
    data = await read_bounded_upload(file, MAX_VOICE_BYTES)
    # Local import: `apps.workers.storage` holds the object-store client.
    from apps.workers.storage import kb_object_key, store_kb_object

    recording_id = uuid7()
    key = kb_object_key(
        tenant_id=principal.tenant_id,
        upload_id=recording_id,
        slot="brief",
        suffix=content_type.split("/")[-1][:8],
    )
    await store_kb_object(key=key, data=data, content_type=content_type)
    await service.start_recording(
        session,
        tenant_id=principal.tenant_id,
        recording_id=recording_id,
        language=language,
        object_key=key,
        content_type=content_type,
    )
    await _audit(session, principal, request, "first_run.recording", {"bytes": len(data)})
    found = await service.read_recording(session, recording_id)
    return RecordingOut(
        id=found.id, status=found.status, words=found.words, error_code=found.error_code
    )


@router.get(
    "/recordings/{recording_id}",
    response_model=RecordingOut,
    openapi_extra=_MANAGE,
    summary="One spoken piece of the brief, and what was heard",
)
async def read_recording(recording_id: UUID, session: Session, _: Owner) -> RecordingOut:
    found = await service.read_recording(session, recording_id)
    return RecordingOut(
        id=found.id, status=found.status, words=found.words, error_code=found.error_code
    )


@router.post(
    "/answers",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Answer the follow-up questions",
    description=(
        "Each answer names its question by `id` and uses the field its kind asks for "
        "(`choices` for `choices` and `single_choice`, which takes exactly one; `text` for "
        "`text` and `address`; `services`; `hours`), and is refused with "
        "`first_run_answer_mismatch` otherwise. Every answer is kept with its question and "
        "given to the script writer; one whose question has `maps_to` is also merged into "
        "that business-profile section (`PATCH /v1/business-profile`'s own save), so every "
        "agent of the business learns it. A skipped question is left out."
    ),
)
async def post_answers(
    payload: AnswersIn, request: Request, session: Session, principal: Owner
) -> FirstRunOut:
    assert principal.tenant_id is not None
    sections = await service.answer_questions(
        session,
        tenant_id=principal.tenant_id,
        answers=[
            service.GivenAnswer(
                id=answer.id,
                choices=tuple(answer.choices),
                text=answer.text,
                services=tuple(answer.services),
                hours=None
                if answer.hours is None
                else service.OpenHours(
                    opens=answer.hours.opens,
                    closes=answer.hours.closes,
                    closed=tuple(answer.hours.closed),
                ),
            )
            for answer in payload.answers
        ],
        user_id=principal.client_user_id,
    )
    await _audit(
        session,
        principal,
        request,
        "first_run.answers",
        {"answers": len(payload.answers), "sections": sorted(sections)},
    )
    return await _out(session, principal.tenant_id)


@router.post(
    "/build",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Build the agent from its job and the brief (a worker; poll this resource)",
    description=(
        "The first build creates the agent; a later one rewrites the same agent's script from "
        "a changed brief. Each step (`voice`, `script`, `greeting`, `notice`) is marked as the "
        "worker finishes it."
    ),
)
async def post_build(request: Request, session: Session, principal: Owner) -> FirstRunOut:
    assert principal.tenant_id is not None
    await service.request_build(
        session, tenant_id=principal.tenant_id, user_id=principal.client_user_id
    )
    await _audit(session, principal, request, "first_run.build", {})
    return await _out(session, principal.tenant_id)


@router.put(
    "/name",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Rename the agent before its first call",
)
async def put_name(
    payload: NameIn, request: Request, session: Session, principal: Owner
) -> FirstRunOut:
    assert principal.tenant_id is not None
    await service.rename_agent(
        session, tenant_id=principal.tenant_id, name=payload.name, user_id=principal.client_user_id
    )
    await _audit(session, principal, request, "first_run.renamed", {})
    return await _out(session, principal.tenant_id)


async def _mark(
    marker: Literal["finished", "dismissed"],
    request: Request,
    session: AsyncSession,
    principal: Principal,
) -> FirstRunOut:
    assert principal.tenant_id is not None
    await service.mark(session, tenant_id=principal.tenant_id, marker=marker)
    await _audit(session, principal, request, f"first_run.{marker}", {})
    return await _out(session, principal.tenant_id)


@router.post(
    "/finish",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="The owner has met their agent: stop sending them here",
)
async def post_finish(request: Request, session: Session, principal: Owner) -> FirstRunOut:
    return await _mark("finished", request, session, principal)


@router.post(
    "/dismiss",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Put the first run aside for now; the dashboard still offers it",
)
async def post_dismiss(request: Request, session: Session, principal: Owner) -> FirstRunOut:
    return await _mark("dismissed", request, session, principal)


__all__ = ["router"]
