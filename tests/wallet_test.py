"""The client's own prepaid wallet: the runway, the drawdown, the attempts, and the two
promises the founder made about an empty one (2 Sep 2026).

What is asserted here, and why each one is worth a test rather than a docstring:

* **Inbound is NEVER stopped by a balance.** The founder's decision, and the one this
  product loses clients over. It is asserted as a property of the dial gate itself — the
  refusal that exists is outbound-only — rather than by reading a comment that says so.
* **There is no second credit check.** `wallet_routes` asks
  `compliance.service.credits_exhausted` and publishes its answer; a managed tenant with
  an empty wallet is NOT stopped, because that gate says so.
* **The runway refuses to invent a number.** Two days of history projects nothing, and the
  screen is told which reason.
* **Double delivery credits once.** The webhook is delivered twice, then the same payment
  arrives again under the OTHER credit event, and the wallet moves exactly once.
* **RLS.** A cross-tenant read of `topup_attempts` returns zero rows.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import payments
from apps.api.billing.payment_routes import webhook_router
from apps.api.billing.service import (
    LOW_BALANCE_INR,
    WALLET_LEVEL_EMPTY,
    WALLET_LEVEL_LOW,
    crossed_downwards,
    get_balance,
    prepaid_minutes_left,
    record_entry,
)
from apps.api.billing.service import Balance as WalletBalance
from apps.api.billing.wallet import (
    MIN_BURN_HISTORY_DAYS,
    PENDING_GRACE_HOURS,
    read_attempts,
    read_runway,
    read_wallet,
    record_attempt,
    settle_attempt,
)
from apps.api.billing.wallet_routes import (
    read_payment_receipt,
    read_topup_attempts,
    read_wallet_ledger,
    read_wallet_summary,
)
from apps.api.compliance.service import check_dispatch, credits_exhausted
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import accept_agreements

pytestmark = [pytest.mark.rls]

WEBHOOK_SECRET = "whsec_wallet_test"


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that can verify a webhook. Orders are not created in this file — the
    intent route's own suite covers that seam."""
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_wallet")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)


async def _tenant(plan_tier: str = "self_serve") -> UUID:
    created = await admin_service.create_organization(
        name="Wallet Clinic",
        slug=f"wal-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id


def _principal(tenant_id: UUID, role: str = "owner") -> Principal:
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=role,
        impersonating=False,
    )


async def _past_entry(
    tenant_id: UUID,
    *,
    delta: str,
    reason: str,
    days_ago: int,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append a ledger entry dated in the PAST.

    A test that wants a runway needs a history, and there is exactly one way to give a
    wallet one: APPEND. `credit_ledger` is in `APPEND_ONLY_TABLES` and a database trigger
    refuses UPDATE outright (hard rule 4) — an earlier draft of this file back-dated rows
    with an UPDATE and was correctly refused, which is the guard doing its job on a test.

    `balance_after` is carried forward from the newest existing row, because `get_balance`
    READS the newest `balance_after` rather than summing: a fixture that wrote a wrong one
    would produce a balance no arithmetic on the visible rows explains. Callers therefore
    add history oldest-first.
    """
    async with tenant_session(tenant_id) as session:
        current = (await get_balance(session, tenant_id=tenant_id)).amount_inr
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, meta, created_at) VALUES (gen_random_uuid(), :t, :d, :r, NULL, "
                ":bal, now() - make_interval(days => :ago), CAST(:meta AS jsonb), now())"
            ),
            {
                "t": tenant_id,
                "d": Decimal(delta),
                "r": reason,
                "bal": current + Decimal(delta),
                "ago": days_ago,
                "meta": json.dumps(meta) if meta else None,
            },
        )


# ============================================================================
# THE FOUNDER'S DECISION: outbound stops at zero, INBOUND NEVER DOES
# ============================================================================


async def test_an_empty_wallet_stops_outbound_dialling() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id) is True


async def test_an_empty_wallet_does_not_stop_an_inbound_agent_answering() -> None:
    """THE PROMISE THAT MATTERS, asserted against the gate rather than against a comment.

    `check_dispatch` is the ONE gate every outbound path goes through, and it is the only
    place `credits_exhausted` can refuse anything. Its refusal for an inbound agent is
    `agent_inbound_only` — "this agent only answers calls; it cannot place them" — and
    that refusal is reached BEFORE the money questions, so an inbound agent on an empty
    wallet is never told about credit at all.

    That is the shape of the guarantee: there is nothing in this product that an inbound
    CALL passes through which can consult a balance. `apps/voice-runtime` reads no billing
    state (hard rule 3 — it acks and defers), and a grep of the inbound path for a credit
    check finds nothing. So answering the phone cannot stop for an empty wallet, and this
    test fails the day someone puts a credit check in front of one.
    """
    tenant_id = await _tenant()
    agent_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                # Every compliance sentence column is NOT NULL, `disclosure_line`
                # included (the legacy bundled one, still present under hard rule 8's
                # two-step deprecation). Written out rather than copied off a seeded row
                # because this fixture needs one property no seed has: an INBOUND agent.
                "INSERT INTO agents (id, tenant_id, name, status, direction, "
                "language_primary, disclosure_line, ai_disclosure_line, "
                "recording_notice_line, caller_memory_notice_line, created_at, updated_at) "
                "VALUES (:a, :t, 'Reception', 'live', 'inbound', 'en-IN', "
                "'This is the AI assistant for Wallet Clinic. This call is being recorded.', "
                "'This is the AI assistant for Wallet Clinic.', "
                "'This call is being recorded.', "
                "'We remember what you tell us so you do not have to repeat it.', "
                "now(), now())"
            ),
            {"a": agent_id, "t": tenant_id},
        )
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000001"
        )
    # Refused as an OUTBOUND dial, on the grounds that it is an answering agent — never
    # on the grounds of money, and refused before the wallet is even read.
    assert decision.allowed is False
    assert decision.rule == "agent_inbound_only"
    assert decision.rule != "no_credits"


async def test_a_managed_tenant_with_an_empty_wallet_is_not_stopped() -> None:
    """The gate is tier-conditional, and the wallet screen ASKS it rather than
    re-deriving `balance <= 0` — which would stop an invoiced client over a wallet they
    never bought."""
    tenant_id = await _tenant(plan_tier="managed")
    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).is_exhausted is True
        assert await credits_exhausted(session, tenant_id=tenant_id) is False

    summary = await read_wallet_summary(_principal(tenant_id))
    assert summary.prepaid is False
    assert summary.outbound_stopped is False
    # No runway is quoted to an account with no wallet: a minutes figure there would be a
    # number about nothing.
    assert summary.minutes_left is None


# ============================================================================
# THE RUNWAY — and its refusal to invent one
# ============================================================================


async def test_a_brand_new_wallet_says_it_has_not_watched_long_enough() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("5000"), reason="topup")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-200"), reason="usage")
        balance = await get_balance(session, tenant_id=tenant_id)
        runway, _ = await read_runway(session, tenant_id=tenant_id, balance=balance)
    assert runway.basis == "too_new"
    assert runway.days is None, "a projection from two days of data is worse than none"
    assert runway.daily_burn_inr is None
    assert runway.history_days < MIN_BURN_HISTORY_DAYS


async def test_a_wallet_with_history_projects_days_and_shows_its_working() -> None:
    tenant_id = await _tenant()
    await _past_entry(tenant_id, delta="5000", reason="topup", days_ago=10)
    # ₹1,000 spent over the ten days we have been watching = ₹100/day, and ₹4,000 left.
    await _past_entry(tenant_id, delta="-1000", reason="usage", days_ago=1)
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        runway, drawdown = await read_runway(session, tenant_id=tenant_id, balance=balance)
    assert runway.basis == "projected"
    assert runway.daily_burn_inr == Decimal("100")
    assert runway.days == 40
    # THE WORKING IS PUBLISHED, not just the conclusion: an owner who disagrees with
    # "40 days" can see the ₹100 a day it came from.
    assert drawdown.spent_inr == Decimal("1000")


async def test_a_wallet_that_is_spending_nothing_says_so_rather_than_forever() -> None:
    tenant_id = await _tenant()
    await _past_entry(tenant_id, delta="5000", reason="topup", days_ago=20)
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        runway, _ = await read_runway(session, tenant_id=tenant_id, balance=balance)
    assert runway.basis == "no_burn"
    assert runway.days is None
    # ZERO and not None: "we watched for twenty days and you spent nothing" is a
    # measurement, and a different statement from "we could not measure".
    assert runway.daily_burn_inr == Decimal("0")


async def test_an_almost_idle_account_is_capped_rather_than_told_it_has_years() -> None:
    tenant_id = await _tenant()
    await _past_entry(tenant_id, delta="50000", reason="topup", days_ago=25)
    await _past_entry(tenant_id, delta="-3", reason="usage", days_ago=1)
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        runway, _ = await read_runway(session, tenant_id=tenant_id, balance=balance)
    assert runway.beyond_horizon is True
    assert runway.days is None, "'your credit lasts until 2029' is true and useless"


async def test_an_empty_wallet_projects_nothing_and_says_it_is_empty() -> None:
    tenant_id = await _tenant()
    await _past_entry(tenant_id, delta="500", reason="topup", days_ago=20)
    await _past_entry(tenant_id, delta="-500", reason="usage", days_ago=1)
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        runway, _ = await read_runway(session, tenant_id=tenant_id, balance=balance)
    assert runway.basis == "empty"
    assert runway.days is None


def test_minutes_left_never_prints_a_zero_for_an_unpriced_deployment() -> None:
    """`None` means "no answer", not "none left" — printing a zero for a deployment that
    quotes no rate would tell a client with money in their wallet that they cannot call."""
    funded = WalletBalance(amount_inr=Decimal("500"), is_low=False)
    assert prepaid_minutes_left(balance=funded, rate=Decimal("0")) is None
    assert prepaid_minutes_left(balance=funded, rate=Decimal("8")) == 62, "floored, never up"
    empty = WalletBalance(amount_inr=Decimal("0"), is_low=True)
    assert prepaid_minutes_left(balance=empty, rate=Decimal("0")) == 0


# ============================================================================
# WHERE THE MONEY WENT
# ============================================================================


async def test_the_drawdown_splits_calls_from_ai_help_and_adds_up_exactly() -> None:
    from apps.api.billing.ai_quota import OVERAGE_META_KIND

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("5000"), reason="topup")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-120.50"), reason="usage")
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-300"),
            reason="usage",
            meta={"kind": OVERAGE_META_KIND},
        )
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-40"), reason="adjustment")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("400"), reason="bonus")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-100"), reason="refund")
        balance = await get_balance(session, tenant_id=tenant_id)
        _, drawdown = await read_runway(session, tenant_id=tenant_id, balance=balance)

    assert drawdown.calls_inr == Decimal("120.50")
    assert drawdown.ai_assist_inr == Decimal("300")
    assert drawdown.adjustments_inr == Decimal("40")
    # THE TOTAL IS THE SUM OF THE ROWS BENEATH IT, by construction rather than by a second
    # aggregate that can round differently from its own parts.
    assert drawdown.spent_inr == drawdown.calls_inr + drawdown.ai_assist_inr + (
        drawdown.adjustments_inr
    )
    assert drawdown.added_inr == Decimal("5400")
    assert drawdown.refunded_inr == Decimal("100")


# ============================================================================
# THE LOW-BALANCE WARNING — a CROSSING, not a state
# ============================================================================


def test_only_the_entry_that_crosses_the_line_warns() -> None:
    low = LOW_BALANCE_INR
    assert crossed_downwards(low + Decimal("50"), low - Decimal("50")) == WALLET_LEVEL_LOW
    # Already below the line: a second charge on an already-low wallet says nothing, which
    # is what makes "warn once per episode" need no stored flag.
    assert crossed_downwards(low - Decimal("50"), low - Decimal("60")) is None
    # Falling to zero is the more severe crossing and wins even though it crosses both.
    assert crossed_downwards(low + Decimal("50"), Decimal("0")) == WALLET_LEVEL_EMPTY
    assert crossed_downwards(Decimal("-5"), Decimal("-9")) is None, "already empty"
    # Money going UP never warns.
    assert crossed_downwards(Decimal("0"), Decimal("5000")) is None


async def test_a_charge_that_empties_the_wallet_publishes_one_warning() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("5000"), reason="topup")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-4900"), reason="usage")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-100"), reason="usage")
        # A fourth movement, still below zero: no second warning.
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-10"),
            reason="usage",
            allow_negative=True,
        )
        rows = (
            await session.execute(
                text(
                    "SELECT payload->>'level' FROM outbox_messages "
                    "WHERE job = 'notify_low_balance' AND payload->>'tenant_id' = :t "
                    "ORDER BY created_at"
                ),
                {"t": str(tenant_id)},
            )
        ).all()
    assert [str(r[0]) for r in rows] == [WALLET_LEVEL_LOW, WALLET_LEVEL_EMPTY]


async def test_the_warning_carries_the_balance_as_digits_not_a_json_number() -> None:
    """Hard rule 7 across JSONB: a rupee amount that crossed as a JSON number would be a
    binary double by the time the email renders it."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("300"), reason="topup")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-150.10"), reason="usage")
        payload = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = 'notify_low_balance' "
                    "AND payload->>'tenant_id' = :t"
                ),
                {"t": str(tenant_id)},
            )
        ).scalar()
    body = payload if isinstance(payload, dict) else json.loads(str(payload))
    assert isinstance(body["balance_inr"], str)
    assert Decimal(body["balance_inr"]) == Decimal("149.90")


def test_the_warning_email_leads_with_the_reassurance_not_the_alarm() -> None:
    """A clinic owner reading "your credit has run out" at 8pm concludes their phone has
    stopped being answered. It has not, and the mail says so FIRST."""
    from apps.workers.wallet_alerts import compose

    body = compose(
        level=WALLET_LEVEL_EMPTY, balance_inr=Decimal("0"), minutes_left=0, slug="clinic"
    )
    first = body.splitlines()[0]
    assert "still get through" in first
    assert body.index("still get through") < body.index("has stopped")
    assert "/c/clinic/credits" in body
    # No internals vocabulary anywhere in a client-facing sentence.
    for banned in ("self_serve", "tenant", "ledger", "no_credits", "outbound_stopped"):
        assert banned not in body


# ============================================================================
# TOP-UP ATTEMPTS — the rows a ledger cannot hold
# ============================================================================


async def test_an_attempt_is_recorded_once_per_receipt_and_learns_its_order_id() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt="rcpt-1",
            amount_inr=Decimal("2500"),
            provider_order_id=None,
            pack_id="starter",
        )
        # The same receipt again — one row, and it gains the order id it did not have.
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt="rcpt-1",
            amount_inr=Decimal("2500"),
            provider_order_id="order_abc",
            pack_id="starter",
        )
        rows = await read_attempts(session, tenant_id=tenant_id)
    assert len(rows) == 1
    assert rows[0].provider_order_id == "order_abc"
    assert rows[0].outcome == "settling"
    assert rows[0].amount_inr == Decimal("2500.0000")


async def test_an_unanswered_attempt_becomes_unfinished_only_after_the_grace_window() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt="rcpt-old",
            amount_inr=Decimal("500"),
            provider_order_id="order_old",
            pack_id=None,
        )
        later = datetime.now(UTC) + timedelta(hours=PENDING_GRACE_HOURS + 1)
        aged = await read_attempts(session, tenant_id=tenant_id, now=later)
        fresh = await read_attempts(session, tenant_id=tenant_id)
    assert aged[0].outcome == "unfinished"
    assert fresh[0].outcome == "settling"


async def test_a_captured_attempt_can_never_be_relabelled_failed() -> None:
    """Razorpay's in-modal retry means a `payment.failed` for one card can be followed by
    a success on the SAME order — and, redelivered, can arrive after it."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt="rcpt-retry",
            amount_inr=Decimal("1000"),
            provider_order_id="order_retry",
            pack_id=None,
        )
        await settle_attempt(
            session,
            tenant_id=tenant_id,
            order_id="order_retry",
            payment_id="pay_ok",
            status="captured",
        )
        await settle_attempt(
            session,
            tenant_id=tenant_id,
            order_id="order_retry",
            payment_id="pay_bad",
            status="failed",
        )
        rows = await read_attempts(session, tenant_id=tenant_id)
    assert rows[0].outcome == "captured"
    assert rows[0].provider_payment_id == "pay_ok"


async def test_an_attempt_for_an_order_we_never_recorded_is_not_an_error() -> None:
    """A payment made outside our checkout, or an order created before this table
    existed. The wallet is credited by the ledger either way."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await settle_attempt(
            session,
            tenant_id=tenant_id,
            order_id="order_unknown",
            payment_id="pay_x",
            status="captured",
        )
        assert await read_attempts(session, tenant_id=tenant_id) == []


async def test_topup_attempts_are_invisible_across_tenants() -> None:
    """Hard rule 1: a cross-tenant read returns ZERO rows, and a cross-tenant WRITE is
    refused by the FORCEd policy rather than by anything this code does."""
    owner = await _tenant()
    stranger = await _tenant()
    async with tenant_session(owner) as session:
        await record_attempt(
            session,
            tenant_id=owner,
            receipt="rcpt-private",
            amount_inr=Decimal("900"),
            provider_order_id="order_private",
            pack_id=None,
        )
    async with tenant_session(stranger) as session:
        assert await read_attempts(session, tenant_id=owner) == []
        rows = (await session.execute(text("SELECT id FROM topup_attempts")),)[0].all()
        assert rows == []
    with pytest.raises(DBAPIError):
        async with tenant_session(stranger) as session:
            await record_attempt(
                session,
                tenant_id=owner,
                receipt="rcpt-forged",
                amount_inr=Decimal("1"),
                provider_order_id=None,
                pack_id=None,
            )


# ============================================================================
# IDEMPOTENCY UNDER DOUBLE DELIVERY — the one that is about money
# ============================================================================


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(webhook_router)
    return application


def _signed(body: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {payments.SIGNATURE_HEADER: signature, "Content-Type": "application/json"}


def _envelope(*, event: str, payment_id: str, order_id: str, tenant_id: UUID) -> dict[str, Any]:
    return {
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": 250000,
                    "currency": "INR",
                    "status": "captured",
                    "notes": {payments.NOTES_TENANT_KEY: str(tenant_id)},
                }
            }
        },
    }


async def test_the_same_payment_credits_once_however_many_times_it_is_delivered() -> None:
    """THE MONEY TEST, and it is deliberately not a docstring.

    Four deliveries of one payment: `payment.captured` twice (a plain redelivery, which
    the inbox catches) and `order.paid` twice (a DIFFERENT event carrying the SAME payment
    entity, which claims its own inbox row and is therefore caught only by the ledger's
    `ref` under the per-tenant credit lock). The wallet must move exactly ₹2,500, once.
    """
    tenant_id = await _tenant()
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    order_id = f"order_{uuid.uuid4().hex[:10]}"

    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt="rcpt-double",
            amount_inr=Decimal("2500"),
            provider_order_id=order_id,
            pack_id=None,
        )

    statuses: list[str] = []
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        for event in ("payment.captured", "payment.captured", "order.paid", "order.paid"):
            raw, headers = _signed(
                _envelope(
                    event=event, payment_id=payment_id, order_id=order_id, tenant_id=tenant_id
                )
            )
            response = await client.post("/hooks/v1/razorpay", content=raw, headers=headers)
            assert response.status_code == 200, response.text
            statuses.append(str(response.json()["status"]))

    # The first delivery credits; every later one — same event or the sibling one — reports
    # a duplicate rather than moving money.
    assert statuses[0] == "credited"
    assert statuses[1:] == ["duplicate", "duplicate", "duplicate"]

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT delta FROM credit_ledger WHERE tenant_id = :t AND ref = :r "
                    "AND reason = 'topup'"
                ),
                {"t": tenant_id, "r": payment_id},
            )
        ).all()
        balance = await get_balance(session, tenant_id=tenant_id)
        attempts = await read_attempts(session, tenant_id=tenant_id)

    assert len(rows) == 1, "one payment, one ledger row, whatever the delivery pattern"
    assert balance.amount_inr == Decimal("2500.0000")
    # And the client's screen learned about it in the same transaction as the credit.
    assert attempts[0].outcome == "captured"
    assert attempts[0].provider_payment_id == payment_id


async def test_a_payment_that_only_ever_arrives_by_webhook_still_credits() -> None:
    """THE BROWSER CALLBACK IS NOT THE SOURCE OF TRUTH. Nobody confirms anything here —
    no `/topups/callback` is posted, exactly as when a client closes the tab after paying
    — and the wallet moves anyway."""
    tenant_id = await _tenant()
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    raw, headers = _signed(
        _envelope(
            event="payment.captured",
            payment_id=payment_id,
            order_id="order_tabclosed",
            tenant_id=tenant_id,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        response = await client.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "credited"
    async with tenant_session(tenant_id) as session:
        assert (await get_balance(session, tenant_id=tenant_id)).amount_inr == Decimal("2500.0000")


async def test_a_failed_payment_marks_the_attempt_and_moves_no_money() -> None:
    tenant_id = await _tenant()
    order_id = f"order_{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt="rcpt-declined",
            amount_inr=Decimal("2500"),
            provider_order_id=order_id,
            pack_id=None,
        )
    raw, headers = _signed(
        {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_declined",
                        "order_id": order_id,
                        "error_code": "BAD_REQUEST_ERROR",
                        "notes": {payments.NOTES_TENANT_KEY: str(tenant_id)},
                    }
                }
            },
        }
    )
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        response = await client.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert response.json()["status"] == "failed"
    async with tenant_session(tenant_id) as session:
        attempts = await read_attempts(session, tenant_id=tenant_id)
        balance = await get_balance(session, tenant_id=tenant_id)
    # THE WHOLE POINT: a declined card has no ledger entry, and without this row the
    # client comes back to a screen indistinguishable from one they never touched.
    assert attempts[0].outcome == "failed"
    assert balance.amount_inr == Decimal("0")


# ============================================================================
# THE ROUTES
# ============================================================================


async def test_the_wallet_route_publishes_the_gate_s_verdict_and_the_working() -> None:
    tenant_id = await _tenant()
    await _past_entry(tenant_id, delta="5000", reason="topup", days_ago=10)
    await _past_entry(tenant_id, delta="-1000", reason="usage", days_ago=1)

    out = await read_wallet_summary(_principal(tenant_id))
    assert out.prepaid is True
    assert out.outbound_stopped is False
    assert out.balance_inr == Decimal("4000.00")
    assert out.is_low is False
    assert out.runway.basis == "projected"
    assert out.runway.days == 40
    assert out.drawdown.spent_inr == Decimal("1000.00")
    # The constants the projection was made under travel with it, so the screen can say
    # "over the last 30 days" without a second copy of the number.
    assert out.runway.window_days == 30
    assert out.runway.min_history_days == MIN_BURN_HISTORY_DAYS


async def test_the_ledger_route_pairs_every_payment_row_with_its_payment() -> None:
    tenant_id = await _tenant()
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal("2500"),
                currency="INR",
            ),
        )
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-40"), reason="usage")

    ledger = await read_wallet_ledger(_principal(tenant_id))
    # Newest first.
    assert [e.reason for e in ledger.entries] == ["usage", "topup"]
    assert ledger.entries[0].payment_ref is None
    assert ledger.entries[1].payment_ref == payment_id
    assert [p.payment_ref for p in ledger.payments] == [payment_id]
    assert ledger.payments[0].credited_inr == Decimal("2500.00")


async def test_a_receipt_is_a_receipt_and_never_calls_itself_a_tax_invoice() -> None:
    tenant_id = await _tenant()
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal("2500"),
                currency="INR",
            ),
        )
    receipt = await read_payment_receipt(payment_id, _principal(tenant_id))
    assert receipt.document_type == "receipt"
    assert receipt.amount_inr == Decimal("2500.00")
    assert "not a tax invoice" in receipt.note
    assert "tax invoice" not in receipt.note.replace("not a tax invoice", "")


async def test_a_receipt_for_another_organizations_payment_is_a_404() -> None:
    owner = await _tenant()
    stranger = await _tenant()
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    async with tenant_session(owner) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=owner,
                amount_inr=Decimal("2500"),
                currency="INR",
            ),
        )
    with pytest.raises(ProblemError):
        await read_payment_receipt(payment_id, _principal(stranger))


async def test_the_attempts_route_publishes_no_provider_identifier() -> None:
    """The client sees OUR reference and nothing of the provider's.

    Two reasons, and the second is the one worth a test: there is nothing a client can
    safely do with an order id, and publishing one would invite a second control that
    reopens a payment window — while `POST /v1/billing/topups/intent` is already the one
    place a payment starts. Two controls that both mint an order is how a client ends up
    with two orders for one top-up.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt="rcpt-live",
            amount_inr=Decimal("2500"),
            provider_order_id="order_live",
            pack_id=None,
        )
    rows = await read_topup_attempts(_principal(tenant_id))
    published = rows[0].model_dump()
    assert published["receipt"] == "rcpt-live"
    assert "order_live" not in str(published)
    assert set(published) == {
        "id",
        "receipt",
        "amount_inr",
        "pack_id",
        "outcome",
        "started_at",
    }


async def test_staff_may_see_the_wallet_so_a_stopped_dialler_has_its_explanation() -> None:
    """The founder's decision: everyone sees the balance and the ledger, only the owner
    buys. Asserted on the permission tables, which is where the two halves are decided."""
    from apps.api.core.rbac import MUTATING_PERMISSIONS, ROLE_PERMISSIONS

    assert "wallet:read" in ROLE_PERMISSIONS["staff"]
    assert "billing:read" not in ROLE_PERMISSIONS["staff"]
    assert "org:manage" not in ROLE_PERMISSIONS["staff"], "staff may not buy"
    # A READ, so a D-22 view-as operator keeps it — and the purchase, which is
    # `org:manage`, they correctly do not.
    assert "wallet:read" not in MUTATING_PERMISSIONS
    assert "org:manage" in MUTATING_PERMISSIONS


async def test_the_wallet_read_holds_no_second_credit_check() -> None:
    """`compliance.service.credits_exhausted` is the ONE gate. `billing/wallet.py` asks
    it through its caller and must never grow a comparison of its own — the founder said
    so in those words ("do NOT build a second credit check")."""
    import ast
    import inspect

    from apps.api.billing import wallet

    # THE AST, NOT THE TEXT. An earlier draft grepped the source and failed on this
    # module's own docstring, which names the gate in prose precisely to say it is not
    # called here — so the check has to be about what the module DOES.
    tree = ast.parse(inspect.getsource(wallet))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "credits_exhausted" not in imported, "the gate is ASKED by the route, not here"
    assert "credits_exhausted" not in called
    assert "PREPAID_TIERS" not in imported, "the tier test belongs to the gate, not to a read"
    assert "plan_tier_of" not in imported


async def test_read_wallet_takes_the_verdicts_it_is_given() -> None:
    """The module cannot decide dialling for itself: both verdicts are arguments."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        summary = await read_wallet(
            session,
            tenant_id=tenant_id,
            prepaid=True,
            outbound_stopped=True,
            rate_inr_per_min=Decimal("8"),
        )
    assert summary.outbound_stopped is True
    assert summary.prepaid is True
