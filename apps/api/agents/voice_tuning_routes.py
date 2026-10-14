"""How a Studio voice sounds on one agent, for operators (`agents/voice_tuning`).

    GET   /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning            the settings held
    PATCH /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning            set or clear (audited)
    POST  /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning/preview    hear them, unsaved

Admin only (founder decision, 13 Oct 2026): a client neither sees nor sets these. The write
is the agent write permission, like the operator's call-handling door, and it reaches a live
agent through the live apply queued in the saving transaction. The preview speaks one short
line on our voice key, which the provider charges per character, so it is rate-limited as a
costly route and never stored.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from apps.api.agents import voice_tuning
from apps.api.agents.engine_catalogue_routes import PREVIEW_RESPONSES
from apps.api.agents.hosted_voices import parse_hosted_voice_id, studio_listing_workspace
from apps.api.agents.voice_tuning import VoiceTuningState
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.thinnest_workspace import in_workspace

AgentOperator = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

admin_router = APIRouter(tags=["admin"])

#: The engine caps a spoken preview line, as the ops preview does (the adapter refuses longer).
_PREVIEW_TEXT_MAX_CHARS = 200

_PATH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice-tuning"
_DESCRIPTION = (
    "How a Studio voice sounds on this agent. `speed` "
    f"({voice_tuning.SPEED_MIN}-{voice_tuning.SPEED_MAX}) and `volume` "
    f"({voice_tuning.VOLUME_MIN}-{voice_tuning.VOLUME_MAX}), 1 being the voice's own, in "
    "hundredths; `emotion` (English calls only); `model`, the voice model for this agent alone "
    "(null: the key's own); `dictionary_id`, a pronunciation dictionary of our voice account. "
    "Null leaves the voice's default. The older voice model takes no speed, volume or "
    "emotion, and a voice cloned from a long recording keeps its own pace (refused at publish "
    "or preview). They apply only while the agent's voice is a Studio one."
)


class VoiceTuningOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speed_min: Decimal
    speed_max: Decimal
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


def _options() -> VoiceTuningOptionsOut:
    return VoiceTuningOptionsOut(
        speed_min=voice_tuning.SPEED_MIN,
        speed_max=voice_tuning.SPEED_MAX,
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
        options=_options(),
    )


def _changes(payload: BaseModel) -> dict[str, Any]:
    return {f: getattr(payload, f) for f in voice_tuning.FIELDS if f in payload.model_fields_set}


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
                summary={
                    "changed": list(moved),
                    **{f: _audit_value(getattr(state.tuning, f)) for f in moved},
                },
            )
    return _out(state)


def _audit_value(value: object) -> str | None:
    return None if value is None else str(value)


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
        raise ProblemError(
            kind="business_rule",
            code="voice_tuning_needs_studio_voice",
            title="These settings are for Studio voices",
            detail="This agent's voice is not a Studio one, so there is nothing to hear.",
            remediation="Choose a Studio voice for the agent first.",
        )
    engine = get_engine()
    if not isinstance(engine, HostsVoices):
        raise ProblemError(
            kind="business_rule",
            code="voices_not_hosted",
            title="This voice platform does not host its own voices",
            detail="Voices on this deployment come from Calevate's own catalogue.",
            remediation="Manage voices from the Voices panel instead.",
        )
    found = await studio_listing_workspace(engine)
    if found is None:
        raise ProblemError(
            kind="business_rule",
            code="studio_preview_no_workspace",
            title="No workspace runs Studio yet",
            detail="A Studio voice is spoken on our key in a workspace where it is switched "
            "on, and none answers as ready.",
            remediation="Run Studio ready, then try again.",
        )
    with in_workspace(found.workspace):
        audio = await engine.preview_own_key_voice(
            voice_id=ref.vendor_id,
            text=(payload.text or "").strip() or None,
            language=str(language) if language else None,
            tuning=tuning,
        )
    return Response(
        content=audio.data,
        media_type=audio.content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


__all__ = ["admin_router"]
