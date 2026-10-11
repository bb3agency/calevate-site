"""The voices and models an agent may be put on, where the ENGINE hosts them (D-678, D-687).

For an engine that speaks voices it hosts and runs its own models (`engine/catalogue.
HostsVoices` / `HoldsCatalogue`); on any other engine the answer says there is no such list
and the voice picker at `/v1/agents/voices` is the one to read.

THE VOICES ARE THE OPERATOR'S LIST, NOT THE VENDOR'S. Only voices an operator added and
enabled are returned (`agents/hosted_voices.py`), each with its rung, a language note and
whether a preview can be played; the vendor's live catalogue is read by the sync, never by a
picker render. The models are the engine's live list, operators only: a client chooses a
tier and is sent no models at all (D-679). Only models the engine says can answer a call and
our plan may pick, and that are not recorded as paid (D-750), are listed, each with the band
an operator recorded (`agents/engine_model_bands.py`) and availability from
`agents/engine_catalogue_offer.py`.
Sentences are in the reader's own audience
(`voice_routes._reason_audience` argues the realm rule).

Mounted BEFORE `agents.routes.router`, for `voice_routes.py`'s reason: `/v1/agents/
{agent_id}` would otherwise swallow the literal segment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict

from apps.api.agents.engine_catalogue_offer import offered_models
from apps.api.agents.engine_choice import (
    BYOK_CHOICE_NOTE,
    byok_in_force,
    in_call_default_model,
)
from apps.api.agents.engine_model_bands import pickable_models, recorded_bands, with_recorded_bands
from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    hosted_voice_unofferable_reason,
    offered_hosted_voices,
    preview_object,
    rung_of_source,
    studio_voices_ready,
)
from apps.api.agents.llm_models import LlmReasonAudience
from apps.api.agents.llm_tiers import engine_model_token
from apps.api.agents.voice_offer import tts_price_is_billable
from apps.api.billing.engine_minutes import attested_rate_keys
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import EngineCatalogue, HoldsCatalogue, HostsVoices
from apps.api.engine.hosted_platform import engine_platform_label

router = APIRouter(tags=["agents"])

CatalogueReader = Annotated[Principal, Depends(requires("agents:read"))]

#: How long a browser may keep a preview clip. The bytes for one voice id only change when
#: an operator replaces them, and an hour is what the vendor itself allows for its own
#: preview audio (preview-byok-voice.md:367-370).
PREVIEW_CACHE_CONTROL = "private, max-age=3600"

#: The OpenAPI description of a preview answer: audio bytes, never a JSON body.
PREVIEW_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    200: {
        "description": "The preview audio.",
        "content": {
            "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
            "audio/wav": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


class EngineCatalogueVoiceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Our catalogue id: what `PATCH /v1/agents/{agent_id}` takes as `engine_voice_id`.
    voice_id: str
    label: str
    #: The client price rung a minute on this voice is billed at.
    rung: Literal["clear", "studio"]
    #: Cloned by our account rather than one of the platform's own voices.
    is_custom: bool
    #: What language the voice speaks, in a sentence a client reads.
    language_note: str
    #: A preview clip can be played from `GET /v1/agents/engine-catalogue/preview`.
    preview_available: bool
    offerable: bool
    #: Why it cannot be chosen right now, in the reader's audience. Null exactly when offerable.
    reason: str | None


class EngineCatalogueModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: An OPAQUE id (`llm_tiers.engine_model_token`) in both realms — the one
    #: `AgentOut.engine_model_id` carries and `PATCH /v1/agents/{agent_id}` accepts. An
    #: engine's model ids name the companies that make them (D-679).
    model_id: str
    #: The engine's own name. Operators only: a client is sent no models (D-679).
    label: str
    call_capable: bool
    plan_allows: bool
    #: May an agent on a Studio voice use it? A Studio voice runs the call on the
    #: platform's standard models only, and any other is refused at publish (D-687).
    usable_with_studio_voice: bool
    #: The per-minute band an operator recorded for the model, "none" or "premium", or
    #: null when nobody has (then it is not offered).
    price_band: Literal["none", "premium"] | None = None
    #: The reply latency the platform's console shows, in milliseconds, when on record.
    latency_ms: int | None = None
    offerable: bool
    reason: str | None


class EngineCatalogueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Does the selected voice platform host its own voices? False on every engine whose
    #: voices come from Calevate's catalogue (`/v1/agents/voices`).
    available: bool
    #: False when the platform's model list was cut short; the entries shown are still real.
    complete: bool
    note: str
    #: May an agent choose one of these per agent? False when the platform runs on the
    #: account's own keys (`Settings.thinnest_byok_enabled`), where `choice_note` says why.
    choosable: bool = True
    choice_note: str | None = None
    #: Can this reader put an agent on a Studio voice? False before Studio is ready on this
    #: deployment. A free-trial account may (D-727).
    studio_available: bool = False
    #: Why Studio cannot be chosen, in the reader's words; null when it can. Names no vendor.
    studio_note: str | None = None
    #: What "Platform default" means for an agent on a Clear voice: the in-call model it is
    #: sent when none is chosen (`Settings.thinnest_in_call_default_model`), by the name the
    #: operator is shown. Always null to a client, who reads no model names (D-679), and null
    #: when the platform's own default applies or the model is unlisted.
    default_model_label: str | None = None
    voices: list[EngineCatalogueVoiceOut]
    #: The engine's models that can answer a call on our plan, to an operator. Always empty
    #: to a client, who chooses a tier instead (`/v1/organization/llm-defaults`).
    models: list[EngineCatalogueModelOut]


#: What a client reads while Studio is not ready on this deployment. No vendor name (D-679).
STUDIO_NOT_READY_NOTE: Final = "Studio voices are not available yet."


def _studio_note(*, studio_ready: bool) -> str | None:
    """Why a reader cannot choose a Studio voice, or None. A free-trial account may choose one
    like any other (D-727): its agents speak Studio in our developer workspace."""
    return None if studio_ready else STUDIO_NOT_READY_NOTE


@router.get(
    "/v1/agents/engine-catalogue",
    response_model=EngineCatalogueOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The voices an agent may be put on, and the platform's models, with availability",
    description=(
        "On a voice platform that hosts its own voices: the voices an operator added and "
        "enabled, each with its rung (Clear or Studio), a language note, whether a preview "
        "can be played, and whether it can be chosen right now. To an operator, the "
        "platform's own models that can answer a call on our plan, with their recorded "
        "band; a client is sent no models. On any other platform `available` is false and "
        "the voice picker at `/v1/agents/voices` is the one to read."
    ),
)
async def engine_catalogue(principal: CatalogueReader) -> EngineCatalogueOut:
    engine = get_engine()
    if not isinstance(engine, HostsVoices) or not isinstance(engine, HoldsCatalogue):
        return EngineCatalogueOut(
            available=False,
            complete=True,
            note="Voices on this account come from Calevate's own catalogue.",
            voices=[],
            models=[],
        )
    audience: LlmReasonAudience = "operator" if principal.is_admin else "client"
    platform = engine_platform_label(engine)
    voice_key_priced = tts_price_is_billable(STUDIO_VOICE_PROVIDER)
    # Platform-scoped rows with no RLS, read on their own short session, through the one
    # door that decides whether a minute may be sold (hard rule 7).
    async with untenanted_session() as session:
        attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
        rows = await offered_hosted_voices(session)
        studio_ready = await studio_voices_ready(session)
        bands = await recorded_bands(session, engine=engine.name)
    studio_note = _studio_note(studio_ready=studio_ready)
    is_client = audience == "client"
    # A client chooses a tier, never one of the engine's models, and never reads their
    # names (D-679; the 10 Oct 2026 exception that showed them was revoked 11 Oct 2026), so
    # the client realm does not read the engine's model list at all.
    catalogue = (
        EngineCatalogue(models=[], complete=True)
        if is_client
        else with_recorded_bands(await engine.read_catalogue(), bands)
    )
    models = offered_models(
        catalogue.model_copy(update={"models": pickable_models(catalogue.models)}),
        attested=attested,
        platform=platform,
        audience=audience,
    )
    reasons = [
        hosted_voice_unofferable_reason(
            row,
            attested=attested,
            voice_key_priced=voice_key_priced,
            platform=platform,
            audience=audience,
        )
        for row in rows
    ]
    voices = [
        EngineCatalogueVoiceOut(
            voice_id=row.voice_id,
            label=row.label,
            rung=rung_of_source(engine.name, row.source),
            is_custom=row.is_custom,
            language_note=row.language_note,
            preview_available=row.preview_available,
            offerable=reason is None,
            reason=reason,
        )
        for row, reason in zip(rows, reasons, strict=True)
    ]
    offerable = sum(1 for v in voices if v.offerable)
    byok = byok_in_force(engine)
    default_model = in_call_default_model(engine, voice_id=None)
    default_label = (
        None
        if is_client
        else next((m.label for m in catalogue.models if m.model_id == default_model), None)
    )
    return EngineCatalogueOut(
        available=True,
        complete=catalogue.complete,
        choosable=not byok,
        choice_note=BYOK_CHOICE_NOTE if byok else None,
        studio_available=studio_ready,
        studio_note=studio_note,
        default_model_label=default_label,
        note=(
            f"{offerable} of {len(voices)} voices can be chosen today."
            if voices
            else "No voices have been made available yet."
        ),
        voices=voices,
        models=[
            EngineCatalogueModelOut(
                model_id=engine_model_token(m.model.model_id),
                label=m.model.label,
                call_capable=m.model.call_capable,
                plan_allows=m.model.plan_allows,
                usable_with_studio_voice=m.model.voice_only_byok,
                price_band=m.model.surcharge,
                latency_ms=m.model.console_latency_ms,
                offerable=m.offerable,
                reason=m.reason,
            )
            for m in models
        ],
    )


@router.get(
    "/v1/agents/engine-catalogue/preview",
    response_class=Response,
    openapi_extra=permission_meta("agents:read"),
    summary="Play one voice's preview clip",
    description=(
        "The stored preview audio for one voice, served by Calevate (never a link to the "
        "voice platform). A client may play a voice on offer; an admin impersonating a "
        "client may play any voice that has a preview. A voice with no preview, or one the "
        "reader may not see, is a 404. The ops console plays from "
        "`GET /v1/ops/voices/hosted/preview`."
    ),
    responses=PREVIEW_RESPONSES,
)
async def engine_voice_preview(
    principal: CatalogueReader,
    voice_id: Annotated[str, Query(min_length=1, max_length=255)],
) -> Response:
    return await stored_preview_response(voice_id, offered_only=not principal.is_admin)


async def stored_preview_response(voice_id: str, *, offered_only: bool) -> Response:
    """THE ONE READ of a voice's stored preview, for this route and the ops console's
    (`ops/hosted_voice_routes.hosted_voice_preview`). `offered_only` limits it to a voice on
    the client picker; a voice outside it, with no preview, or whose object is gone, is 404."""
    async with untenanted_session() as session:
        key, content_type = await preview_object(
            session, voice_id=voice_id, offered_only=offered_only
        )
    from apps.workers.storage import read_voice_preview

    data = await read_voice_preview(key)
    if data is None:
        raise ProblemError.not_found("Voice preview")
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": PREVIEW_CACHE_CONTROL, "X-Content-Type-Options": "nosniff"},
    )


__all__ = ["PREVIEW_CACHE_CONTROL", "PREVIEW_RESPONSES", "router", "stored_preview_response"]
