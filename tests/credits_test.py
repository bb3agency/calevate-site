"""Prepaid credits (D-34/D-39) — the ledger, the race, and the two motions.

D-12 says metering is not retrofittable, which is why this exists in M1 with no UI. The
tests are correspondingly about correctness under concurrency and about not breaking
the managed motion, not about screens.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import charge_for_call, get_balance, record_entry
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def _tenant(plan_tier: str = "self_serve") -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Credit Clinic",
        slug=f"cred-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id


async def test_a_new_tenant_has_a_zero_balance() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("0")
    assert balance.is_exhausted


async def test_topups_and_usage_accumulate_into_balance_after() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("1000"), reason="topup")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-250.50"), reason="usage")
        balance = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("100"), reason="refund"
        )
    assert balance.amount_inr == Decimal("849.5000")
    assert not balance.is_exhausted


async def test_a_charge_that_would_overdraw_is_refused_by_default() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("100"), reason="topup")
        with pytest.raises(ProblemError) as exc:
            await record_entry(session, tenant_id=tenant_id, delta=Decimal("-500"), reason="usage")
    assert exc.value.code == "insufficient_credits"


async def test_a_completed_call_is_charged_even_into_the_negative() -> None:
    """The call already happened. A cost we refuse to record is a cost we later cannot
    explain — prevention belongs at the pre-dispatch gate, not at the ledger."""
    tenant_id = await _tenant()
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await charge_for_call(
            session, tenant_id=tenant_id, call_id=call_id, amount_inr=Decimal("42.5")
        )
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("-42.5000")


async def test_charging_the_same_call_twice_does_not_double_bill() -> None:
    """The post-call pipeline is re-runnable by design; a ledger that double-charges on
    a replay is worse than no ledger."""
    tenant_id = await _tenant()
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup")
        for _ in range(3):
            await charge_for_call(
                session, tenant_id=tenant_id, call_id=call_id, amount_inr=Decimal("30")
            )
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("470.0000")


async def test_concurrent_charges_cannot_both_read_the_same_starting_balance() -> None:
    """The race the FOR UPDATE exists for: two charges landing at once must serialize,
    or a wallet with ₹100 pays for two ₹80 calls."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("100"), reason="topup")

    async def charge(amount: str) -> str:
        try:
            async with tenant_session(tenant_id) as session:
                await record_entry(
                    session, tenant_id=tenant_id, delta=Decimal(amount), reason="usage"
                )
            return "ok"
        except (ProblemError, DBAPIError):
            return "refused"

    results = await asyncio.gather(charge("-80"), charge("-80"))
    assert results.count("ok") == 1, f"exactly one charge may succeed, got {results}"

    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("20.0000"), "the wallet cannot go below what it held"


async def test_the_ledger_is_append_only() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("100"), reason="topup")
    with pytest.raises(DBAPIError, match="append-only"):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE credit_ledger SET delta = 999 WHERE tenant_id = :t"),
                {"t": tenant_id},
            )


async def test_an_empty_wallet_blocks_dispatch_for_a_self_serve_tenant() -> None:
    tenant_id = await _tenant("self_serve")
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500021"
        )
    assert not decision.allowed
    assert decision.rule == "no_credits"


async def test_a_managed_tenant_is_never_blocked_by_credits() -> None:
    """D-34: one product, two motions. A managed client is invoiced against a retainer,
    so blocking their calls over a credit balance they never bought would be an outage
    caused by a concept that does not apply to them."""
    tenant_id = await _tenant("managed")
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500022"
        )
    # Either allowed, or blocked for a reason that is NOT credits (calling hours, say).
    assert decision.rule != "no_credits"


async def test_credit_entries_are_tenant_isolated() -> None:
    a = await _tenant()
    b = await _tenant()
    async with tenant_session(a) as session:
        await record_entry(session, tenant_id=a, delta=Decimal("500"), reason="topup")
    async with tenant_session(b) as session:
        rows = (await session.execute(text("SELECT count(*) FROM credit_ledger"))).scalar()
        balance = await get_balance(session, tenant_id=b)
    assert rows == 0, "a tenant must not see another tenant's wallet"
    assert balance.amount_inr == Decimal("0")
