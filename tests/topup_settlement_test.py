"""The webhook that never arrives — the one payment failure no handler can see.

Every other alarm on the top-up path is raised INSIDE `razorpay_webhook`, so all of them
need the delivery to reach us first. The failure this suite is about is the delivery
never arriving: a webhook registered against the wrong hostname, an un-subscribed event,
a firewall. `apps/workers/topup_settlement.py` is the only reader in the platform that
can see it, and the two properties that make it worth having are both here:

* it FIRES when an order is stranded and the webhook leg is silent, and
* it stays QUIET when a client merely abandoned a Checkout window — which produces a byte
  -for-byte identical row, and is the reason a naive "alert on any old attempt" sweep
  would have been switched off inside a week.

Nothing here asserts anything about Razorpay. The job talks to no vendor and credits
nothing; `tests/wallet_test.py` owns the ledger invariants it must not disturb.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.wallet import record_attempt, settle_attempt
from apps.api.db.session import tenant_session
from apps.workers import topup_settlement
from apps.workers.fleet_walk import WalkBudget
from apps.workers.topup_settlement import (
    LOOKBACK,
    SETTLEMENT_GRACE,
    scan_tenants,
    sweep_topup_settlement,
)
from sqlalchemy import text
from tests.conftest import accept_agreements

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Settlement Clinic",
        slug=f"stl-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id


async def _attempt(
    tenant_id: UUID,
    *,
    order_id: str | None,
    age: timedelta,
    settled: str | None = None,
    settled_age: timedelta | None = None,
    now: datetime = NOW,
) -> None:
    """One attempt row, aged backwards from `now` (the fixed `NOW` unless told otherwise).

    `created_at` and `updated_at` are server-side clocks, so the ages are applied by an
    UPDATE afterwards rather than by faking `now()` — `topup_attempts` is deliberately
    NOT in `APPEND_ONLY_TABLES` (it is a narrative, not money), so this is an ordinary
    write and not a hole poked in hard rule 4.
    """
    receipt = f"rcpt-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await record_attempt(
            session,
            tenant_id=tenant_id,
            receipt=receipt,
            amount_inr=Decimal("500"),
            provider_order_id=order_id,
            pack_id=None,
        )
        if settled is not None:
            await settle_attempt(
                session,
                tenant_id=tenant_id,
                order_id=order_id,
                payment_id=f"pay_{uuid.uuid4().hex[:8]}",
                status=settled,
            )
        await session.execute(
            text(
                "UPDATE topup_attempts SET created_at = :created, updated_at = :updated "
                "WHERE tenant_id = :tid AND receipt = :receipt"
            ),
            {
                "created": now - age,
                "updated": now - (settled_age if settled_age is not None else age),
                "tid": tenant_id,
                "receipt": receipt,
            },
        )


# --- the alarm fires when it should ---------------------------------------------------


async def test_a_stranded_order_with_a_silent_webhook_leg_is_reported() -> None:
    """The misconfigured-URL case: an order exists at the provider and nothing has ever
    come back. This is the state a client experiences as "I paid and nothing happened"."""
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id="order_lost", age=SETTLEMENT_GRACE + timedelta(minutes=5))

    scan = await scan_tenants([tenant_id], now=NOW)

    assert scan.silent is True
    assert [order.order_id for order in scan.stuck] == ["order_lost"]
    assert scan.last_settlement is None


async def test_the_alert_body_names_the_order_and_the_hostname_trap() -> None:
    """The operator's first action is to check the URL, so the alert says so — and it
    names ORDER ids, which is what the provider's dashboard is searched by."""
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id="order_named", age=timedelta(hours=2))
    scan = await scan_tenants([tenant_id], now=NOW)

    body = topup_settlement._describe(scan, now=NOW)

    assert "order_named" in body
    assert "/hooks/v1/razorpay" in body
    assert "hooks." in body


# --- and stays quiet when it should ---------------------------------------------------


async def test_a_settlement_after_the_stranded_order_proves_the_leg_is_alive() -> None:
    """THE PROPERTY THAT KEEPS THIS ALARM USABLE. An abandoned Checkout window leaves the
    same row as a lost webhook; the only thing that tells them apart is whether anything
    at all has been settled since. One client abandoning while another pays is the normal
    state of a working payment page, and it must not page anybody."""
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id="order_abandoned", age=timedelta(hours=3))
    await _attempt(
        tenant_id,
        order_id="order_paid",
        age=timedelta(hours=2),
        settled="captured",
        settled_age=timedelta(hours=2),
    )

    scan = await scan_tenants([tenant_id], now=NOW)

    assert scan.stuck, "the abandoned order is still stuck — it is the VERDICT that changes"
    assert scan.silent is False


async def test_a_declined_card_counts_as_a_sign_of_life() -> None:
    """`payment.failed` proves deliveries are reaching us exactly as well as
    `payment.captured` does. Counting only successes would page every time a client's
    first card bounced and their second one was never tried."""
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id="order_stranded", age=timedelta(hours=3))
    await _attempt(
        tenant_id,
        order_id="order_declined",
        age=timedelta(hours=2),
        settled="failed",
        settled_age=timedelta(hours=2),
    )

    assert (await scan_tenants([tenant_id], now=NOW)).silent is False


async def test_a_fresh_order_inside_the_grace_is_not_stranded_yet() -> None:
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id="order_new", age=SETTLEMENT_GRACE - timedelta(minutes=5))

    scan = await scan_tenants([tenant_id], now=NOW)

    assert scan.stuck == ()
    assert scan.silent is False


async def test_an_attempt_with_no_provider_order_is_never_stranded() -> None:
    """A NULL order id means no order was created at the provider — the deployment holds
    no API secret, or the order call failed — so no money can have been taken and there is
    nothing for a webhook to have missed."""
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id=None, age=timedelta(days=1))

    assert (await scan_tenants([tenant_id], now=NOW)).stuck == ()


async def test_an_order_older_than_the_lookback_stops_being_news() -> None:
    """Without this the alarm becomes permanent on a deployment where nobody has paid
    since, and a permanent alarm is a silenced one. The client's own credits screen still
    shows the row as `unfinished`, which is where something this old belongs."""
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id="order_ancient", age=LOOKBACK + timedelta(days=1))

    scan = await scan_tenants([tenant_id], now=NOW)

    assert scan.stuck == ()
    assert scan.silent is False


# --- the walk itself ------------------------------------------------------------------


async def test_a_truncated_walk_says_so_rather_than_reporting_a_smaller_number() -> None:
    """A budget-exhausted pass has seen less than it appears to have seen, and silence
    there reads exactly like a healthy fleet (D-369)."""
    tenant_id = await _tenant()
    spent = WalkBudget(budget=timedelta(seconds=-1))

    scan = await scan_tenants([tenant_id], now=NOW, budget=spent)

    assert scan.truncated is True
    assert scan.tenants_probed == 0
    assert scan.tenants_unreached == 1


async def test_the_sweep_pages_once_and_returns_its_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the REGISTERED job, alert seam included.

    Aged against the real clock rather than `NOW`, because the job asks the time itself —
    pinning that would be pinning `datetime`, and what is worth proving here is that the
    job reads the same rows the scan does and raises exactly one page.
    """
    tenant_id = await _tenant()
    await _attempt(tenant_id, order_id="order_swept", age=timedelta(hours=2), now=datetime.now(UTC))
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(
        topup_settlement, "alert", lambda stage, code, **kw: raised.append((stage, code))
    )
    # ONE tenant, so another test's abandoned window cannot decide this assertion. The
    # real enumeration is `qa_sampling._DIRECTORY`'s, shared verbatim.
    monkeypatch.setattr(topup_settlement, "_DIRECTORY", f"SELECT '{tenant_id}'::uuid AS id")

    summary = json.loads(await sweep_topup_settlement({"job_try": 1}))

    assert raised == [("WORKER_STALL", "topup_settlement_silent")]
    assert summary["stuck_orders"] == 1
    assert summary["webhook_leg_silent"] is True
    assert summary["tenants_unreached"] == 0
