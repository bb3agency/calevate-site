"""The engine's OWN voice and model catalogue, each entry with its availability.

For an engine that speaks its own voices and runs its own models
(`apps.api.engine.catalogue.HoldsCatalogue`); on any other engine the answer says there
is no such catalogue and the voice picker at `/v1/agents/voices` is the one to read.
Availability comes from `agents/engine_catalogue_offer.py`, the offer seam for this
catalogue, with the sentence in the reader's own audience (`voice_routes._reason_audience`
argues the realm rule).

Mounted BEFORE `agents.routes.router`, for `voice_routes.py`'s reason: `/v1/agents/
{agent_id}` would otherwise swallow the literal segment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from apps.api.agents.engine_catalogue_offer import offered_catalogue
from apps.api.agents.engine_choice import BYOK_CHOICE_NOTE, byok_in_force
from apps.api.agents.llm_models import LlmReasonAudience
from apps.api.agents.llm_tiers import engine_model_labels, engine_model_token
from apps.api.billing.engine_minutes import attested_rate_keys, sold_rate_keys
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HoldsCatalogue
from apps.api.engine.hosted_platform import engine_platform_label

router = APIRouter(tags=["agents"])

CatalogueReader = Annotated[Principal, Depends(requires("agents:read"))]


class EngineCatalogueVoiceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str
    label: str
    #: The engine's price band for a call on this voice.
    price_band: str
    is_custom: bool
    offerable: bool
    #: Why it cannot be chosen, in the reader's audience. Null exactly when offerable.
    reason: str | None


class EngineCatalogueModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: An OPAQUE id (`llm_tiers.engine_model_token`) in both realms — the one
    #: `AgentOut.engine_model_id` carries and `PATCH /v1/agents/{agent_id}` accepts. An
    #: engine's model ids name the companies that make them (D-679).
    model_id: str
    #: The engine's own name to an operator; to a client, OUR tier word (D-680).
    label: str
    call_capable: bool
    plan_allows: bool
    offerable: bool
    reason: str | None


class EngineCatalogueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Does the selected voice platform publish its own catalogue? False on every engine
    #: whose voices come from Calevate's catalogue (`/v1/agents/voices`).
    available: bool
    #: False when the platform's list was cut short; the entries shown are still real.
    complete: bool
    note: str
    #: May an agent choose one of these per agent? False when the platform runs on the
    #: account's own keys (`Settings.thinnest_byok_enabled`), where `choice_note` says why.
    choosable: bool = True
    choice_note: str | None = None
    voices: list[EngineCatalogueVoiceOut]
    models: list[EngineCatalogueModelOut]


@router.get(
    "/v1/agents/engine-catalogue",
    response_model=EngineCatalogueOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The voice platform's own voices and models, each with its availability",
)
async def engine_catalogue(principal: CatalogueReader) -> EngineCatalogueOut:
    engine = get_engine()
    if not isinstance(engine, HoldsCatalogue):
        return EngineCatalogueOut(
            available=False,
            complete=True,
            note="Voices on this account come from Calevate's own catalogue.",
            voices=[],
            models=[],
        )
    audience: LlmReasonAudience = "operator" if principal.is_admin else "client"
    platform = engine_platform_label(engine)
    catalogue = await engine.read_catalogue()
    # Platform-scoped rows with no RLS, read on their own short session, through the one
    # door that decides whether a minute may be sold (hard rule 7).
    at = datetime.now(UTC)
    async with untenanted_session() as session:
        attested = await attested_rate_keys(session, engine=engine.name, at=at)
    voices, models = offered_catalogue(
        catalogue,
        attested=attested,
        platform=platform,
        audience=audience,
        sold=sold_rate_keys(engine.name),
    )
    client_labels = engine_model_labels(catalogue.models)
    is_client = audience == "client"
    offerable = sum(1 for v in voices if v.offerable)
    byok = byok_in_force(engine)
    return EngineCatalogueOut(
        available=True,
        complete=catalogue.complete,
        choosable=not byok,
        choice_note=BYOK_CHOICE_NOTE if byok else None,
        note=(
            f"{offerable} of {len(voices)} voices can be chosen today."
            if voices
            else "The voice platform listed no voices."
        ),
        voices=[
            EngineCatalogueVoiceOut(
                voice_id=v.voice.voice_id,
                label=v.voice.label,
                price_band=v.voice.price_band,
                is_custom=v.voice.is_custom,
                offerable=v.offerable,
                reason=v.reason,
            )
            for v in voices
        ],
        models=[
            EngineCatalogueModelOut(
                model_id=engine_model_token(m.model.model_id),
                label=client_labels[m.model.model_id] if is_client else m.model.label,
                call_capable=m.model.call_capable,
                plan_allows=m.model.plan_allows,
                offerable=m.offerable,
                reason=m.reason,
            )
            for m in models
        ],
    )


__all__ = ["router"]
