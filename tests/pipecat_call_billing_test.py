"""A call on the owned Pipecat runtime is charged to the client exactly as on every engine.

The worker's settlement writes the call's supplier legs (STT, TTS, LLM) from attested rates,
and until this change the post-call metering stage skipped the call because the adapter's
snapshot carried no `cost`: no wallet debit, no `spend_state` movement, no `telephony_s`
row — so no minutes on the usage panel or the invoice, and no cap could ever arm.

The billable duration is the worker's measured connected time (D-648, founder decision); the
carrier's CDR sets only our cost, as a separate compensating row (D-662). These tests drive
the real settlement route, read the call back through `PipecatEngine.execution` and run the
real metering stage over it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.billing.plans import ist_billing_month, month_pricing_instant
from apps.api.billing.service import (
    BASE_OVERAGE_RUNG,
    LEDGER_RUNG_KEY,
    rate_card_at,
    usage_summary,
    voice_tier_usage,
)
from apps.api.compliance.service import spend_capped
from apps.api.db.session import tenant_session
from apps.api.engine.pipecat import PipecatEngine
from apps.workers.pipeline import _meter
from calevate_shared.events import CallEvent
from calevate_shared.worker_api import (
    MeteredQuantity,
    ObservationBatch,
    SettlementRefusal,
    SettlementRequest,
)
from sqlalchemy import text
from tests.conftest import fund_wallet
from tests.worker_api_harness import (
    call_ref,
    declare_pipecat_engine,
    published_agent,
    worker_client,
)

pytestmark = [pytest.mark.rls]

#: One and a half minutes, so a per-minute price and a per-second quantity both show.
_SECONDS = 90


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from declare_pipecat_engine(monkeypatch)


async def _settled_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    seconds: int,
    final_status: str = "completed",
    measured: bool = True,
    spoken_kchars: Decimal | None = None,
) -> tuple[uuid.UUID, str]:
    """A call the worker observed for `seconds` and settled with the carrier leg refused."""
    call_id, ref = call_ref(tenant_id)
    ended = datetime.now(UTC)
    event = CallEvent(
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        direction="inbound",
        status=final_status,  # type: ignore[arg-type]
        engine="pipecat",
        started_at=ended - timedelta(seconds=seconds),
        ended_at=ended,
    )
    request = SettlementRequest(
        final_status=final_status,  # type: ignore[arg-type]
        direction="inbound",
        agent_id=agent_id,
        refusals=[
            SettlementRefusal(
                leg="carrier",
                code="meter_carrier_cdr_missing",
                detail="no carrier CDR was supplied, so the connected duration has no witness.",
                remediation="Retrieve the CDR from the carrier and meter again.",
            )
        ],
        quantities=(
            [MeteredQuantity(leg="stt", unit_type="stt_min", qty=Decimal("1.5"))]
            if measured
            else []
        )
        + (
            [MeteredQuantity(leg="tts", unit_type="tts_kchars", qty=spoken_kchars)]
            if spoken_kchars is not None
            else []
        ),
    )
    async with worker_client() as api:
        await api.post_observations(
            ref,
            ObservationBatch(agent_id=agent_id, direction="inbound", events=[event], turns=[]),
        )
        await api.post_settlement(ref, request)
    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
    return uuid.UUID(str(row_id)), ref


async def _meter_it(tenant_id: uuid.UUID, row_id: uuid.UUID, ref: str) -> int:
    """The post-call pipeline's step 5, over the snapshot the adapter really returns."""
    snapshot = await PipecatEngine().get_execution(ref)
    assert snapshot is not None
    return await _meter(tenant_id, row_id, snapshot)


async def _balance(tenant_id: uuid.UUID) -> Decimal:
    async with tenant_session(tenant_id) as db:
        total = (
            await db.execute(
                text("SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    return Decimal(str(total))


async def _set_tier(tenant_id: uuid.UUID, tier: str) -> None:
    async with tenant_session(tenant_id) as db:
        await db.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": tier, "i": tenant_id},
        )


async def _spend_state(tenant_id: uuid.UUID) -> tuple[Decimal, Decimal, Decimal, bool]:
    async with tenant_session(tenant_id) as db:
        row = (
            await db.execute(
                text(
                    "SELECT minutes_used, spend_used, billed_inr, capped FROM spend_state "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).one()
    return Decimal(row[0]), Decimal(row[1]), Decimal(row[2]), bool(row[3])


async def test_a_settled_pipecat_call_debits_the_wallet_on_its_published_voice_tier(
    worker_token: None,
) -> None:
    tenant_id, agent_id, _ = await published_agent()
    await fund_wallet(tenant_id, "500.00")
    before = await _balance(tenant_id)
    row_id, ref = await _settled_call(tenant_id, agent_id, seconds=_SECONDS)

    assert await _meter_it(tenant_id, row_id, ref) > 0

    month = ist_billing_month(datetime.now(UTC))
    async with tenant_session(tenant_id) as db:
        # The published agent speaks Cartesia, which bills on the Studio rung; a funded
        # wallet with no lots is priced at the card's list rate for that rung.
        card = await rate_card_at(db, at=month_pricing_instant(month))
        rate = card.list_rates().rate_for("studio")
        usage = await voice_tier_usage(db, tenant_id=tenant_id, month=month)
        summary = await usage_summary(db, tenant_id=tenant_id, month=month)
        telephony = (
            await db.execute(
                text(
                    "SELECT qty, unit_cost_paid, meta FROM usage_events "
                    "WHERE call_id = :c AND unit_type = 'telephony_s'"
                ),
                {"c": row_id},
            )
        ).one()

    charged = before - await _balance(tenant_id)
    assert charged == (Decimal("1.5") * rate).quantize(Decimal("0.01")) > 0
    assert usage.by_voice["studio"].minutes == Decimal("1.5")
    assert usage.by_voice["studio"].charged_inr == charged
    assert usage.by_voice["clear"].minutes == 0

    # ONE number feeds the wallet and the invoice: the same seconds, on the base rung.
    assert Decimal(telephony[0]) == _SECONDS
    assert telephony[1] is None, "the carrier's cost is unknown until a CDR is read"
    assert telephony[2][LEDGER_RUNG_KEY] == BASE_OVERAGE_RUNG
    assert telephony[2]["voice_tier"] == "studio"
    assert telephony[2]["duration_source"] == "worker_settlement"
    assert Decimal(str(summary["minutes_used"])) == Decimal("1.5")

    minutes, spend, billed, _capped = await _spend_state(tenant_id)
    assert minutes == Decimal("1.5")
    assert billed == charged, "spend_state must accrue exactly what the wallet was debited"
    assert spend == Decimal("0.75"), "our cost is the settled STT leg: 1.5 min at ₹0.50"


async def test_re_running_the_pipeline_does_not_charge_twice(worker_token: None) -> None:
    tenant_id, agent_id, _ = await published_agent()
    await fund_wallet(tenant_id, "500.00")
    row_id, ref = await _settled_call(tenant_id, agent_id, seconds=_SECONDS)

    assert await _meter_it(tenant_id, row_id, ref) > 0
    after_first = (await _balance(tenant_id), await _spend_state(tenant_id))
    assert await _meter_it(tenant_id, row_id, ref) == 0, "the replay must meter nothing"

    assert (await _balance(tenant_id), await _spend_state(tenant_id)) == after_first
    async with tenant_session(tenant_id) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT count(*) FROM usage_events WHERE call_id = :c "
                    "AND unit_type = 'telephony_s'"
                ),
                {"c": row_id},
            )
        ).scalar_one()
    assert rows == 1


async def test_a_pipecat_call_that_crosses_the_minute_cap_caps_the_tenant(
    worker_token: None,
) -> None:
    from tests.spend_caps_test import _plan

    tenant_id, agent_id, _ = await published_agent()
    await _set_tier(tenant_id, "managed")
    await _plan(tenant_id, cap_min=1)
    row_id, ref = await _settled_call(tenant_id, agent_id, seconds=_SECONDS)

    await _meter_it(tenant_id, row_id, ref)

    minutes, _spend, _billed, capped = await _spend_state(tenant_id)
    assert minutes == Decimal("1.5")
    assert capped is True
    async with tenant_session(tenant_id) as db:
        assert await spend_capped(db, tenant_id=tenant_id), "the next dial must be refused"


async def test_a_failed_call_is_not_charged_and_a_zero_length_one_charges_nothing(
    worker_token: None,
) -> None:
    tenant_id, agent_id, _ = await published_agent()
    await fund_wallet(tenant_id, "500.00")
    before = await _balance(tenant_id)

    failed_id, failed_ref = await _settled_call(
        tenant_id, agent_id, seconds=_SECONDS, final_status="failed"
    )
    snapshot = await PipecatEngine().get_execution(failed_ref)
    assert snapshot is not None and snapshot.cost is None, "as the fake adapter: no charge"
    assert await _meter(tenant_id, failed_id, snapshot) == 0

    empty_id, empty_ref = await _settled_call(tenant_id, agent_id, seconds=0)
    assert await _meter_it(tenant_id, empty_id, empty_ref) == 1, "the zero-second row only"

    assert await _balance(tenant_id) == before
    minutes, _spend, billed, _capped = await _spend_state(tenant_id)
    assert (minutes, billed) == (Decimal("0"), Decimal("0"))


async def test_a_call_whose_every_leg_was_refused_is_not_left_unmetered(
    worker_token: None,
) -> None:
    """`admin/health.calls_unmetered` stops the account board for a completed call with no
    `usage_events` row. A call the settlement could price nothing on (carrier refused, no
    quantities) has none until the metering stage writes its billable seconds."""
    from apps.api.admin.health import _FACTS, UNMETERED_GRACE

    tenant_id, agent_id, _ = await published_agent()
    await fund_wallet(tenant_id, "500.00")
    row_id, ref = await _settled_call(tenant_id, agent_id, seconds=_SECONDS, measured=False)

    async def unmetered() -> int:
        now = datetime.now(UTC) + UNMETERED_GRACE + timedelta(minutes=1)
        async with tenant_session(tenant_id) as db:
            facts = (
                await db.execute(
                    text(_FACTS),
                    {
                        "window_start": now - timedelta(days=30),
                        "prev_start": now - timedelta(days=60),
                        "unmetered_cutoff": now - UNMETERED_GRACE,
                    },
                )
            ).one()
        return int(facts[7] or 0)

    assert await unmetered() == 1, "settled with every leg refused: nothing on the ledger yet"
    await _meter_it(tenant_id, row_id, ref)
    assert await unmetered() == 0
    minutes, spend, _billed, _capped = await _spend_state(tenant_id)
    assert (minutes, spend) == (Decimal("1.5"), Decimal("0"))


async def _republish_to_clear(tenant_id: uuid.UUID, agent_id: uuid.UUID, ref: str) -> None:
    """Move the agent's PUBLISHED voice from Cartesia (Studio) to Gnani (Clear)."""
    from tests.voice_worker_session_test import _agent_config

    cfg = _agent_config(tenant_id, agent_id)
    cfg = cfg.model_copy(
        update={
            "models": cfg.models.model_copy(
                update={"tts_provider": "gnani", "tts_model": "timbre-v2.5", "tts_voice": "Suhana"}
            )
        }
    )
    await PipecatEngine().update_agent(ref, cfg)
    async with tenant_session(tenant_id) as db:
        provider = (
            await db.execute(
                text(
                    "SELECT v.model_config->>'tts_provider' FROM pipecat_agents p "
                    "JOIN agent_config_versions v ON v.id = p.agent_config_version_id "
                    "WHERE p.agent_id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
    assert provider == "gnani", "the republish must really have moved the published voice"


async def _studio_minutes(tenant_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    month = ist_billing_month(datetime.now(UTC))
    async with tenant_session(tenant_id) as db:
        usage = await voice_tier_usage(db, tenant_id=tenant_id, month=month)
    return usage.by_voice["studio"].minutes, usage.by_voice["clear"].minutes


async def test_a_republish_before_metering_does_not_re_price_the_call(
    worker_token: None,
) -> None:
    """Settled on a Studio (Cartesia) version, republished to Clear (Gnani) before the
    pipeline runs: the call is charged at Studio, the voice it actually spoke. Holds whether
    the settlement priced the TTS leg (a stamped row) or refused it for want of an attested
    price (a parked re-metering demand) — both carry the settled version's provider."""
    tenant_id, agent_id, agent_ref = await published_agent()
    await fund_wallet(tenant_id, "500.00")
    row_id, ref = await _settled_call(
        tenant_id, agent_id, seconds=_SECONDS, spoken_kchars=Decimal("0.5")
    )
    await _republish_to_clear(tenant_id, agent_id, agent_ref)

    await _meter_it(tenant_id, row_id, ref)

    assert await _studio_minutes(tenant_id) == (Decimal("1.5"), Decimal("0"))


async def test_a_call_that_spoke_nothing_falls_back_to_the_published_voice(
    worker_token: None,
) -> None:
    """No settled TTS row and no parked demand: the only record left is the published config."""
    tenant_id, agent_id, agent_ref = await published_agent()
    await fund_wallet(tenant_id, "500.00")
    row_id, ref = await _settled_call(tenant_id, agent_id, seconds=_SECONDS)
    await _republish_to_clear(tenant_id, agent_id, agent_ref)

    await _meter_it(tenant_id, row_id, ref)

    assert await _studio_minutes(tenant_id) == (Decimal("0"), Decimal("1.5"))
