"""The engine's own voice and model catalogue goes through an offer seam (hard rule 7).

A voice on a band nobody has attested a rupee rate for is shown and refused by name, never
offered; with no base rate nothing is offered; a model the engine calls too slow for a
phone, or one the account's plan does not include, says so. The route answers "no such
catalogue" on any engine that does not publish one, so the Pipecat path reads nothing new.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from apps.api.agents import engine_catalogue_offer as offer
from apps.api.agents.engine_catalogue_routes import engine_catalogue
from apps.api.agents.llm_tiers import engine_model_token
from apps.api.billing import engine_minutes
from apps.api.core.context import Principal
from apps.api.engine.catalogue import CatalogueModel, CatalogueVoice, EngineCatalogue
from apps.api.engine.fake import FakeEngine

PRIYA = CatalogueVoice(voice_id="priya", label="Priya", price_band="premium")
ANJALI = CatalogueVoice(voice_id="3b7e", label="Anjali", price_band="standard")
PRANA = CatalogueModel(model_id="prana-voice", label="Prana", call_capable=True, plan_allows=True)
SLOW = CatalogueModel(model_id="gpt-4.1", label="GPT-4.1", call_capable=False, plan_allows=False)
LOCKED = CatalogueModel(model_id="gpt-x", label="X", call_capable=True, plan_allows=False)

NOTHING: frozenset[str] = frozenset()
BASE_AND_STANDARD = frozenset({"platform", "standard"})
EVERY_BAND = frozenset({"platform", "standard", "premium", "studio"})
SOLD = frozenset({"premium"})


def test_with_nothing_attested_nothing_is_offered() -> None:
    voices, models = offer.offered_catalogue(
        EngineCatalogue(voices=[PRIYA], models=[PRANA], complete=True),
        attested=NOTHING,
        platform="ThinnestAI",
        audience="operator",
    )
    assert not voices[0].offerable and not models[0].offerable
    assert "ThinnestAI" in (voices[0].reason or "")


def test_a_band_rate_without_the_base_rate_offers_nothing() -> None:
    reason = offer.voice_unofferable_reason(
        ANJALI, attested=frozenset({"standard"}), platform="T", audience="operator"
    )
    assert reason is not None and "platform rate" in reason


def test_an_unattested_band_is_refused_by_name_and_an_attested_one_is_offered() -> None:
    reason = offer.voice_unofferable_reason(
        PRIYA, attested=BASE_AND_STANDARD, platform="ThinnestAI", audience="operator"
    )
    assert reason is not None and "'premium'" in reason
    assert (
        offer.voice_unofferable_reason(
            ANJALI, attested=BASE_AND_STANDARD, platform="ThinnestAI", audience="operator"
        )
        is None
    )


def test_a_client_never_reads_the_vendor_name() -> None:
    for attested in (NOTHING, frozenset({"platform"})):
        reason = offer.voice_unofferable_reason(
            PRIYA, attested=attested, platform="ThinnestAI", audience="client"
        )
        assert reason is not None and "ThinnestAI" not in reason
    for model in (SLOW, LOCKED):
        reason = offer.model_unofferable_reason(
            model, attested=frozenset({"platform"}), platform="ThinnestAI", audience="client"
        )
        assert reason is not None and "ThinnestAI" not in reason


def test_model_grounds_are_the_engines_own_statements() -> None:
    base = frozenset({"platform"})
    assert (
        offer.model_unofferable_reason(PRANA, attested=base, platform="T", audience="operator")
        is None
    )
    slow = offer.model_unofferable_reason(SLOW, attested=base, platform="T", audience="operator")
    assert slow is not None and "too slow" in slow
    locked = offer.model_unofferable_reason(
        LOCKED, attested=base, platform="T", audience="operator"
    )
    assert locked is not None and "plan" in locked


def test_a_band_that_is_not_sold_is_refused_whatever_is_attested() -> None:
    for band_voice in (ANJALI, PRIYA.model_copy(update={"price_band": "studio"})):
        client = offer.voice_unofferable_reason(
            band_voice, attested=EVERY_BAND, platform="ThinnestAI", audience="client", sold=SOLD
        )
        assert client == "This voice is not on offer yet."
        operator = offer.voice_unofferable_reason(
            band_voice, attested=EVERY_BAND, platform="ThinnestAI", audience="operator", sold=SOLD
        )
        assert operator is not None and "Premium" in operator
    assert (
        offer.voice_unofferable_reason(
            PRIYA, attested=EVERY_BAND, platform="ThinnestAI", audience="client", sold=SOLD
        )
        is None
    )


# --- the route ---------------------------------------------------------------------


class _CatalogueEngine(FakeEngine):
    async def read_catalogue(self) -> EngineCatalogue:
        return EngineCatalogue(voices=[PRIYA, ANJALI], models=[PRANA, SLOW], complete=False)


def _selected(instance: FakeEngine) -> Iterator[None]:
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


def _client() -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")


async def test_the_route_reads_nothing_on_an_engine_without_a_catalogue() -> None:
    for _ in _selected(FakeEngine()):
        out = await engine_catalogue(_client())
    assert out.available is False and out.voices == [] and out.models == []


async def test_the_route_lists_every_entry_with_its_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    async def _billable(session: Any, *, engine: str, rate_key: str, at: datetime) -> bool:
        asked.append(engine)
        return rate_key in EVERY_BAND

    monkeypatch.setattr(engine_minutes, "engine_minute_is_billable", _billable)
    for _ in _selected(_CatalogueEngine(name="thinnest")):
        out = await engine_catalogue(_client())
    assert set(asked) == {"thinnest"}
    assert out.available is True and out.complete is False
    by_id = {v.voice_id: v for v in out.voices}
    # D-681: on ThinnestAI only Premium is sold, so the attested Standard voice is still off.
    assert by_id["priya"].offerable and by_id["priya"].reason is None
    assert not by_id["3b7e"].offerable
    assert by_id["3b7e"].reason == offer.NOT_ON_OFFER_CLIENT
    assert [m.offerable for m in out.models] == [True, False]
    assert "1 of 2" in out.note


async def test_a_client_reads_tiers_and_opaque_ids_never_the_engines_model_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-679/D-680: an engine's model ids and names are the names of the companies that make
    them, so a client reads our tier word and an opaque id. The operator keeps the engine's
    own name; the id is opaque in both realms so a read-back always matches a picker row."""

    async def _billable(session: Any, *, engine: str, rate_key: str, at: datetime) -> bool:
        return rate_key in BASE_AND_STANDARD

    monkeypatch.setattr(engine_minutes, "engine_minute_is_billable", _billable)
    tiered = PRANA.model_copy(update={"tier": "standard"})
    unnamed = SLOW.model_copy(update={"tier": None})

    class _Tiered(FakeEngine):
        async def read_catalogue(self) -> EngineCatalogue:
            return EngineCatalogue(voices=[ANJALI], models=[tiered, unnamed], complete=True)

    operator = Principal(realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="superadmin")
    for _ in _selected(_Tiered(name="thinnest")):
        client_view = await engine_catalogue(_client())
        operator_view = await engine_catalogue(operator)

    assert [m.label for m in client_view.models] == ["Standard", "Additional model 1"]
    assert [m.model_id for m in client_view.models] == [
        engine_model_token("prana-voice"),
        engine_model_token("gpt-4.1"),
    ]
    body = client_view.model_dump_json().lower()
    for leaked in ("prana", "gpt", "4.1"):
        assert leaked not in body, leaked
    # Voice names are voices, not vendors, and stay.
    assert client_view.voices[0].label == "Anjali"

    assert [m.label for m in operator_view.models] == ["Prana", "GPT-4.1"]
    assert [m.model_id for m in operator_view.models] == [m.model_id for m in client_view.models]


def test_the_adapter_classifies_the_models_it_knows() -> None:
    from apps.api.engine import thinnest

    assert thinnest._MODEL_TIERS == {
        "prana-voice": "standard",
        "gpt-5-mini": "plus",
        "gpt-4.1": "pro",
    }
    assert len(set(thinnest._MODEL_TIERS.values())) == len(thinnest._MODEL_TIERS)
