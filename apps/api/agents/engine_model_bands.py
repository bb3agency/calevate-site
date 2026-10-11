"""The per-minute band of each of an engine's own models, as an operator recorded it.

ThinnestAI's `GET /models` says whether a model can answer a call, whether our plan may pick
it and whether it may run beside our own voice key, but not whether it lifts a call to a
dearer band (snapshots/2026-10-08/pages/api-reference/models/list-models.md:463-505). The
band is read off its console by an operator and recorded in `platform_engine_model_bands`
(founder decision, 11 Oct 2026); the newest row per (engine, model_id) is in force.

The adapter stays free of database access: `HoldsCatalogue.read_catalogue` returns the
vendor's facts with no band, and every caller that prices, offers or checks a model reads the
catalogue through `banded_catalogue`, which fills `surcharge` and `tier` from the record. A
model with no record keeps `surcharge=None` and is never offered (hard rule 7,
`agents/engine_catalogue_offer.py`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, cast, get_args

from calevate_shared.engine import LlmTier
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue, HoldsCatalogue

ModelBand = Literal["none", "premium"]
MODEL_BANDS: Final[tuple[str, ...]] = get_args(ModelBand)

#: Our tier word for a model's band (D-680): no surcharge is Standard, Premium is Plus.
TIER_OF_BAND: Final[Mapping[ModelBand, LlmTier]] = {"none": "standard", "premium": "plus"}


@dataclass(frozen=True, slots=True)
class RecordedBand:
    model_id: str
    band: ModelBand
    recorded_at: datetime
    #: The operator's admin id; None on a row carried over by migration.
    recorded_by: str | None
    source_note: str | None


async def recorded_bands(session: AsyncSession, *, engine: str) -> dict[str, RecordedBand]:
    """The band in force for every model of `engine` that has one, keyed by raw model id."""
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (model_id) model_id, band, recorded_at, recorded_by, "
                "source_note FROM platform_engine_model_bands WHERE engine = :engine "
                "ORDER BY model_id, seq DESC"
            ),
            {"engine": engine},
        )
    ).all()
    return {
        str(row[0]): RecordedBand(
            model_id=str(row[0]),
            band=cast("ModelBand", row[1]),
            recorded_at=row[2],
            recorded_by=None if row[3] is None else str(row[3]),
            source_note=row[4],
        )
        for row in rows
    }


def with_recorded_bands(
    catalogue: EngineCatalogue, bands: Mapping[str, RecordedBand]
) -> EngineCatalogue:
    """The catalogue with each model's band and tier taken from the record, and only from it:
    a model with no record has neither, whatever the adapter returned."""
    models = []
    for model in catalogue.models:
        recorded = bands.get(model.model_id)
        band = recorded.band if recorded is not None else None
        models.append(
            model.model_copy(
                update={
                    "surcharge": band,
                    "tier": TIER_OF_BAND[band] if band is not None else None,
                }
            )
        )
    return catalogue.model_copy(update={"models": models})


async def banded_catalogue(
    session: AsyncSession, holder: HoldsCatalogue, *, engine: str
) -> EngineCatalogue:
    """THE read of an engine's catalogue for anything that offers, prices or checks a model."""
    catalogue = await holder.read_catalogue()
    return with_recorded_bands(catalogue, await recorded_bands(session, engine=engine))


def listed_models(models: Sequence[CatalogueModel]) -> list[CatalogueModel]:
    """The models a picker or the ops band screen lists: the ones the engine says can answer
    a call AND our plan may pick. The others could never be chosen, so they are left out
    rather than shown greyed (founder decision, 11 Oct 2026)."""
    return [m for m in models if m.call_capable and m.plan_allows]


def pickable_models(models: Sequence[CatalogueModel]) -> list[CatalogueModel]:
    """The models an agent's Model section lists: `listed_models` less every model recorded as
    paid. Calevate sells only models included in the per-minute price (founder, 11 Oct 2026,
    D-750), so a paid model is hidden like one that cannot answer a call. A model not checked
    yet stays, so an operator can record it from the agent's screen."""
    return [m for m in listed_models(models) if m.surcharge in (None, "none")]


async def record_engine_model_band(
    session: AsyncSession,
    *,
    engine: str,
    model_id: str,
    band: ModelBand,
    source_note: str | None,
    actor_id: object,
) -> RecordedBand:
    """Record one band as a NEW row. Never an UPDATE.

    The caller MUST be step-up confirmed and MUST write the audit row on this session —
    `billing/engine_minutes.attest_engine_minute_price`'s contract, because it is the same
    act: an operator puts their name to a figure this deployment cannot read for itself.
    """
    if band not in MODEL_BANDS:
        raise ProblemError(
            kind="validation",
            code="engine_model_band_unknown",
            title="No such band",
            detail=f"A model's band is one of {', '.join(MODEL_BANDS)}.",
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_engine_model_bands "
                "(engine, model_id, band, recorded_by, source_note) "
                "VALUES (:engine, :model, :band, :by, :note) RETURNING recorded_at"
            ),
            {
                "engine": engine,
                "model": model_id,
                "band": band,
                "by": actor_id,
                "note": source_note,
            },
        )
    ).one()
    return RecordedBand(
        model_id=model_id,
        band=band,
        recorded_at=row[0],
        recorded_by=str(actor_id),
        source_note=source_note,
    )


__all__ = [
    "MODEL_BANDS",
    "TIER_OF_BAND",
    "ModelBand",
    "RecordedBand",
    "banded_catalogue",
    "listed_models",
    "pickable_models",
    "record_engine_model_band",
    "recorded_bands",
    "with_recorded_bands",
]
