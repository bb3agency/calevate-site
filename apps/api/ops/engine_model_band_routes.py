"""The per-minute band of each of the engine's own models, recorded by an operator.

    GET  /v1/ops/engine-model-bands                       every model the engine lists as
                                                           able to answer a call on our plan,
                                                           with its recorded band or null
    POST /v1/ops/engine-model-bands/{engine}/{model_id}   record one; step-up
                                                           `record_engine_model_band:<engine>:<model_id>`

ThinnestAI's API does not say which models lift a call to its Premium band; its console does.
An operator reads the tag there and records it here, the same act as attesting an engine's
minute price (`ops/engine_minute_routes.py`): step-up bound to the subject, audit row in the
same transaction, append-only history. Until a model has a band it is not offered and a
publish on it is refused (`agents/engine_catalogue_offer.py`), and a model recorded as
"premium" is a paid model that is never offered at all (D-750).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.engine_model_bands import (
    ModelBand,
    RecordedBand,
    listed_models,
    record_engine_model_band,
    recorded_bands,
)
from apps.api.agents.llm_tiers import engine_model_token
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.engine import get_engine
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue, HoldsCatalogue

router = APIRouter(prefix="/v1/ops/engine-model-bands", tags=["ops"])

#: `ops:manage`, beside the hosted-voice curation (`ops/hosted_voice_routes.py`): deciding
#: what the client pickers may offer on the engine. Superadmin-only, like `platform:config`,
#: which the minute-price attestation uses (`core/rbac.SUPERADMIN_ONLY_PERMISSIONS`).
PERMISSION: Final = "ops:manage"

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
BandOperator = Annotated[Principal, Depends(requires(PERMISSION, realm="admin"))]
EngineId = Annotated[str, Path(max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")]
#: Engine model ids carry dots ("composer-v0.1", "qwen3.6-27b").
ModelId = Annotated[str, Path(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]


def engine_model_band_confirmation(engine: str, model_id: str) -> str:
    """The step-up string, bound to the engine AND the model so a captured header cannot
    re-band another model."""
    return f"record_engine_model_band:{engine}:{model_id}"


class EngineModelBandOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str
    #: The engine's raw model id: what the POST path takes.
    model_id: str
    #: The opaque id the agent's model list carries for this model
    #: (`GET /v1/agents/engine-catalogue`), so a screen can match its rows to these.
    catalogue_id: str
    #: The engine's own name for the model, as its console shows it.
    label: str
    #: The band in force: "none" (included in the per-minute price, so it may be offered) or
    #: "premium" (paid, never offered, D-750); null when nobody has recorded one ("not
    #: checked yet"), and then the model is not offered either.
    band: ModelBand | None
    recorded_at: str | None
    #: The admin who recorded the band in force; null for a row carried over by migration.
    recorded_by: str | None
    source_note: str | None
    #: The reply latency the engine's console shows, in milliseconds, when on record.
    latency_ms: int | None
    #: May an agent on a Studio voice use it (the engine's `voiceOnlyByok`)?
    usable_with_studio_voice: bool


class EngineModelBandsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The selected engine, or null when it runs no models of its own.
    engine: str | None
    #: Does the selected engine run models of its own whose band can be recorded?
    available: bool
    #: False when the engine's model list was cut short; the rows shown are still real.
    complete: bool
    models: list[EngineModelBandOut]
    as_of: str


class EngineModelBandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    band: ModelBand
    #: Where the band was read: "console model dropdown, 11 Oct 2026".
    source_note: str | None = Field(default=None, max_length=500)

    @field_validator("source_note")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if len(stripped) < 3:
            raise ValueError("say where the band was read, or leave the note empty")
        return stripped


def _row(engine: str, model: CatalogueModel, recorded: RecordedBand | None) -> EngineModelBandOut:
    band = recorded.band if recorded is not None else None
    return EngineModelBandOut(
        engine=engine,
        model_id=model.model_id,
        catalogue_id=engine_model_token(model.model_id),
        label=model.label,
        band=band,
        recorded_at=recorded.recorded_at.isoformat() if recorded is not None else None,
        recorded_by=recorded.recorded_by if recorded is not None else None,
        source_note=recorded.source_note if recorded is not None else None,
        latency_ms=model.console_latency_ms,
        usable_with_studio_voice=model.voice_only_byok,
    )


def _catalogue_engine(engine: str) -> HoldsCatalogue:
    """The selected engine when it is `engine` and runs models of its own, else a 404: a band
    is recorded against the live list, so it cannot be recorded for an engine not running."""
    selected = get_engine()
    if selected.name != engine or not isinstance(selected, HoldsCatalogue):
        raise ProblemError(
            kind="not_found",
            code="engine_model_band_unknown_engine",
            title="This voice platform's models cannot be banded here",
            detail=(
                f"{engine!r} is not the selected voice platform, or it runs no models of its own."
            ),
        )
    return selected


def _listed_model(catalogue: EngineCatalogue, model_id: str) -> CatalogueModel:
    model = next((m for m in catalogue.models if m.model_id == model_id), None)
    if model is None:
        if not catalogue.complete:
            raise ProblemError(
                kind="dependency",
                code="engine_catalogue_incomplete",
                title="The voice platform's model list could not be read in full",
                detail="This model was not on the part of the list that was read.",
                remediation="Try again in a minute.",
            )
        raise ProblemError(
            kind="not_found",
            code="engine_model_not_in_catalogue",
            title="The voice platform does not list this model",
            detail=f"{model_id!r} is not on the voice platform's model list.",
        )
    if not (model.call_capable and model.plan_allows):
        raise ProblemError.business_rule(
            "engine_model_not_listed",
            "The voice platform says this model cannot answer a call on our plan, so it is "
            "never offered and has no band to record.",
        )
    return model


@router.get(
    "",
    response_model=EngineModelBandsOut,
    openapi_extra=permission_meta(PERMISSION),
    summary="Every engine model that can answer a call, with its recorded per-minute band",
)
async def list_engine_model_bands(session: GlobalSession, _: BandOperator) -> EngineModelBandsOut:
    at = datetime.now(UTC)
    engine = get_engine()
    if not isinstance(engine, HoldsCatalogue):
        return EngineModelBandsOut(
            engine=None, available=False, complete=True, models=[], as_of=at.isoformat()
        )
    catalogue = await engine.read_catalogue()
    bands = await recorded_bands(session, engine=engine.name)
    return EngineModelBandsOut(
        engine=engine.name,
        available=True,
        complete=catalogue.complete,
        models=[
            _row(engine.name, m, bands.get(m.model_id)) for m in listed_models(catalogue.models)
        ],
        as_of=at.isoformat(),
    )


@router.post(
    "/{engine}/{model_id}",
    response_model=EngineModelBandOut,
    openapi_extra=permission_meta(PERMISSION),
    summary="Record one engine model's per-minute band (step-up confirmed, audited)",
    description=(
        "Records the band the voice platform's console shows for one of its models as a NEW "
        "row; the newest row is in force. `none`: the model is included in the per-minute "
        "price and may be offered. `premium`: the model lifts a call to a dearer band, so it "
        "is a paid model and is never offered (Calevate offers only models included in the "
        "per-minute price). Requires `X-Confirm-Action: "
        "record_engine_model_band:<engine>:<model_id>`. Only a model the platform lists as "
        "able to answer a call on our plan can be recorded."
    ),
)
async def record_engine_model_band_route(
    payload: EngineModelBandIn,
    session: GlobalSession,
    request: Request,
    principal: BandOperator,
    engine: EngineId,
    model_id: ModelId,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> EngineModelBandOut:
    step_up.require(x_confirm_action, engine_model_band_confirmation(engine, model_id))
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="engine_model_band_actor_unknown",
            title="This session has no admin identity",
            detail="A recorded band has to be attributable to an operator.",
        )
    holder = _catalogue_engine(engine)
    model = _listed_model(await holder.read_catalogue(), model_id)
    recorded = await record_engine_model_band(
        session,
        engine=engine,
        model_id=model_id,
        band=payload.band,
        source_note=payload.source_note,
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="platform.engine_model_band_recorded",
        actor=principal,
        object_type="platform_engine_model_bands",
        object_id=f"{engine}:{model_id}",
        ip=client_request_ip(request),
        summary={
            "engine": engine,
            "model_id": model_id,
            "band": recorded.band,
            "source_note": recorded.source_note,
        },
    )
    return _row(engine, model, recorded)


__all__ = ["PERMISSION", "engine_model_band_confirmation", "router"]
