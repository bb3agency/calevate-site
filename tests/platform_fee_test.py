"""The monthly platform fee (D-707): one switch, a separate payment, a grace period, then
OUTBOUND pauses until it is paid — and inbound never does.

What is pinned, worst first:

1. **The fee never touches calling credit.** A fee payment through the webhook writes a
   `monthly_fee_payments` row and no `credit_ledger` entry.
2. **The pause is outbound-only and lifts on payment.** Past the grace period an unpaid
   fee refuses the next outbound dial with `platform_fee_overdue`; an inbound-only agent is
   refused for its direction, never for the fee; recording the payment opens the gate on
   the very next dial.
3. **Exempt is exempt.** A free-trial account and a waived one are raised no fee and are
   never paused; turning the switch off lifts every pause.
4. **One fee per client per month**, held by the database.
5. **Tenancy and the ledger** (hard rules 1 and 4): a neighbour's session reads zero rows
   of either table, and a payment row cannot be edited or deleted.
6. **The surfaces**: the client's read, the operator's audited waiver and bank-transfer
   record, and the public rate card quoting the fee only while it is on.

CONCURRENCY: every case mints its own tenant.
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
from apps.api.billing.payment_objects import PLATFORM_FEE, record_route
from apps.api.billing.payment_routes import webhook_router
from apps.api.billing.platform_fee import (
    GRACE_PERIOD,
    PLATFORM_FEE_RULE,
    attach_order,
    exemption_of,
    issue_charge,
    list_charges,
    platform_fee_paused,
    read_charge,
)
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers.billing import compose, issue_platform_fees, notice_due
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import fund_wallet

pytestmark = [pytest.mark.rls]

FEE = Decimal("1999.00")
WEBHOOK_SECRET = "whsec_fee_test"


@pytest.fixture(autouse=True)
def _fee_on(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "platform_fee_enabled", True)
    monkeypatch.setattr(settings, "platform_fee_inr", FEE)


@pytest.fixture
def _gate_reaches_money(monkeypatch: pytest.MonkeyPatch) -> None:
    """The halt and the clock pinned, for `admin_cap_arms_the_gate_test`'s reason: both
    can only ever mask an ALLOWED result, and the refusals here assert the rule by name."""
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Fee Clinic",
        slug=f"fee-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.com",
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'active' WHERE id = :t"), {"t": tenant_id}
        )
    return tenant_id


async def _dialling_tenant() -> tuple[UUID, UUID]:
    """A prepaid tenant that lawfully dials, funded, with a live outbound agent."""
    from tests.spend_caps_test import _tenant as _armed_tenant

    tenant_id, agent_id, _ref = await _armed_tenant(f"fee{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'prepaid', status = 'active' WHERE id = :t"),
            {"t": tenant_id},
        )
    await fund_wallet(tenant_id)
    return tenant_id, agent_id


async def _issue(tenant_id: UUID, *, at: datetime) -> UUID:
    async with tenant_session(tenant_id) as session:
        charge_id = await issue_charge(session, tenant_id=tenant_id, amount_inr=FEE, at=at)
    assert charge_id is not None
    return charge_id


async def _gate(tenant_id: UUID, agent_id: UUID) -> Any:
    phone = f"+9199{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )


async def _admin(role: str = "superadmin") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


def _http() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _audit(tenant_id: UUID, action: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = :a"),
                    {"t": tenant_id, "a": action},
                )
            ).scalar()
            or 0
        )


# --- the gate ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_gate_reaches_money")
async def test_an_unpaid_fee_pauses_outbound_after_grace_and_paying_lifts_it() -> None:
    tenant_id, agent_id = await _dialling_tenant()
    assert (await _gate(tenant_id, agent_id)).allowed, "nothing is owed yet"

    charge_id = await _issue(tenant_id, at=datetime.now(UTC) - timedelta(days=1))
    assert (await _gate(tenant_id, agent_id)).allowed, "inside the grace period calls go on"

    late = await _tenant_with_late_fee(tenant_id, charge_id)
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == PLATFORM_FEE_RULE, decision
    assert "Incoming calls keep working" in decision.reason

    async with _http() as http:
        paid = await http.post(
            f"/v1/admin/tenants/{tenant_id}/platform-fee/{late}/payments",
            json={"reference": f"UTR{uuid.uuid4().hex[:12]}"},
            headers={"Authorization": f"Bearer {await _admin('operator')}"},
        )
    assert paid.status_code == 200, paid.text
    assert paid.json() == {"charge_id": str(late), "recorded": True, "status": "paid"}
    assert (await _gate(tenant_id, agent_id)).allowed, "paying must lift the pause at once"
    assert await _audit(tenant_id, "tenant.platform_fee_paid_manually") == 1


async def _tenant_with_late_fee(tenant_id: UUID, charge_id: UUID) -> UUID:
    """Move one fee's grace period into the past — the state a client reaches by not
    paying for seven days."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE monthly_fee_charges SET issued_at = :i, grace_ends_at = :g WHERE id = :c"),
            {
                "i": datetime.now(UTC) - GRACE_PERIOD - timedelta(days=1),
                "g": datetime.now(UTC) - timedelta(days=1),
                "c": charge_id,
            },
        )
    return charge_id


@pytest.mark.usefixtures("_gate_reaches_money")
async def test_an_inbound_agent_is_never_refused_for_the_fee() -> None:
    tenant_id, _agent_id = await _dialling_tenant()
    await _tenant_with_late_fee(tenant_id, await _issue(tenant_id, at=datetime.now(UTC)))
    async with tenant_session(tenant_id) as session:
        inbound = (
            await session.execute(text("SELECT id FROM agents WHERE direction = 'inbound' LIMIT 1"))
        ).scalar()
    decision = await _gate(tenant_id, UUID(str(inbound)))
    assert decision.rule != PLATFORM_FEE_RULE


async def test_switching_the_fee_off_lifts_every_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = await _tenant()
    await _tenant_with_late_fee(tenant_id, await _issue(tenant_id, at=datetime.now(UTC)))
    async with tenant_session(tenant_id) as session:
        assert await platform_fee_paused(session, tenant_id=tenant_id)
    monkeypatch.setattr(get_settings(), "platform_fee_enabled", False)
    async with tenant_session(tenant_id) as session:
        assert not await platform_fee_paused(session, tenant_id=tenant_id)


# --- exemptions -------------------------------------------------------------------------


async def test_a_waived_client_is_never_paused_and_the_waiver_is_audited() -> None:
    tenant_id = await _tenant()
    await _tenant_with_late_fee(tenant_id, await _issue(tenant_id, at=datetime.now(UTC)))
    token = await _admin("operator")
    async with _http() as http:
        waived = await http.put(
            f"/v1/admin/tenants/{tenant_id}/platform-fee/waiver",
            json={"reason": "lighthouse client, agreed by founder"},
            headers={"Authorization": f"Bearer {token}"},
        )
        again = await http.put(
            f"/v1/admin/tenants/{tenant_id}/platform-fee/waiver",
            json={"reason": "lighthouse client, agreed by founder"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert waived.status_code == 200, waived.text
    body = waived.json()
    assert body["exemption"] == "waiver" and body["outbound_paused"] is False
    assert body["waiver"]["reason"] == "lighthouse client, agreed by founder"
    assert body["charges"][0]["status"] == "waived"
    assert again.status_code == 200
    assert await _audit(tenant_id, "tenant.platform_fee_waived") == 1, "a no-op is not audited"

    async with _http() as http:
        withdrawn = await http.delete(
            f"/v1/admin/tenants/{tenant_id}/platform-fee/waiver",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert withdrawn.json()["outbound_paused"] is True
    assert await _audit(tenant_id, "tenant.platform_fee_waiver_withdrawn") == 1


async def test_a_trial_account_is_exempt_and_is_raised_no_fee() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'trial' WHERE id = :t"), {"t": tenant_id}
        )
        assert await exemption_of(session, tenant_id=tenant_id, at=datetime.now(UTC)) == "trial"
    await issue_platform_fees({})
    async with tenant_session(tenant_id) as session:
        assert await list_charges(session, tenant_id=tenant_id) == []


# --- the job ----------------------------------------------------------------------------


async def test_the_job_raises_one_fee_per_month_and_claims_its_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    class _Transport:
        def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
            sent.append(subject)
            return True

    monkeypatch.setattr("apps.workers.billing.get_transport", lambda: _Transport())
    tenant_id = await _tenant()
    await issue_platform_fees({})
    await issue_platform_fees({})
    async with tenant_session(tenant_id) as session:
        charges = await list_charges(session, tenant_id=tenant_id)
    assert len(charges) == 1, "one fee per client per month, however many ticks run"
    assert charges[0].amount_inr == FEE
    assert charges[0].issued_notice_sent_at is not None
    assert "Your monthly platform fee is due" in sent


async def test_the_job_raises_nothing_while_the_switch_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "platform_fee_enabled", False)
    tenant_id = await _tenant()
    assert json.loads(await issue_platform_fees({})) == {"enabled": False}
    async with tenant_session(tenant_id) as session:
        assert await list_charges(session, tenant_id=tenant_id) == []


async def test_a_second_fee_for_the_same_month_is_not_raised() -> None:
    tenant_id = await _tenant()
    now = datetime.now(UTC)
    await _issue(tenant_id, at=now)
    async with tenant_session(tenant_id) as session:
        assert await issue_charge(session, tenant_id=tenant_id, amount_inr=FEE, at=now) is None


async def test_the_notice_ladder_and_its_copy() -> None:
    tenant_id = await _tenant()
    now = datetime.now(UTC)
    charge_id = await _issue(tenant_id, at=now)
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
    assert charge is not None
    assert notice_due(charge, now=now) == "issued"
    assert notice_due(charge, now=charge.grace_ends_at - timedelta(hours=1)) == "reminder"
    assert notice_due(charge, now=charge.grace_ends_at) == "paused"
    for notice in ("issued", "reminder", "paused"):
        body = compose(notice, charge=charge, slug="fee-clinic")  # type: ignore[arg-type]
        assert "Incoming calls keep being answered" in body
        assert "₹1,999.00" in body


# --- the payment ------------------------------------------------------------------------


async def test_a_fee_paid_through_the_webhook_never_touches_calling_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_fee")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp_secret_fee")
    monkeypatch.setattr(settings, "razorpay_mode", None)

    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    order_id = f"order_{uuid.uuid4().hex[:14]}"
    async with tenant_session(tenant_id) as session:
        await record_route(
            session,
            tenant_id=tenant_id,
            object_id=order_id,
            kind="order",
            purpose=PLATFORM_FEE,
            amount_inr=FEE,
        )
        await attach_order(session, tenant_id=tenant_id, charge_id=charge_id, order_id=order_id)

    payment_id = f"pay_{uuid.uuid4().hex[:14]}"
    envelope = {
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 199900,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": order_id,
                    "international": False,
                    "notes": {payments.NOTES_TENANT_KEY: str(tenant_id)},
                }
            }
        },
    }
    raw = json.dumps(envelope, separators=(",", ":")).encode()
    headers = {
        payments.SIGNATURE_HEADER: hmac.new(
            WEBHOOK_SECRET.encode(), raw, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }
    hook = FastAPI()
    install_error_handlers(hook)
    hook.include_router(webhook_router)
    async with AsyncClient(transport=ASGITransport(app=hook), base_url="http://api") as http:
        first = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
        replay = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "fee_paid"
    assert replay.json()["status"] == "duplicate"

    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
        ledger = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t AND ref = :r"),
                {"t": tenant_id, "r": payment_id},
            )
        ).scalar()
    assert charge is not None and charge.paid and charge.payment_method == "razorpay"
    assert ledger == 0, "a platform fee must never credit the wallet"


# --- the client's read and the public card ----------------------------------------------


async def test_the_client_reads_its_fee_and_the_public_card_quotes_it_only_while_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    await _issue(tenant_id, at=datetime.now(UTC))
    owner = await _owner(tenant_id)
    async with _http() as http:
        mine = await http.get(
            "/v1/billing/platform-fee", headers={"Authorization": f"Bearer {owner}"}
        )
        card_on = await http.get("/v1/public/rate-card")
        monkeypatch.setattr(get_settings(), "platform_fee_enabled", False)
        card_off = await http.get("/v1/public/rate-card")
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["enabled"] is True and body["amount_inr"] == "1999.00"
    assert body["charges"][0]["status"] == "due"
    assert body["outbound_paused"] is False
    assert card_on.json()["platform_fee_inr_per_month"] == "1999.00"
    assert card_off.json()["platform_fee_inr_per_month"] is None


async def _owner(tenant_id: UUID) -> str:
    """A client-realm token for a new owner of `tenant_id`, its only membership."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, email_verified_at, created_at, updated_at) "
                "VALUES (:i, :e, now(), now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'owner', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return f"dev:client:{user_id}"


# --- tenancy and the ledger (hard rules 1 and 4) ----------------------------------------


async def test_a_neighbour_reads_zero_rows_of_either_table() -> None:
    tenant_id = await _tenant()
    neighbour = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        charge = await read_charge(session, tenant_id=tenant_id, charge_id=charge_id)
        assert charge is not None
        await session.execute(
            text(
                "INSERT INTO monthly_fee_payments (id, tenant_id, charge_id, amount, method, "
                "payment_ref, paid_at) VALUES (:i, :t, :c, :a, 'manual', :r, now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "c": charge_id,
                "a": FEE,
                "r": f"UTR-{uuid.uuid4()}",
            },
        )
    async with tenant_session(neighbour) as session:
        for table in ("monthly_fee_charges", "monthly_fee_payments"):
            seen = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            ).scalar()
            assert seen == 0, f"{table} leaked across tenants"


async def test_a_fee_payment_cannot_be_edited_or_deleted() -> None:
    tenant_id = await _tenant()
    charge_id = await _issue(tenant_id, at=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO monthly_fee_payments (id, tenant_id, charge_id, amount, method, "
                "payment_ref, paid_at) VALUES (:i, :t, :c, :a, 'manual', :r, now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "c": charge_id,
                "a": FEE,
                "r": f"UTR-{uuid.uuid4()}",
            },
        )
    for statement in (
        "UPDATE monthly_fee_payments SET payment_ref = 'X' WHERE tenant_id = :t",
        "DELETE FROM monthly_fee_payments WHERE tenant_id = :t",
    ):
        with pytest.raises(DBAPIError):
            async with tenant_session(tenant_id) as session:
                await session.execute(text(statement), {"t": tenant_id})
