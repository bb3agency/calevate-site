"""Journey audit E4 (10 Nov 2026): one prepaid client's money across an IST month and its
boundary, walked in time order through the real writers, with every screen read compared.

The walk: a free trial -> the first top-up (signed Razorpay webhook, credit lot) -> calls on
both voices -> an extra block of AI help -> a spending limit reached -> a number's rental ->
a lapsed lot -> the roll to the next IST month -> an admin refund. After each step the
wallet, the ledger, the lots, `spend_state`, the usage panel, the limit panel, the wallet
drawdown, the statement list and the statement document must agree to the paisa.

The ledger stamps rows with the database clock (`record_entry` uses `clock_timestamp()`),
which a test cannot move, so the month the money moves in is the real current IST month.
The roll is taken by freezing the PROCESS clock of the billing readers one second after
midnight IST on the 1st of the next month; a call that ended on the last evening of the
month and settles after the roll is metered with that `ended_at`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import ai_quota, payments
from apps.api.billing.ai_quota import (
    ai_overage_block_inr,
    new_assist_ref,
    purchase_ai_overage,
    read_ai_quota,
)
from apps.api.billing.caps import apply_client_caps, read_spend_counters
from apps.api.billing.credit_expiry import expire_lot
from apps.api.billing.history import statement_page
from apps.api.billing.invoice import build_invoice
from apps.api.billing.number_rental import charge_number_rental
from apps.api.billing.payment_routes import webhook_router
from apps.api.billing.plans import IST, ist_billing_month, ist_month_window
from apps.api.billing.service import get_balance, to_paise, usage_summary
from apps.api.billing.trials import read_trial, start_trial
from apps.api.billing.wallet import read_wallet
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.spend_caps_test import _call_row, _snapshot
from tests.spend_caps_test import _tenant as _armed_tenant

pytestmark = [pytest.mark.rls]

WEBHOOK_SECRET = "whsec_e4_journey"
KEY_ID = "rzp_test_e4"
KEY_SECRET = "rzp_secret_e4"
_ZERO = Decimal("0.00")
#: A Studio voice id (`agents.voices.voice_tier` reads the model prefix).
_STUDIO_VOICE = "sonic-3.5:e4-journey-voice"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(settings, "razorpay_mode", None)


@pytest.fixture(autouse=True)
def _gate_reaches_the_spend_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling hours and the platform switch sit around the spend rule in `check_dispatch`;
    pinned so the walk measures the limit, not the wall clock."""
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_copy(
        *, source_url: str, tenant_id: UUID, call_id: UUID, leg: str = "call"
    ) -> str:
        return f"recordings/{tenant_id}/{call_id}-{leg}.wav"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)


# --- the process clock -----------------------------------------------------------------

#: The modules whose `datetime.now()` decides "which month is it now" for a reader.
_CLOCK_MODULES = (
    "apps.api.billing.service",
    "apps.api.billing.plans",
    "apps.api.billing.history",
    "apps.api.billing.wallet",
    "apps.api.billing.invoice",
    "apps.api.billing.trials",
    "apps.api.billing.ai_quota",
    "apps.api.compliance.service",
)


def _freeze(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> None:
    frozen = instant

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return frozen if tz is None else frozen.astimezone(tz)

    import importlib

    for name in _CLOCK_MODULES:
        monkeypatch.setattr(importlib.import_module(name), "datetime", _Frozen)


def _next_month_start(month: str) -> datetime:
    return ist_month_window(month)[1]


# --- the writers, driven the way production drives them -------------------------------


def _client() -> AsyncClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(webhook_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _webhook_top_up(tenant_id: UUID, amount_inr: str) -> str:
    """A signed `payment.captured` for a plain top-up, through the real receiver."""
    payment_id = f"pay_{uuid.uuid4().hex[:14]}"
    paise = int(Decimal(amount_inr) * 100)
    body = {
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": paise,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": f"order_{uuid.uuid4().hex[:14]}",
                    "international": False,
                    "notes": {payments.NOTES_TENANT_KEY: str(tenant_id)},
                }
            }
        },
    }
    raw = json.dumps(body, separators=(",", ":")).encode()
    headers = {
        payments.SIGNATURE_HEADER: hmac.new(
            WEBHOOK_SECRET.encode(), raw, hashlib.sha256
        ).hexdigest(),
        payments.EVENT_ID_HEADER: f"evt_{uuid.uuid4().hex[:14]}",
        "Content-Type": "application/json",
    }
    async with _client() as client:
        response = await client.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.status_code == 200, response.text
    return payment_id


async def _set_voice(tenant_id: UUID, agent_id: UUID, voice: str | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v WHERE id = :a"), {"v": voice, "a": agent_id}
        )


def _after_top_up(seconds: int) -> datetime:
    """The end of a call of `seconds` that STARTS now, after the top-up just made: a trial
    call is free by its start, so a call ending now would have begun inside the trial."""
    return datetime.now(UTC) + timedelta(seconds=seconds + 1)


async def _call(
    tenant_id: UUID, agent_id: UUID, *, seconds: int, ended: datetime, spend: str = "0.5000"
) -> UUID:
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, call_id, _snapshot(seconds=seconds, spend=spend, ended=ended))
    return call_id


async def _ai_usage(tenant_id: UUID, cost_inr: Decimal) -> None:
    """One metered dashboard-AI answer costing us `cost_inr`, shaped as
    `ai_quota.record_ai_assist_usage` writes it (one `ktok_out` row under a fresh ref)."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, ref, occurred_at, meta, created_at) VALUES (:id, :tid, NULL, "
                "'ai_assist_ktok_out', 1, :cost, :ref, now(), CAST(:meta AS jsonb), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cost": cost_inr,
                "ref": new_assist_ref(),
                "meta": json.dumps({"kind": ai_quota.ASSIST_META_KIND, "feature": "copy"}),
            },
        )


# --- the reads every screen makes ------------------------------------------------------


async def _ledger_sum(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    return Decimal(str(value))


async def _open_lots_total(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(credits_remaining), 0) FROM credit_lots "
                    "WHERE tenant_id = :t AND closed_at IS NULL"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    return Decimal(str(value))


async def _call_debits(tenant_id: UUID, month: str) -> Decimal:
    """Every rupee a call of `month` took off the wallet: `usage` rows whose ref is a call
    that wrote usage in that IST month."""
    start, end = ist_month_window(month)
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(-e.delta), 0) FROM credit_ledger e WHERE e.tenant_id = :t "
                    "AND e.reason = 'usage' AND EXISTS (SELECT 1 FROM usage_events u WHERE "
                    "u.tenant_id = e.tenant_id AND u.call_id::text = e.ref AND "
                    "u.occurred_at >= :s AND u.occurred_at < :e)"
                ),
                {"t": tenant_id, "s": start, "e": end},
            )
        ).scalar_one()
    return Decimal(str(value))


async def _wallet_agrees(tenant_id: UUID) -> Decimal:
    """Balance = newest balance_after = sum of every delta = the open lots (no overdraft)."""
    async with tenant_session(tenant_id) as session:
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    assert balance == await _ledger_sum(tenant_id)
    if balance >= 0:
        assert await _open_lots_total(tenant_id) == balance
    return balance


async def _screens(tenant_id: UUID, month: str) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        usage = await usage_summary(session, tenant_id=tenant_id, month=month)
        counters = await read_spend_counters(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id, month=month)
        page = await statement_page(session, tenant_id=tenant_id, limit=3, before=None)
        wallet = await read_wallet(
            session, tenant_id=tenant_id, prepaid=True, outbound_stopped=False
        )
        quota = await read_ai_quota(session, tenant_id=tenant_id, month=month)
    statement = next(s for s in page.statements if s.month == month)
    return {
        "usage": usage,
        "counters": counters,
        "invoice": invoice,
        "statement": statement,
        "wallet": wallet,
        "quota": quota,
    }


def _invoice_lines(invoice: dict[str, Any], prefix: str) -> Decimal:
    return sum(
        (
            Decimal(str(i["amount_inr"]))
            for i in invoice["line_items"]
            if i["description"].startswith(prefix)
        ),
        _ZERO,
    )


# --- the walk --------------------------------------------------------------------------


async def test_one_clients_money_walks_a_month_and_its_boundary_to_the_paisa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    month = ist_billing_month(now)
    tenant_id, outbound_agent, _ref = await _armed_tenant(f"e4_{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'prepaid', created_at = :c WHERE id = :t"),
            {"t": tenant_id, "c": now - timedelta(days=40)},
        )
        await session.execute(text("DELETE FROM plans WHERE tenant_id = :t"), {"t": tenant_id})

    # 1. The free trial: a call inside it costs the client nothing.
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session,
            tenant_id=tenant_id,
            days=14,
            actor_user_id=None,
            free_minutes=30,
            at=now - timedelta(hours=3),
        )
    await _call(tenant_id, outbound_agent, seconds=95, ended=now - timedelta(hours=2))
    assert await _wallet_agrees(tenant_id) == _ZERO
    trial_screens = await _screens(tenant_id, month)
    assert trial_screens["usage"]["spend_used_inr"] == _ZERO
    assert trial_screens["counters"].billed_inr == _ZERO

    # 2. The first top-up: a signed webhook credits ₹1,000 into a lot and ends the trial.
    payment_id = await _webhook_top_up(tenant_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        trial = await read_trial(session, tenant_id=tenant_id)
    assert trial is not None and trial.status == "converted"
    assert await _wallet_agrees(tenant_id) == Decimal("1000.00")

    # 3. Calls on both voices, after the trial: every rupee off the wallet is the same
    #    rupee on the usage panel, the limit panel, the drawdown, the statement and the
    #    document.
    await _set_voice(tenant_id, outbound_agent, None)
    await _call(tenant_id, outbound_agent, seconds=125, ended=_after_top_up(125))
    await _set_voice(tenant_id, outbound_agent, _STUDIO_VOICE)
    await _call(tenant_id, outbound_agent, seconds=61, ended=_after_top_up(61))
    await _set_voice(tenant_id, outbound_agent, None)
    calls_spent = await _call_debits(tenant_id, month)
    assert calls_spent > 0
    balance = await _wallet_agrees(tenant_id)
    assert balance == Decimal("1000.00") - calls_spent
    s = await _screens(tenant_id, month)
    assert s["counters"].billed_inr == calls_spent
    assert s["counters"].minutes_used == s["usage"]["minutes_used"] == Decimal("4.00")
    assert s["statement"].calls == s["usage"]["calls"] == 2
    assert s["usage"]["spend_used_inr"] == calls_spent
    assert s["usage"]["clear_charges_inr"] + s["usage"]["studio_charges_inr"] == calls_spent
    assert s["wallet"].drawdown.calls_inr == calls_spent
    assert _invoice_lines(s["invoice"], "Call minutes") == calls_spent
    assert s["statement"].total_inr == calls_spent
    assert s["statement"].wallet_spent_inr == calls_spent
    assert s["statement"].credit_added_inr == Decimal("1000.00")

    # 4. AI help: the allowance runs out and the owner buys the extra block. The block is
    #    a supply the wallet paid for, so the month's statement must carry it.
    quota = s["quota"]
    await _ai_usage(tenant_id, quota.allowance_inr)
    block = ai_overage_block_inr()
    async with tenant_session(tenant_id) as session:
        bought = await purchase_ai_overage(session, tenant_id=tenant_id, accepted_amount_inr=block)
    assert bought.charged
    balance = await _wallet_agrees(tenant_id)
    assert balance == Decimal("1000.00") - calls_spent - block
    s = await _screens(tenant_id, month)
    assert s["wallet"].drawdown.ai_assist_inr == block
    assert s["statement"].wallet_spent_inr == calls_spent + block
    assert s["statement"].total_inr == calls_spent + block, (
        "the extra AI help the wallet paid for is missing from the month's statement"
    )
    assert s["counters"].billed_inr == calls_spent, "the limit counts calls only"

    # 5. The spending limit: set below what is already spent, outbound stops at once.
    async with tenant_session(tenant_id) as session:
        await apply_client_caps(session, tenant_id=tenant_id, cap_min=None, cap_spend=calls_spent)
    async with tenant_session(tenant_id) as session:
        refused = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=outbound_agent,
            phone_e164=f"+9199{uuid.uuid4().int % 100000000:08d}",
        )
    assert refused.rule == "spend_cap"

    # 6. A number's rental for this month, from the wallet.
    number_id = uuid7()
    today = now.astimezone(IST).date()
    period = date(today.year, today.month, 1)
    async with tenant_session(tenant_id) as session:
        rental = await charge_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=number_id,
            anchor=period,
            period_start=period,
            inr_per_month=Decimal("299.00"),
        )
    assert rental.charged
    balance = await _wallet_agrees(tenant_id)
    s = await _screens(tenant_id, month)
    assert s["wallet"].drawdown.number_rental_inr == Decimal("299.00")
    assert _invoice_lines(s["invoice"], "Phone number rental") == Decimal("299.00")
    assert s["statement"].total_inr == calls_spent + block + Decimal("299.00")
    assert s["statement"].wallet_spent_inr == calls_spent + block + Decimal("299.00")

    # 7. A lot lapses: lapsed credit leaves the balance and the lots, and is not spend.
    second_payment = await _webhook_top_up(tenant_id, "500.00")
    async with tenant_session(tenant_id) as session:
        lot_id, remaining, lapses_at = (
            await session.execute(
                text(
                    "SELECT l.id, l.credits_remaining, l.expires_at FROM credit_lots l "
                    "JOIN credit_ledger e ON e.id = l.ledger_entry_id "
                    "WHERE l.tenant_id = :t AND e.ref LIKE :p"
                ),
                {"t": tenant_id, "p": f"%{second_payment}%"},
            )
        ).one()
        assert lapses_at is not None, "a pack bought under Terms 19 carries its lapse date"
        expired = await expire_lot(
            session, tenant_id=tenant_id, lot_id=lot_id, now=lapses_at + timedelta(seconds=1)
        )
    assert expired is not None and expired.credits_inr == Decimal(str(remaining))
    balance = await _wallet_agrees(tenant_id)
    s = await _screens(tenant_id, month)
    assert s["wallet"].drawdown.expired_inr == Decimal(str(remaining))
    assert s["statement"].credit_expired_inr == to_paise(Decimal(str(remaining)))
    assert s["statement"].wallet_spent_inr == calls_spent + block + Decimal("299.00")
    before_roll = s

    # 8. The roll: one second after 00:00 IST on the 1st.
    roll = _next_month_start(month) + timedelta(seconds=1)
    next_month = ist_billing_month(roll)
    _freeze(monkeypatch, roll)
    # A call that ended on the last evening settles after the roll: it belongs to the
    # closed month on every screen.
    late = await _call(
        tenant_id,
        outbound_agent,
        seconds=30,
        ended=_next_month_start(month) - timedelta(seconds=40),
    )
    late_debit = await _call_debits(tenant_id, month) - calls_spent
    assert late_debit > 0
    balance = await _wallet_agrees(tenant_id)
    async with tenant_session(tenant_id) as session:
        fresh = await read_spend_counters(session, tenant_id=tenant_id)
        dispatch = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=outbound_agent,
            phone_e164=f"+9199{uuid.uuid4().int % 100000000:08d}",
        )
        next_quota = await read_ai_quota(session, tenant_id=tenant_id)
        closed_usage = await usage_summary(session, tenant_id=tenant_id, month=month)
        closed_invoice = await build_invoice(session, tenant_id=tenant_id, month=month)
        page = await statement_page(session, tenant_id=tenant_id, limit=3, before=None, now=roll)
        open_usage = await usage_summary(session, tenant_id=tenant_id)
    assert fresh.billed_inr == _ZERO and fresh.minutes_used == _ZERO and not fresh.capped
    assert dispatch.rule != "spend_cap", "last month's limit must not stop this month's calls"
    assert next_quota.month == next_month
    assert next_quota.used_inr == 0 and next_quota.extra_purchased_inr == 0
    assert open_usage["month"] == next_month and open_usage["spend_used_inr"] == _ZERO
    assert closed_usage["spend_used_inr"] == calls_spent + late_debit
    assert _invoice_lines(closed_invoice, "Call minutes") == calls_spent + late_debit
    closed_row = next(r for r in page.statements if r.month == month)
    open_row = next(r for r in page.statements if r.month == next_month)
    assert closed_row.closed and not open_row.closed
    assert open_row.total_inr == _ZERO
    assert closed_row.total_inr == before_roll["statement"].total_inr + late_debit
    assert closed_invoice["invoice_number"] == before_roll["invoice"]["invoice_number"]
    _ = late
    assert before_roll["wallet"].balance.amount_inr - late_debit == balance

    # 9. An admin refunds ₹100 of the first payment (Razorpay confirms it by webhook):
    #    the money leaves as a refund, off the lot it was bought into, and is not spend.
    refund_body = {
        "entity": "event",
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": f"rfnd_{uuid.uuid4().hex[:14]}",
                    "entity": "refund",
                    "amount": 10000,
                    "currency": "INR",
                    "payment_id": payment_id,
                    "status": "processed",
                    "notes": {payments.NOTES_TENANT_KEY: str(tenant_id)},
                }
            }
        },
    }
    raw = json.dumps(refund_body, separators=(",", ":")).encode()
    async with _client() as client:
        response = await client.post(
            "/hooks/v1/razorpay",
            content=raw,
            headers={
                payments.SIGNATURE_HEADER: hmac.new(
                    WEBHOOK_SECRET.encode(), raw, hashlib.sha256
                ).hexdigest(),
                payments.EVENT_ID_HEADER: f"evt_{uuid.uuid4().hex[:14]}",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 200, response.text
    final = await _wallet_agrees(tenant_id)
    assert final == balance - Decimal("100.00")
    async with tenant_session(tenant_id) as session:
        after_refund = await read_wallet(
            session, tenant_id=tenant_id, prepaid=True, outbound_stopped=False, now=roll
        )
        page = await statement_page(session, tenant_id=tenant_id, limit=3, before=None, now=roll)
    assert after_refund.drawdown.refunded_inr == Decimal("100.00")
    assert after_refund.drawdown.spent_inr == before_roll["wallet"].drawdown.spent_inr + late_debit
    closed_after = next(r for r in page.statements if r.month == month)
    assert closed_after.total_inr == closed_row.total_inr
    assert closed_after.wallet_spent_inr == closed_row.wallet_spent_inr
