"""How an agent's voice sounds (`agents/voice_tuning`), for clients and operators: the speed
on any voice (D-884), the rest on a Studio voice. A sample is spoken only for a Studio voice;
a Clear voice's speed is saved and heard on the next call.

    GET   /v1/agents/{aid}/voice-tuning                                speed, loudness, emotion
    PATCH /v1/agents/{aid}/voice-tuning                                set or clear (audited)
    POST  /v1/agents/{aid}/voice-tuning/preview                        hear a sample, unsaved
    GET   /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning            every setting held
    PATCH /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning            set or clear (audited)
    POST  /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning/preview    hear them, unsaved

A client sets speed, loudness and emotion on its own Studio agents (D-843, founder 21 Oct
2026, superseding the 13 Oct operators-only decision); the voice model and pronunciation
dictionary stay with operators, and the client schema has no field for them. The client write
is `org:manage`, the permission `PATCH /v1/agents/{id}` takes to change an agent's voice. Both
doors share `agents/voice_tuning` and reach a live agent through the live apply queued in the
saving transaction.

A preview speaks one line on our voice key, which the provider charges per character, so it
is rate-limited as a costly route and never stored. A client's sample is also capped per
account per IST day (`voice_tuning.CLIENT_PREVIEWS_PER_DAY`), speaks a fixed line rather than
text the client sends, and its cost is ours: no feature meters previews, so each one logs its
character count.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from calevate_shared.engine import ByokVoiceTuning
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import voice_tuning
from apps.api.agents.engine_catalogue_routes import PREVIEW_RESPONSES
from apps.api.agents.hosted_voices import parse_hosted_voice_id, studio_listing_workspace
from apps.api.agents.voice_tuning import Audience, VoiceTuningState
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.thinnest_workspace import in_workspace

log = get_logger(__name__)

Session = Annotated[AsyncSession, Depends(db)]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
AgentOperator = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

router = APIRouter(tags=["agents"])
admin_router = APIRouter(tags=["admin"])

_PREVIEW_TEXT_MAX_CHARS = voice_tuning.PREVIEW_TEXT_MAX_CHARS

_PATH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice-tuning"
_CLIENT_PATH = "/v1/agents/{agent_id}/voice-tuning"
_SPEED_RANGES = (
    f"`speed` is {voice_tuning.SPEED_MIN}-{voice_tuning.SPEED_MAX} in hundredths on a Studio "
    f"voice and {voice_tuning.CLEAR_SPEED_MIN}-{voice_tuning.CLEAR_SPEED_MAX} in steps of "
    f"{voice_tuning.CLEAR_SPEED_STEP} on any other (`options` gives the range in force), 1 "
    "being the voice's own pace. "
)
_DESCRIPTION = (
    "How the agent's voice sounds. "
    + _SPEED_RANGES
    + f"`volume` ({voice_tuning.VOLUME_MIN}-{voice_tuning.VOLUME_MAX}, hundredths); "
    "`emotion`, or null to let the words decide; `model`, the voice model for this agent "
    "alone (null: the key's own); `dictionary_id`, a pronunciation dictionary of our voice "
    "account. Null leaves the voice's default. The older voice model takes no speed, volume "
    "or emotion, and a Studio voice cloned from a long recording keeps its own pace (refused "
    "at publish or preview). Speed applies on any voice; the rest only while the agent's "
    "voice is a Studio one."
)
_CLIENT_DESCRIPTION = (
    "How this agent's voice sounds. "
    + _SPEED_RANGES
    + f"`volume` ({voice_tuning.VOLUME_MIN}-{voice_tuning.VOLUME_MAX}, hundredths) and "
    "`emotion` (one of `options.emotions`, or null to let the words decide) apply to a Studio "
    "voice only. Null leaves the voice's default; a field left out of a PATCH is kept. A "
    "change reaches a live agent from its next call."
)


class VoiceTuningOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The speed range and step of the agent's voice now: Studio's, or a Clear voice's.
    speed_min: Decimal
    speed_max: Decimal
    speed_step: Decimal
    volume_min: Decimal
    volume_max: Decimal
    emotions: list[str]
    models: list[str]
    #: The model that takes no speed, volume or emotion.
    old_model: str
    dictionary_id_pattern: str
    preview_text_max_chars: int


class VoiceTuningOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    #: The agent's configured voice is a Studio one, so these apply to it.
    studio: bool
    speed: Decimal | None
    volume: Decimal | None
    emotion: str | None
    model: str | None
    dictionary_id: str | None
    options: VoiceTuningOptionsOut


class VoiceTuningIn(BaseModel):
    """Every field optional: a field left out is kept, null clears it."""

    model_config = ConfigDict(extra="forbid")

    speed: Decimal | None = Field(default=None, max_digits=4, decimal_places=2)
    volume: Decimal | None = Field(default=None, max_digits=4, decimal_places=2)
    emotion: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=40)
    dictionary_id: str | None = Field(default=None, max_length=80)


class VoiceTuningPreviewIn(VoiceTuningIn):
    """The settings to hear, whatever is saved; `text` is the line (a short greeting in the
    agent's language when left out)."""

    text: str | None = Field(default=None, max_length=_PREVIEW_TEXT_MAX_CHARS)


class ClientVoiceTuningOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The speed range and step of the agent's voice now: Studio's, or a Clear voice's.
    speed_min: Decimal
    speed_max: Decimal
    speed_step: Decimal
    volume_min: Decimal
    volume_max: Decimal
    emotions: list[str]
    previews_per_day: int


class ClientVoiceTuningOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    #: The agent's configured voice is a Studio one, so these apply to it.
    studio: bool
    speed: Decimal | None
    volume: Decimal | None
    #: Null: the words decide.
    emotion: str | None
    options: ClientVoiceTuningOptionsOut
    #: Samples this account may still hear today (IST); null when that cannot be read now.
    previews_left_today: int | None


class ClientVoiceTuningIn(BaseModel):
    """Speed, loudness and emotion only (D-843). Every field optional: a field left out is
    kept, null clears it. `extra="forbid"` is what refuses the operator-only fields."""

    model_config = ConfigDict(extra="forbid")

    speed: Decimal | None = Field(default=None, max_digits=4, decimal_places=2)
    volume: Decimal | None = Field(default=None, max_digits=4, decimal_places=2)
    emotion: str | None = Field(default=None, max_length=40)


def _options(studio: bool) -> VoiceTuningOptionsOut:
    speed_min, speed_max, speed_step = voice_tuning.speed_range(studio=studio)
    return VoiceTuningOptionsOut(
        speed_min=speed_min,
        speed_max=speed_max,
        speed_step=speed_step,
        volume_min=voice_tuning.VOLUME_MIN,
        volume_max=voice_tuning.VOLUME_MAX,
        emotions=list(voice_tuning.EMOTIONS),
        models=list(voice_tuning.VOICE_MODELS),
        old_model=voice_tuning.OLD_VOICE_MODEL,
        dictionary_id_pattern=voice_tuning.DICTIONARY_ID_PATTERN,
        preview_text_max_chars=_PREVIEW_TEXT_MAX_CHARS,
    )


def _out(state: VoiceTuningState) -> VoiceTuningOut:
    tuning = state.tuning
    return VoiceTuningOut(
        agent_id=state.agent_id,
        studio=state.studio,
        speed=tuning.speed,
        volume=tuning.volume,
        emotion=tuning.emotion,
        model=tuning.model,
        dictionary_id=tuning.dictionary_id,
        options=_options(state.studio),
    )


async def _client_out(state: VoiceTuningState, tenant_id: UUID) -> ClientVoiceTuningOut:
    tuning = state.tuning
    speed_min, speed_max, speed_step = voice_tuning.speed_range(studio=state.studio)
    return ClientVoiceTuningOut(
        agent_id=state.agent_id,
        studio=state.studio,
        speed=tuning.speed,
        volume=tuning.volume,
        emotion=tuning.emotion,
        options=ClientVoiceTuningOptionsOut(
            speed_min=speed_min,
            speed_max=speed_max,
            speed_step=speed_step,
            volume_min=voice_tuning.VOLUME_MIN,
            volume_max=voice_tuning.VOLUME_MAX,
            emotions=list(voice_tuning.EMOTIONS),
            previews_per_day=voice_tuning.CLIENT_PREVIEWS_PER_DAY,
        ),
        previews_left_today=await voice_tuning.client_previews_left(tenant_id),
    )


def _changes(payload: BaseModel) -> dict[str, Any]:
    return {f: getattr(payload, f) for f in voice_tuning.FIELDS if f in payload.model_fields_set}


def _audit_summary(state: VoiceTuningState, moved: tuple[str, ...]) -> dict[str, Any]:
    return {"changed": list(moved), **{f: _audit_value(getattr(state.tuning, f)) for f in moved}}


def _audit_value(value: object) -> str | None:
    return None if value is None else str(value)


def _not_studio(audience: Audience) -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="voice_tuning_needs_studio_voice",
        title="These settings are for Studio voices",
        detail="This agent's voice is not a Studio one, so there is nothing to hear.",
        remediation="Choose a Studio voice for the agent first."
        if audience == "operator"
        else "Choose a Studio voice for the agent in Voice first.",
    )


def _preview_unavailable(
    audience: Audience, *, code: str, title: str, detail: str, fix: str
) -> ProblemError:
    """An operator reads the ground they can fix; a client reads that samples are not
    available, with no workspace or platform named (D-679)."""
    if audience == "client":
        return ProblemError(
            kind="business_rule",
            code=code,
            title="Samples are not available right now",
            detail="This voice cannot be played as a sample at the moment. Your saved settings "
            "still apply to calls.",
            remediation="Try again later. If it keeps happening, contact us.",
        )
    return ProblemError(
        kind="business_rule", code=code, title=title, detail=detail, remediation=fix
    )


async def _speaking_engine(audience: Audience) -> tuple[HostsVoices, str | None]:
    """The engine and the workspace a Studio voice is spoken in, or a refusal."""
    engine = get_engine()
    if not isinstance(engine, HostsVoices):
        raise _preview_unavailable(
            audience,
            code="voices_not_hosted",
            title="This voice platform does not host its own voices",
            detail="Voices on this deployment come from Calevate's own catalogue.",
            fix="Manage voices from the Voices panel instead.",
        )
    found = await studio_listing_workspace(engine)
    if found is None:
        raise _preview_unavailable(
            audience,
            code="studio_preview_no_workspace",
            title="No workspace runs Studio yet",
            detail="A Studio voice is spoken on our key in a workspace where it is switched "
            "on, and none answers as ready.",
            fix="Run Studio ready, then try again.",
        )
    return engine, found.workspace


def _audio(data: bytes, content_type: str) -> Response:
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


# --- the client's door (D-843) -----------------------------------------------------------


@router.get(
    _CLIENT_PATH,
    response_model=ClientVoiceTuningOut,
    openapi_extra=permission_meta("agents:read"),
    summary="How this agent's Studio voice sounds",
    description=_CLIENT_DESCRIPTION,
)
async def get_agent_voice_tuning(
    agent_id: UUID, session: Session, principal: AgentReader
) -> ClientVoiceTuningOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    state = await voice_tuning.read_voice_tuning(session, agent_id)
    return await _client_out(state, principal.tenant_id)


@router.patch(
    _CLIENT_PATH,
    response_model=ClientVoiceTuningOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set how this agent's Studio voice sounds",
    description=_CLIENT_DESCRIPTION,
)
async def set_agent_voice_tuning(
    agent_id: UUID,
    payload: ClientVoiceTuningIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> ClientVoiceTuningOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    state, moved = await voice_tuning.set_voice_tuning(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        changes=_changes(payload),
        audience="client",
    )
    if moved:
        await write_audit(
            session,
            action="agent.voice_tuning_set",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary=_audit_summary(state, moved),
        )
    return await _client_out(state, principal.tenant_id)


_SAMPLE_SQL = (
    "SELECT a.language_primary, a.direction, o.name FROM agents a "
    "JOIN organizations o ON o.id = a.tenant_id WHERE a.id = :aid AND a.deleted_at IS NULL"
)


@router.post(
    f"{_CLIENT_PATH}/preview",
    response_class=Response,
    openapi_extra=permission_meta("org:manage"),
    summary="Hear this agent's Studio voice with these settings, unsaved",
    description=(
        "Speaks one fixed sample line in the agent's main language, in its Studio voice, with "
        "the speed, loudness and emotion sent (the saved ones are not read). "
        f"{voice_tuning.CLIENT_PREVIEWS_PER_DAY} samples per account per day (India time); "
        "past that it is refused with `voice_preview_daily_cap`. Refused while the agent's "
        "voice is not a Studio one."
    ),
    responses=PREVIEW_RESPONSES,
)
async def preview_agent_voice_tuning(
    agent_id: UUID, payload: ClientVoiceTuningIn, principal: Owner
) -> Response:
    tenant_id = principal.tenant_id
    assert tenant_id is not None  # client realm; `requires()` resolves it
    sent = voice_tuning.tuning_of(_changes(payload))
    # Read and released before the engine round trip: no transaction is held open across a
    # vendor call.
    async with tenant_session(tenant_id) as scoped:
        state = await voice_tuning.read_voice_tuning(scoped, agent_id)
        language, direction, business = (
            await scoped.execute(text(_SAMPLE_SQL), {"aid": agent_id})
        ).one()
    # The operator's model and dictionary are part of how the voice sounds on calls, so the
    # sample keeps them; only what the client sets is taken from the request.
    tuning = ByokVoiceTuning(
        speed=sent.speed,
        volume=sent.volume,
        emotion=sent.emotion,
        model=state.tuning.model,
        dictionary_id=state.tuning.dictionary_id,
    )
    voice_tuning.refuse_invalid_tuning(tuning, audience="client")
    ref = parse_hosted_voice_id(state.voice_id)
    if not state.studio or ref is None:
        raise _not_studio("client")
    engine, workspace = await _speaking_engine("client")
    line = voice_tuning.sample_line(
        language=str(language) if language else None,
        direction=str(direction),
        business=str(business),
    )
    await voice_tuning.take_client_preview(tenant_id)
    try:
        with in_workspace(workspace):
            audio = await engine.preview_own_key_voice(
                voice_id=ref.vendor_id,
                text=line,
                language=str(language) if language else None,
                tuning=tuning,
            )
    except Exception:
        await voice_tuning.refund_client_preview(tenant_id)
        raise
    log.info(
        "client_voice_preview_spoken",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            # The engine's own greeting when no line of ours fits; its length is not ours.
            "characters": len(line) if line else None,
        },
    )
    return _audio(audio.data, audio.content_type)


# --- the operator's door -----------------------------------------------------------------


@admin_router.get(
    _PATH,
    response_model=VoiceTuningOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="How a Studio voice sounds on one client agent",
    description=_DESCRIPTION,
)
async def admin_get_voice_tuning(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: Operator
) -> VoiceTuningOut:
    async with tenant_session(tenant_id) as scoped:
        state = await voice_tuning.read_voice_tuning(scoped, agent_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return _out(state)


@admin_router.patch(
    _PATH,
    response_model=VoiceTuningOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set how a Studio voice sounds on one client agent (audited)",
    description=_DESCRIPTION,
)
async def admin_set_voice_tuning(
    tenant_id: UUID,
    agent_id: UUID,
    payload: VoiceTuningIn,
    request: Request,
    principal: AgentOperator,
) -> VoiceTuningOut:
    changes = _changes(payload)
    async with tenant_session(tenant_id) as scoped:
        state, moved = await voice_tuning.set_voice_tuning(
            scoped, tenant_id=tenant_id, agent_id=agent_id, changes=changes
        )
        if moved:
            await write_audit(
                scoped,
                action="admin.agent_voice_tuning_set",
                actor=principal,
                tenant_id=tenant_id,
                object_type="agent",
                object_id=str(agent_id),
                ip=client_request_ip(request),
                summary=_audit_summary(state, moved),
            )
    return _out(state)


_LANGUAGE_SQL = "SELECT language_primary FROM agents WHERE id = :aid AND deleted_at IS NULL"


@admin_router.post(
    f"{_PATH}/preview",
    response_class=Response,
    openapi_extra=permission_meta("agents:write"),
    summary="Hear a Studio voice on one client agent with these settings, unsaved",
    description=(
        "Speaks one short line in the agent's Studio voice with the settings sent (the saved "
        "ones are not read), on our voice key, which the provider charges per character. "
        "Refused while the agent's voice is not a Studio one, or while no workspace runs "
        "Studio."
    ),
    responses=PREVIEW_RESPONSES,
)
async def admin_preview_voice_tuning(
    tenant_id: UUID,
    agent_id: UUID,
    payload: VoiceTuningPreviewIn,
    request: Request,
    principal: AgentOperator,
) -> Response:
    tuning = voice_tuning.tuning_of(_changes(payload))
    voice_tuning.refuse_invalid_tuning(tuning)
    async with tenant_session(tenant_id) as scoped:
        state = await voice_tuning.read_voice_tuning(scoped, agent_id)
        language = (await scoped.execute(text(_LANGUAGE_SQL), {"aid": agent_id})).scalar()
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    ref = parse_hosted_voice_id(state.voice_id)
    if not state.studio or ref is None:
        raise _not_studio("operator")
    engine, workspace = await _speaking_engine("operator")
    line = (payload.text or "").strip() or None
    with in_workspace(workspace):
        audio = await engine.preview_own_key_voice(
            voice_id=ref.vendor_id,
            text=line,
            language=str(language) if language else None,
            tuning=tuning,
        )
    log.info(
        "admin_voice_preview_spoken",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "characters": len(line) if line else None,
        },
    )
    return _audio(audio.data, audio.content_type)


__all__ = ["admin_router", "router"]
