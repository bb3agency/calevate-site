"""The new owner's first run, "Meet your agent" (D-855).

    GET  /v1/first-run                       where the owner is, and whether it is still due
    PUT  /v1/first-run/job                   the job and the languages
    PUT  /v1/first-run/brief                 the brief; queues the follow-up questions
    POST /v1/first-run/documents             a knowledge upload added as a brief document
    DELETE /v1/first-run/documents/{id}      stop reading one for the brief (it stays knowledge)
    POST /v1/first-run/recordings            one spoken piece of the brief (under 30 s)
    GET  /v1/first-run/recordings/{id}       what was heard
    POST /v1/first-run/answers               the follow-up answers, into the business profile
    PUT  /v1/first-run/agent                 name and voice: make the agent (no script), and
                                             have Pip save the company training as version 1
    POST /v1/first-run/work                  what first: draft a line or a campaign; Pip
                                             writes and saves its script (Phase 3b)
    POST /v1/first-run/build                 the agent built from a written script (before
                                             Phase 3b; the screen no longer calls it)
    PUT  /v1/first-run/name                  rename the agent before its first call
    POST /v1/first-run/finish | /dismiss     done, or put aside for now

All `org:manage`: building the account's first agent is the owner's act, the same permission
`POST /v1/agents` takes. Uploading a recording is NOT the knowledge base's `kb:write`, because
it teaches no agent anything: its words come back into the brief box. A DOCUMENT is the
opposite: it is uploaded through `POST /v1/kb/uploads` under that route's own permission, and
the documents routes only record that the brief step added it (D-918). Every write is audited
with names and counts, never the words (hard rule 6).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.default_agent import read_default_agent
from apps.api.agents.languages import OfferedLanguage
from apps.api.agents.starters import StarterJob
from apps.api.agents.voice_pick import gender_of, pick_voice
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.first_run import service, work
from apps.api.first_run.models import (
    BUILD_STEPS,
    MAX_BUILD_RUNS,
    MAX_DOCUMENTS,
    MAX_RECORDINGS,
    BuildStep,
)
from apps.api.first_run.schemas import (
    AgentIn,
    AnswersIn,
    BriefIn,
    BuildOut,
    BuildStepOut,
    DefaultAgentOut,
    DocumentIn,
    DocumentOut,
    FirstRunOut,
    JobIn,
    LeftOutOut,
    NameIn,
    QuestionOut,
    QuestionsOut,
    RecordingOut,
    WorkIn,
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
        documents_used=int(found.get("documents_used", 0)),
        left_out=[LeftOutOut.model_validate(item) for item in found.get("left_out") or []],
    )


async def _out(session: AsyncSession, tenant_id: UUID) -> FirstRunOut:
    state = await service.read_state(session, tenant_id=tenant_id)
    default = await read_default_agent(session)
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
        documents=[
            DocumentOut(
                upload_id=doc.upload_id,
                name=doc.name,
                source_kind=doc.source_kind,
                state=doc.state,
                detail=doc.detail,
                reaches_agents=doc.reaches_agents,
            )
            for doc in state.documents
        ],
        documents_left=max(0, MAX_DOCUMENTS - len(state.documents)),
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
        line_id=state.line_id,
        campaign_id=state.campaign_id,
        default_agent=DefaultAgentOut(
            name=default.name, voice_id=default.voice_id, gender=default.gender
        ),
    )


def _may_spend_ai(principal: Principal) -> bool:
    """Pip's drafts here spend the account's dashboard AI allowance, which a view-as session
    may not (`billing.ai_assist`); the step itself still goes ahead without them."""
    try:
        assert_view_as_may(principal, "billing.ai_assist")
    except ProblemError:
        return False
    return True


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
        "A brief with something to read is sent to a worker whose AI writes two or three "
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
    "/documents",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Add a knowledge upload as one of the brief's documents",
    description=(
        f"Up to {MAX_DOCUMENTS}. Upload the file with `POST /v1/kb/uploads` first: it is "
        "ordinary knowledge, read, reviewed and metered like any upload, and every agent uses "
        "it. This records that the brief step added it, so the follow-up questions and the "
        "script are written from its words too (redacted first). Refused with "
        "`first_run_documents_full` past the bound."
    ),
)
async def post_document(
    payload: DocumentIn, request: Request, session: Session, principal: Owner
) -> FirstRunOut:
    assert principal.tenant_id is not None
    await service.add_document(session, tenant_id=principal.tenant_id, upload_id=payload.upload_id)
    await _audit(
        session,
        principal,
        request,
        "first_run.document_added",
        {"upload_id": str(payload.upload_id)},
    )
    return await _out(session, principal.tenant_id)


@router.delete(
    "/documents/{upload_id}",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Stop using one document for the brief",
    description=(
        "The upload stays in the knowledge base; remove it there with "
        "`DELETE /v1/kb/uploads/{upload_id}`."
    ),
)
async def delete_document(
    upload_id: UUID, request: Request, session: Session, principal: Owner
) -> FirstRunOut:
    assert principal.tenant_id is not None
    await service.remove_document(session, tenant_id=principal.tenant_id, upload_id=upload_id)
    await _audit(
        session, principal, request, "first_run.document_removed", {"upload_id": str(upload_id)}
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
    "/agent",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="Name and voice: make the first agent, or rename it before its first call",
    description=(
        "The first time, the agent is made with this name and languages and the default "
        "agent's voice (a woman's voice for its language when the default names none); it has "
        "no script of its own. Pip then drafts the company training from the owner's words "
        "and saves it as version 1, within the account's AI allowance. Later, the same agent "
        "is renamed and its languages changed, until it is set up for calls "
        "(`first_run_rename_after_ready`). Its voice is changed with the voice picker."
    ),
)
async def put_agent(payload: AgentIn, request: Request, principal: Owner) -> FirstRunOut:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with tenant_session(tenant_id) as session:
        held = await service.read_state(session, tenant_id=tenant_id)
        made = await work.agent_status(session, held.agent_id) is not None
        default = await read_default_agent(session)
    voice: dict[str, object] | None = None
    if not made:
        # The admin's voice where this account can use it (Studio open, the language
        # spoken); otherwise the usual ranking, by that voice's gender.
        picked = await pick_voice(
            tenant_id,
            payload.language_primary,
            preferred=default.voice_id,
            gender=gender_of(default.gender) or "female",
        )
        if picked is not None:
            voice = {
                "voice_id": picked.row.voice_id,
                "label": picked.row.label,
                "rung": picked.rung,
                "fallback": picked.fallback,
                "not_female": picked.not_female,
            }
    async with tenant_session(tenant_id) as session:
        await work.save_agent(
            session,
            tenant_id=tenant_id,
            name=payload.name,
            language_primary=payload.language_primary,
            languages_extra=list(payload.languages_extra),
            voice=voice,
            user_id=principal.client_user_id,
            may_spend_ai=_may_spend_ai(principal),
        )
        await _audit(
            session,
            principal,
            request,
            "first_run.agent",
            {"made": not made, "language": payload.language_primary},
        )
        return await _out(session, tenant_id)


@router.post(
    "/work",
    response_model=FirstRunOut,
    openapi_extra=_MANAGE,
    summary="What first: draft an inbound line or a campaign for the agent; Pip writes it",
    description=(
        "`answer_calls` drafts an inbound line in the agent's voice (no number needed); "
        "`call_leads` drafts a campaign. Its main task is the owner's own words, its sources "
        "the files they added, and Pip's script is saved to it as soon as it is written "
        "(poll the line or the campaign). Pressing the same card again returns the same "
        "draft. Refused with `first_run_no_agent` before the agent has a name."
    ),
)
async def post_work(
    payload: WorkIn, request: Request, session: Session, principal: Owner
) -> FirstRunOut:
    assert principal.tenant_id is not None
    await work.start_work(
        session,
        tenant_id=principal.tenant_id,
        job=payload.job,
        user_id=principal.client_user_id,
        may_spend_ai=_may_spend_ai(principal),
    )
    await _audit(session, principal, request, "first_run.work", {"job": payload.job})
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
