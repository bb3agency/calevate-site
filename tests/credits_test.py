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


async def _entry_count(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalar()
            or 0
        )


async def test_an_entry_that_moves_nothing_is_not_written_to_the_ledger() -> None:
    """A zero delta is not an event. `credit_ledger` is append-only (hard rule 4), so
    nothing that lands on it can ever be tidied away — and a ledger that records "₹0.00,
    usage" every time a free-tier or zero-cost call completes buries the entries that
    describe real money under rows that describe none.

    The balance answer must still be correct and must still be a `Balance`, because the
    caller uses the return value: pipelines read it to decide whether the wallet is
    exhausted, and returning None or a bare Decimal for the zero case would move the
    failure into them.

    A zero delta must also not take the per-tenant advisory lock: it has nothing to
    serialize against, and a metering run over a batch of zero-cost calls would
    otherwise queue behind every other writer for that tenant.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("250.00"), reason="topup")
        unchanged = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("0"), reason="usage", ref="zero-cost-call"
        )
        # `Decimal("0.0000")` is the same number spelled differently — the guard must be
        # numeric, not a string or an `is` comparison.
        also_unchanged = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("0.0000"), reason="adjustment"
        )

    assert unchanged.amount_inr == Decimal("250.0000")
    assert str(unchanged.amount_inr) == "250.0000", "hard rule 7: exact digits, never a float"
    assert also_unchanged.amount_inr == Decimal("250.0000")
    assert unchanged.is_exhausted is False
    assert await _entry_count(tenant_id) == 1, "only the top-up belongs on the ledger"


async def test_a_call_that_cost_nothing_leaves_the_wallet_alone() -> None:
    """The same rule at the caller the post-call pipeline actually uses.

    A completed call with no billable cost is ordinary — an inbound call on a plan whose
    telephony is included, a call that failed before connecting, a metering run where
    the engine reported no cost yet. Charging ₹0.00 for it would put a row on an
    append-only ledger for every such call, and a NEGATIVE amount arriving here (a cost
    correction sent to the wrong function) must not be silently converted into a CREDIT:
    `charge_for_call` debits, and a refund is a compensating `adjustment` entry that
    somebody decides on.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("100.00"), reason="topup")
        await charge_for_call(
            session, tenant_id=tenant_id, call_id=uuid.uuid4(), amount_inr=Decimal("0")
        )
        await charge_for_call(
            session, tenant_id=tenant_id, call_id=uuid.uuid4(), amount_inr=Decimal("-5.00")
        )
        balance = await get_balance(session, tenant_id=tenant_id)

    assert str(balance.amount_inr) == "100.0000", "neither call may move the wallet"
    assert await _entry_count(tenant_id) == 1, "only the top-up belongs on the ledger"


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


async def _verify_kyc(tenant_id: uuid.UUID) -> None:
    """Clear this tenant's subscriber KYC (migration a3f6b1e02d95).

    Needed because `check_dispatch` asks about identity BEFORE money for self-serve
    tenants — telling an unverified account to top up when topping up will not let them
    dial is a worse answer than the right one. So a test about the WALLET has to get
    past the identity gate first, exactly as production does.
    """
    from apps.api.compliance.kyc import record_kyc
    from apps.api.db.session import untenanted_session

    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    async with tenant_session(tenant_id) as session:
        await record_kyc(
            session,
            tenant_id=tenant_id,
            status="verified",
            document_kind="cin",
            document_ref="U74999TG2026PTC000001",
            verified_by_admin_id=admin_id,
        )


async def test_an_empty_wallet_blocks_dispatch_for_a_self_serve_tenant() -> None:
    tenant_id = await _tenant("self_serve")
    await _verify_kyc(tenant_id)
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
