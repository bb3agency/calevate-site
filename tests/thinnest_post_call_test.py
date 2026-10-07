"""A ThinnestAI call through the post-call pipeline, and its minutes at an attested rate.

The inbound case is the one the plan exists for: `GET /calls/{id}` answers 404 for a call the
API did not place (`thinnest-findings/mirror/pages/api-reference/get-call.md:50-52`), so the
signed `call.analysed` delivery — sealed by voice-runtime — is the only record of it. The
vendor is an `httpx.MockTransport` that answers exactly that 404.

Money: no cost field (get-call.md:199-204), so `unit_cost_paid` = billed minutes x the
operator-attested ₹/min, in 30-second pulses (evaluation §2, FOUNDER-RELAYED).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.billing.engine_minutes import (
    attest_engine_minute_price,
    attested_minute_prices,
    billed_minutes,
    engine_minute_is_billable,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.reliability.engine_intake_keys import seal_delivery
from apps.workers import pipeline
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant
from tests.thinnest_intake_security_test import _analysed

ENGINE = "thinnest"


def test_billed_minutes_round_up_to_the_pulse() -> None:
    assert billed_minutes(Decimal(182), pulse_s=30) == Decimal("3.5")
    assert billed_minutes(Decimal(180), pulse_s=30) == Decimal("3")
    assert billed_minutes(Decimal(1), pulse_s=30) == Decimal("0.5")
    assert billed_minutes(Decimal(0), pulse_s=30) == Decimal(0)
    assert billed_minutes(Decimal(-5), pulse_s=30) == Decimal(0)


async def _operator() -> UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _attest(rate_key: str, inr: str, *, ago: timedelta = timedelta(minutes=1)) -> None:
    actor = await _operator()
    async with untenanted_session() as session:
        await attest_engine_minute_price(
            session,
            engine=ENGINE,
            rate_key=rate_key,
            inr_per_min=Decimal(inr),
            # Strictly before the call ends, and distinct per run.
            effective_from=datetime(2026, 10, 6, 4, tzinfo=UTC)
            - ago
            - timedelta(microseconds=uuid.uuid4().int % 1_000_000),
            source_note="ThinnestAI invoice TEST-1, BYOK minute",
            actor_id=actor,
        )


async def test_attestation_refuses_what_it_cannot_meter() -> None:
    actor = await _operator()
    async with untenanted_session() as session:
        for engine, key, inr, code in (
            ("thinnest", "platform", "0", "engine_minute_price_not_positive"),
            # Positive, but NUMERIC(12,4) would store it as ₹0.0000 per minute.
            ("thinnest", "platform", "0.00001", "attested_price_not_meterable"),
            ("thinnest", "gold", "1", "engine_minute_price_unknown_rate_key"),
            ("pipecat", "platform", "1", "engine_minute_price_unknown_engine"),
        ):
            with pytest.raises(ProblemError) as refused:
                await attest_engine_minute_price(
                    session,
                    engine=engine,
                    rate_key=key,
                    inr_per_min=Decimal(inr),
                    effective_from=datetime.now(UTC),
                    source_note="invoice",
                    actor_id=actor,
                )
            assert refused.value.code == code


async def test_a_second_price_at_the_same_instant_is_a_conflict_not_an_edit() -> None:
    actor = await _operator()
    instant = datetime(2026, 10, 6, 3, tzinfo=UTC) - timedelta(
        microseconds=uuid.uuid4().int % 3_600_000_000
    )

    async def attest(inr: str) -> None:
        async with untenanted_session() as session:
            await attest_engine_minute_price(
                session,
                engine=ENGINE,
                rate_key="standard",
                inr_per_min=Decimal(inr),
                effective_from=instant,
                source_note="ThinnestAI invoice TEST-2",
                actor_id=actor,
            )

    await attest("2.00")
    with pytest.raises(ProblemError) as refused:
        await attest("2.10")
    assert refused.value.code == "engine_minute_price_duplicate_instant"
    async with untenanted_session() as session:
        stored = (await attested_minute_prices(session, engine=ENGINE, at=instant))["standard"]
    assert stored.inr_per_min == Decimal("2.00")
    assert stored.effective_from == instant


async def test_a_naive_instant_is_refused_because_it_has_no_month() -> None:
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await attested_minute_prices(session, engine=ENGINE, at=datetime(2026, 10, 6, 4))


async def test_the_door_is_closed_until_a_rate_is_attested() -> None:
    later = datetime(2026, 10, 6, 4, tzinfo=UTC)
    async with untenanted_session() as session:
        before = await engine_minute_is_billable(
            session, engine=ENGINE, rate_key="premium", at=datetime(2000, 1, 1, tzinfo=UTC)
        )
    assert before is False
    await _attest("premium", "2.50")
    async with untenanted_session() as session:
        assert await engine_minute_is_billable(session, engine=ENGINE, rate_key="premium", at=later)


# --- the pipeline ----------------------------------------------------------------


@pytest.fixture
def thinnest(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The adapter on a vendor that knows no call by id, plus stubbed storage."""
    state: dict[str, Any] = {"archive": {}, "enqueued": [], "gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.startswith("/api/v1/calls/"):
            state["gets"] += 1
            return httpx.Response(404, json={"error": "Not found"})
        return httpx.Response(500)

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://app.thinnest.ai/api/v1"
        ),
    )
    monkeypatch.setattr(pipeline, "get_engine", lambda: engine)

    async def _copy(
        *, source_url: str, tenant_id: UUID, call_id: UUID, leg: str = "call", **fetch: Any
    ) -> str:
        # The authenticated recording endpoint on the vendor's own host, with its rules.
        assert source_url.startswith("https://app.thinnest.ai/api/v1/calls/")
        assert source_url.endswith("/recording")
        assert fetch["rules"].allowed_hosts == frozenset({"app.thinnest.ai"})
        return f"recordings/{tenant_id}/{call_id}.wav"

    async def _archive(**kw: Any) -> str:
        key = f"engine-payloads/{kw['tenant_id']}/{kw['call_id']}/x.json"
        state["archive"][key] = kw["document"]
        return key

    async def _read(key: str) -> bytes | None:
        return state["archive"].get(key) or next(iter(state["archive"].values()), None)

    async def _enqueue(job: str, payload: dict[str, Any], **_: Any) -> str:
        state["enqueued"].append((job, payload))
        return "job"

    monkeypatch.setattr(pipeline, "copy_recording", _copy)
    monkeypatch.setattr(pipeline, "archive_payload", _archive)
    monkeypatch.setattr("apps.workers.engine_delivery.read_engine_payload", _read)
    monkeypatch.setattr(pipeline, "enqueue", _enqueue)
    return state


async def _thinnest_agent(rate_key: str | None) -> tuple[UUID, UUID, str]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, engine_rate_key, created_at, updated_at) VALUES ('thinnest', :ref, "
                ":tid, :aid, true, :key, now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id, "key": rate_key},
        )
    return tenant_id, agent_id, ref


async def _ingest(ref: str) -> tuple[str, dict[str, Any]]:
    body = _analysed(ref)
    call_id = json.loads(body)["data"]["id"]
    event_name = "call.analysed:1:2026-10-06T04:33:20Z"
    delivery = seal_delivery(
        body.decode(), engine=ENGINE, execution_id=call_id, event_name=event_name
    )
    outcome = await pipeline.ingest_engine_event(
        {},
        {
            "engine": ENGINE,
            "execution_id": call_id,
            "raw_status": "call.analysed",
            "engine_agent_ref": ref,
            "delivery": delivery,
        },
    )
    assert outcome == "pipeline_enqueued"
    return call_id, delivery


async def _usage(tenant_id: UUID, call_id: UUID) -> dict[str, tuple[Decimal, Decimal | None, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta FROM usage_events "
                    "WHERE call_id = :c"
                ),
                {"c": call_id},
            )
        ).all()
    return {
        str(r[0]): (Decimal(str(r[1])), None if r[2] is None else Decimal(str(r[2])), r[3])
        for r in rows
    }


async def test_an_inbound_call_settles_from_its_signed_delivery(thinnest: dict[str, Any]) -> None:
    await _attest("platform", "1.00")
    tenant_id, _agent, ref = await _thinnest_agent(None)
    execution_id, delivery = await _ingest(ref)

    [(_job, payload)] = [e for e in thinnest["enqueued"] if e[0] == pipeline.POSTCALL_JOB]
    assert payload["delivery"] == delivery
    call_id = UUID(payload["call_id"])

    await pipeline._post_call_stages(tenant_id, call_id, execution_id, delivery=delivery)

    async with tenant_session(tenant_id) as session:
        call = (
            await session.execute(
                text(
                    "SELECT direction, status, duration_s, recording_url, engine_payload_ref "
                    "FROM calls WHERE id = :c"
                ),
                {"c": call_id},
            )
        ).one()
        turns = (
            await session.execute(
                text("SELECT count(*) FROM transcript_turns WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar_one()
    assert call[0] == "inbound"
    assert call[1] == "completed"
    assert call[2] == 182
    assert call[3] == f"recordings/{tenant_id}/{call_id}.wav"
    assert call[4] is not None
    assert turns == 2

    usage = await _usage(tenant_id, call_id)
    qty, unit, meta = usage["platform_min"]
    assert qty == Decimal("3.0333")  # 182 s as minutes, at the column's four decimals
    # 182 s is seven 30-second pulses: 3.5 billed minutes at ₹1.00 = ₹3.50 for the call.
    assert (qty * unit).quantize(Decimal("0.01")) == Decimal("3.50")
    assert meta["engine_rate_key"] == "platform"
    assert meta["billed_minutes"] == "3.5"
    assert meta["inr_per_min"] == "1.000000"
    assert usage["telephony_s"][0] == Decimal(182)

    # A re-drive carries no delivery: the engine 404s, the archive answers, and the
    # append-only ledger is not written twice.
    gets_before = thinnest["gets"]
    await pipeline._post_call_stages(tenant_id, call_id, execution_id)
    assert thinnest["gets"] == gets_before + 1
    assert await _usage(tenant_id, call_id) == usage


async def test_an_unattested_rate_meters_the_minutes_unpriced_and_alarms(
    thinnest: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts: list[str] = []
    real_alert = pipeline.alert

    def _record(stage: str, code: str, **kw: Any) -> None:
        alerts.append(code)
        real_alert(stage, code, **kw)

    monkeypatch.setattr(pipeline, "alert", _record)
    # `studio` is never attested by this suite.
    tenant_id, _agent, ref = await _thinnest_agent("studio")
    execution_id, delivery = await _ingest(ref)
    call_id = UUID(
        next(
            p
            for j, p in thinnest["enqueued"]
            if j == pipeline.POSTCALL_JOB and p["execution_id"] == execution_id
        )["call_id"]
    )

    await pipeline._post_call_stages(tenant_id, call_id, execution_id, delivery=delivery)

    usage = await _usage(tenant_id, call_id)
    _qty, unit, meta = usage["platform_min"]
    assert unit is None, "an unattested minute is unpriced, never ₹0"
    assert meta["engine_rate_key"] == "studio"
    assert meta["inr_per_min"] is None
    assert "engine_minute_rate_unattested" in alerts


async def test_a_lost_inbound_delivery_settles_from_the_call_list_and_says_so(
    thinnest: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reconciliation re-drive of an inbound call whose `call.analysed` never arrived:
    the engine 404s by id, so the sealed listing row is what settles it — with an alarm,
    because its transcript and recording are gone (list-calls.md:250-252)."""
    from apps.workers import engine_delivery

    alerts: list[str] = []
    monkeypatch.setattr(engine_delivery, "alert", lambda _s, code, **_kw: alerts.append(code))
    tenant_id, _agent, ref = await _thinnest_agent(None)
    engine = pipeline.get_engine()
    listed = engine.snapshot_from_delivery(json.loads(_analysed(ref))).model_copy(  # type: ignore[attr-defined]
        update={"transcript": [], "recording_url": None, "raw_document": None}
    )
    payload = {
        "engine": ENGINE,
        "execution_id": listed.engine_call_id,
        "raw_status": listed.raw_status,
        "engine_agent_ref": ref,
        "source": "reconciliation",
        **engine_delivery.seal_listing(engine, listed),
    }
    assert CALLER_DIGITS not in json.dumps(payload)

    assert await pipeline.ingest_engine_event({}, payload) == "pipeline_enqueued"
    assert "engine_call_settled_without_delivery" in alerts
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM calls WHERE engine_call_id = :e"),
                {"e": listed.engine_call_id},
            )
        ).scalar_one()
    assert status == "completed"


CALLER_DIGITS = "9876543210"


# --- the client's rung (D-681) -------------------------------------------------------


async def _settle_on(
    thinnest: dict[str, Any], rate_key: str, *, tts_voice: str | None
) -> tuple[UUID, UUID]:
    """A funded prepaid tenant whose ThinnestAI agent was published on `rate_key`, its
    `agents.tts_voice` set to one of OUR voices, and one 182-second call settled."""
    from apps.api.billing.service import record_entry

    tenant_id, agent_id, ref = await _thinnest_agent(rate_key)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v WHERE id = :a"), {"v": tts_voice, "a": agent_id}
        )
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup")
    execution_id, delivery = await _ingest(ref)
    call_id = UUID(
        next(
            p
            for j, p in thinnest["enqueued"]
            if j == pipeline.POSTCALL_JOB and p["execution_id"] == execution_id
        )["call_id"]
    )
    await pipeline._post_call_stages(tenant_id, call_id, execution_id, delivery=delivery)
    return tenant_id, call_id


async def _debit(tenant_id: UUID, call_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        total = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(-delta), 0) FROM credit_ledger "
                    "WHERE reason = 'usage' AND ref = :r"
                ),
                {"r": str(call_id)},
            )
        ).scalar_one()
    return Decimal(str(total))


async def _clear_list_rate(tenant_id: UUID) -> Decimal:
    from apps.api.billing.service import rate_card_at

    async with tenant_session(tenant_id) as session:
        return (await rate_card_at(session, at=datetime.now(UTC))).list_rates().rate_for("clear")


async def test_a_premium_voice_bills_the_clear_rung_whatever_tts_voice_says(
    thinnest: dict[str, Any],
) -> None:
    await _attest("premium", "2.50")
    # A Studio voice id of OUR catalogue on the row: the engine did not speak it.
    tenant_id, call_id = await _settle_on(thinnest, "premium", tts_voice="sonic-3.5:anything")

    usage = await _usage(tenant_id, call_id)
    assert usage["telephony_s"][2]["voice_tier"] == "clear"
    # The Clear list rate (no lot was bought) on the client-billed minutes of 182 s.
    from apps.api.billing.rates import client_billed_minutes, prepaid_billed_inr

    ended = datetime(2026, 10, 6, 4, 33, 11, tzinfo=UTC)
    expected = prepaid_billed_inr(
        minutes=client_billed_minutes(Decimal(182), at=ended),
        self_serve_rate=await _clear_list_rate(tenant_id),
    )
    assert await _debit(tenant_id, call_id) == expected


async def test_a_band_that_is_not_sold_bills_clear_and_alarms(
    thinnest: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts: list[str] = []
    real_alert = pipeline.alert

    def _record(stage: str, code: str, **kw: Any) -> None:
        alerts.append(code)
        real_alert(stage, code, **kw)

    monkeypatch.setattr(pipeline, "alert", _record)
    await _attest("standard", "2.00")
    tenant_id, call_id = await _settle_on(thinnest, "standard", tts_voice=None)

    assert (await _usage(tenant_id, call_id))["telephony_s"][2]["voice_tier"] == "clear"
    assert "engine_rate_key_not_sold" in alerts
