"""The owned-runtime settlement prices from the server's own record, and refuses crossed ids.

What is pinned here, each against the route a real worker posts to:

1. The LLM leg is priced as the model the agent's PUBLISHED configuration version names,
   never as whatever `meta["model"]` the worker sends, and the ledger row says which.
2. The TTS leg is priced from the operator-attested price for that configuration's voice
   provider; with none it is refused and parked, and the re-metering sweep bills it once a
   price is on file.
3. A configuration version that is not this agent's is refused.
4. A later body naming a different agent than the one a call was minted under is refused,
   and so is a batch whose events name a different call than the path's ref.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.billing.rates import LlmPriceAttestation, install_llm_price_attestations
from apps.api.db.session import tenant_session
from apps.api.ops.model_pricing import TtsPriceAttestation
from apps.api.worker import service
from apps.workers.remetering import remeter_refused_legs
from calevate_shared.events import CallEvent
from calevate_shared.worker_api import MeteredQuantity, ObservationBatch, SettlementRequest
from sqlalchemy import text
from tests.remetering_test import UNPRICED_MODEL, published_agent
from tests.worker_api_harness import call_ref, declare_pipecat_engine, worker_client
from voice_worker.api_client import WorkerApiError

pytestmark = [pytest.mark.rls]

TOKENS = Decimal("12.5")
KCHARS = Decimal("3.2")
#: An attested Cartesia rate, INR per 1,000 characters, with four decimal places so the
#: NUMERIC column is exercised rather than a round number.
CARTESIA_RATE = Decimal("3.4496")


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from declare_pipecat_engine(monkeypatch)


@pytest.fixture(autouse=True)
def _no_ambient_attestations() -> Iterator[None]:
    install_llm_price_attestations(None)
    yield
    install_llm_price_attestations(None)


def _tts_price_on_file(monkeypatch: pytest.MonkeyPatch, *, attested: bool) -> None:
    """`platform_tts_prices` is one global, append-only table shared by every test process,
    so the price on file is supplied at the one seam the settlement reads it through."""

    async def _prices(_session: object, *, at: datetime) -> dict[str, TtsPriceAttestation]:
        if not attested:
            return {}
        return {
            "cartesia": TtsPriceAttestation(
                provider="cartesia",
                inr_per_1k_chars=CARTESIA_RATE,
                effective_from=at,
                attested_at=at,
                attested_by="ops@calevate.test",
                source_note="test invoice",
            )
        }

    monkeypatch.setattr(service, "attested_tts_prices", _prices)


def _attest_llm() -> None:
    install_llm_price_attestations(
        lambda: {
            UNPRICED_MODEL: LlmPriceAttestation(
                model=UNPRICED_MODEL,
                input_usd_per_mtok=Decimal("1.00"),
                output_usd_per_mtok=Decimal("1.00"),
                read_on=datetime(2026, 9, 19, tzinfo=UTC).date(),
                attested_by="ops@calevate.test",
                source="vendor invoice INV-2026-09",
            )
        }
    )


def _settlement(
    agent_id: uuid.UUID, *quantities: MeteredQuantity, **extra: object
) -> SettlementRequest:
    return SettlementRequest(
        final_status="completed",
        direction="inbound",
        agent_id=agent_id,
        quantities=list(quantities),
        **extra,  # type: ignore[arg-type]
    )


def _llm(model_in_meta: str) -> MeteredQuantity:
    return MeteredQuantity(
        leg="llm", unit_type="llm_ktok_in", qty=TOKENS, meta={"model": model_in_meta}
    )


def _tts() -> MeteredQuantity:
    return MeteredQuantity(leg="tts", unit_type="tts_kchars", qty=KCHARS, meta={})


async def _usage(tenant_id: uuid.UUID, ref: str) -> list[tuple[str, Decimal, dict[str, str]]]:
    async with tenant_session(tenant_id) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT u.unit_type, u.unit_cost_paid, u.meta FROM usage_events u "
                    "JOIN calls c ON c.id = u.call_id WHERE c.engine_call_id = :c "
                    "ORDER BY u.unit_type"
                ),
                {"c": ref},
            )
        ).all()
    return [
        (str(r[0]), Decimal(str(r[1])), r[2] if isinstance(r[2], dict) else json.loads(r[2]))
        for r in rows
    ]


async def _call_row(tenant_id: uuid.UUID, ref: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
    return uuid.UUID(str(row_id))


# --- 1. the LLM leg ------------------------------------------------------------------


async def test_the_worker_cannot_choose_the_model_its_tokens_are_priced_at(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The published model is unattested, so the leg is refused — even though the worker's
    meta names `gpt-4o-mini`, a model the catalogue prices from a verified vendor reading."""
    _tts_price_on_file(monkeypatch, attested=False)
    tenant_id, agent_id, _ = await published_agent()
    _call, ref = call_ref(tenant_id)
    async with worker_client() as api:
        answer = await api.post_settlement(ref, _settlement(agent_id, _llm("gpt-4o-mini")))
    assert answer.rows_written == 0
    assert answer.refusals_recorded == 1
    assert await _usage(tenant_id, ref) == []


async def test_the_ledger_row_names_the_published_model_it_was_priced_as(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tts_price_on_file(monkeypatch, attested=False)
    _attest_llm()
    tenant_id, agent_id, _ = await published_agent()
    _call, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_settlement(ref, _settlement(agent_id, _llm("something-else")))
    [(unit, cost, meta)] = await _usage(tenant_id, ref)
    assert unit == "llm_ktok_in"
    assert cost == Decimal("0.0957")
    assert meta["llm_model"] == UNPRICED_MODEL
    assert "model" not in meta, "the worker's own claim reached an append-only row"


async def test_a_configuration_version_of_another_agent_is_refused(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tts_price_on_file(monkeypatch, attested=False)
    tenant_id, agent_id, _ = await published_agent()
    _call, ref = call_ref(tenant_id)
    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as refused:
            await api.post_settlement(
                ref, _settlement(agent_id, agent_config_version_id=uuid.uuid4())
            )
    assert "422" in str(refused.value)


# --- 2. the TTS leg ------------------------------------------------------------------


async def test_an_attested_voice_price_meters_the_characters_at_that_rate(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tts_price_on_file(monkeypatch, attested=True)
    tenant_id, agent_id, _ = await published_agent()
    _call, ref = call_ref(tenant_id)
    async with worker_client() as api:
        answer = await api.post_settlement(ref, _settlement(agent_id, _tts()))
    assert answer.rows_written == 1
    [(unit, cost, meta)] = await _usage(tenant_id, ref)
    assert unit == "tts_kchars"
    assert cost == CARTESIA_RATE
    assert meta["tts_provider"] == "cartesia"
    assert meta["voice_tier"] == "studio", "the rung the other engines stamp is missing"
    assert Decimal(meta["total_inr"]) == CARTESIA_RATE * KCHARS


async def test_an_unattested_voice_is_parked_and_metered_once_a_price_arrives(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tts_price_on_file(monkeypatch, attested=False)
    tenant_id, agent_id, _ = await published_agent()
    _call, ref = call_ref(tenant_id)
    async with worker_client() as api:
        answer = await api.post_settlement(ref, _settlement(agent_id, _tts()))
    assert answer.rows_written == 0
    row_id = await _call_row(tenant_id, ref)
    async with tenant_session(tenant_id) as db:
        keys = (
            (
                await db.execute(
                    text("SELECT dedupe_key FROM outbox_messages WHERE dedupe_key LIKE :k"),
                    {"k": f"remeter:{row_id}:%"},
                )
            )
            .scalars()
            .all()
        )
    assert keys == [f"remeter:{row_id}:tts:tts_kchars"]

    await remeter_refused_legs({})
    assert await _usage(tenant_id, ref) == [], "a leg with no price on file was metered"

    _tts_price_on_file(monkeypatch, attested=True)
    await remeter_refused_legs({})
    await remeter_refused_legs({})
    [(unit, cost, meta)] = await _usage(tenant_id, ref)
    assert (unit, cost, meta["tts_provider"]) == ("tts_kchars", CARTESIA_RATE, "cartesia")


# --- 3. crossed ids --------------------------------------------------------------------


async def _second_agent(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    """A second agent in the SAME tenant, copied from the first."""
    other = uuid.uuid4()
    async with tenant_session(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO agents SELECT (jsonb_populate_record(NULL::agents, "
                "to_jsonb(a) || jsonb_build_object('id', CAST(:new AS text), "
                "'engine_agent_ref', NULL, 'name', 'second agent'))).* "
                "FROM agents a WHERE a.id = :aid"
            ),
            {"new": str(other), "aid": agent_id},
        )
    return other


async def test_a_later_body_naming_another_agent_of_the_tenant_is_refused(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tts_price_on_file(monkeypatch, attested=False)
    tenant_id, agent_id, _ = await published_agent()
    other = await _second_agent(tenant_id, agent_id)
    call_id, ref = call_ref(tenant_id)
    event = CallEvent(
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        status="in_progress",
        engine="pipecat",
    )
    async with worker_client() as api:
        await api.post_observations(
            ref, ObservationBatch(agent_id=agent_id, direction="inbound", events=[event])
        )
        with pytest.raises(WorkerApiError) as refused:
            await api.post_settlement(ref, _settlement(other))
    assert "422" in str(refused.value)


async def test_a_batch_about_another_call_than_the_ref_is_refused(
    worker_token: None,
) -> None:
    tenant_id, agent_id, _ = await published_agent()
    _call_id, ref = call_ref(tenant_id)
    event = CallEvent(
        call_id="some-other-call",
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        status="in_progress",
        engine="pipecat",
    )
    async with worker_client() as api:
        with pytest.raises(WorkerApiError) as refused:
            await api.post_observations(
                ref, ObservationBatch(agent_id=agent_id, direction="inbound", events=[event])
            )
    assert "422" in str(refused.value)
