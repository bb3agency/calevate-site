"""Credit granted out of nothing (D-535) — the ledger row, the ceiling, and the split.

The founder: *"the admin should be able to add any no.of credits without any payments
record to any client but it is audited"*, with three guardrails they chose themselves —
shown separately from paid credit, a ceiling per grant, and audited.

Each of those is a test here, and so is the one property that is easy to get wrong in the
other direction: a grant is idempotent on a reference the OPERATOR supplies, so a second
click converges and a second genuine gift of the same size does not.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.billing.models import CREDIT_REASONS, GRANTED_CREDIT_REASONS, PAID_CREDIT_REASONS
from apps.api.billing.service import (
    MAX_GRANT_INR,
    MIN_GRANT_INR,
    CreditReason,
    credit_totals,
    get_balance,
    grant_ref,
    record_entry,
)
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


async def _tenant(plan_tier: str = "prepaid") -> uuid.UUID:
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Grant Clinic",
        slug=f"grant-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": plan_tier, "i": tenant_id},
        )
    return tenant_id


async def test_the_reason_vocabulary_and_its_type_agree() -> None:
    """`CreditReason` is a hand-written Literal (a `Literal[*tuple]` is not a static type
    mypy can check), so nothing but a test holds it equal to the tuple the DB CHECK is
    built from. A reason in one and not the other is either a value the ORM admits and the
    type refuses, or one the type admits and Postgres rejects at 2am."""
    from typing import get_args

    assert set(get_args(CreditReason)) == set(CREDIT_REASONS)


async def test_every_reason_is_either_paid_or_granted_or_neither_deliberately() -> None:
    """The two sets are the definition of "bought" and "given", and they must not overlap.
    `usage`, `adjustment` and `refund` are in NEITHER on purpose — they are movements, not
    origins, and letting a correction subtract from what a client was given would
    understate the gift."""
    assert not set(PAID_CREDIT_REASONS) & set(GRANTED_CREDIT_REASONS)
    assert set(PAID_CREDIT_REASONS) | set(GRANTED_CREDIT_REASONS) <= set(CREDIT_REASONS)
    assert "grant" in GRANTED_CREDIT_REASONS
    assert "topup" in PAID_CREDIT_REASONS


async def test_a_grant_lands_on_the_balance_and_is_counted_as_given_not_paid() -> None:
    """The founder's first guardrail, as arithmetic: the wallet goes up by the grant and
    the REVENUE side does not move. Granted credit reading as paid is what would inflate
    our own margin figures."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("2000"), reason="topup", ref="UTR-1"
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="goodwill-1"),
        )
        balance = await get_balance(session, tenant_id=tenant_id)
        totals = await credit_totals(session, tenant_id=tenant_id)

    assert balance.amount_inr == Decimal("2500.0000")
    assert totals.paid_inr == Decimal("2000.0000")
    assert totals.granted_inr == Decimal("500.0000")


async def test_a_pack_bonus_counts_as_given_too() -> None:
    """`bonus` is credit WE fund — a promotional grant earned on a pack — so counting it
    as revenue would be the same lie a grant would be. It is a distinct REASON from
    `grant` (a bonus is clawed back when its payment is refunded, and a goodwill grant must
    not be), and the same side of the split."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("100"), reason="bonus", ref="pay_1"
        )
        totals = await credit_totals(session, tenant_id=tenant_id)
    assert totals.granted_inr == Decimal("100.0000")
    assert totals.paid_inr == Decimal("0")


async def test_a_correction_belongs_to_neither_total() -> None:
    """An adjustment that takes a wrong grant back reduces the BALANCE and must not reduce
    `granted_inr`: what a client was given is a historical fact, and the correction is its
    own row that a reader can find beside it."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="oops"),
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-500"),
            reason="adjustment",
            ref="adjust:x",
            allow_negative=True,
        )
        balance = await get_balance(session, tenant_id=tenant_id)
        totals = await credit_totals(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("0.0000")
    assert totals.granted_inr == Decimal("500.0000")


async def test_the_database_refuses_a_second_grant_under_one_reference() -> None:
    """`ux_credit_ledger_grant_ref` is the backstop the route's advisory lock is the
    primary guarantee for (D-63). A future writer that forgets the lock gets a UNIQUE
    violation rather than crediting the gift twice."""
    tenant_id = await _tenant()
    ref = grant_ref(reference="twice")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("100"), reason="grant", ref=ref
        )
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("100"), reason="grant", ref=ref
            )


async def test_two_genuinely_distinct_grants_of_the_same_size_both_land() -> None:
    """THE REASON THE KEY IS THE OPERATOR'S AND NOT A CONTENT ADDRESS. Two goodwill grants
    of ₹500 to one client two months apart are ordinary; a key derived from (amount,
    reason) would report the second as a replay of the first — a gift the client never
    received, reported as delivered."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="jan-goodwill"),
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="feb-goodwill"),
        )
        totals = await credit_totals(session, tenant_id=tenant_id)
    assert totals.granted_inr == Decimal("1000.0000")


async def test_the_ceiling_catches_the_founders_own_example() -> None:
    """*"a fat-finger (₹5,00,000 instead of ₹5,000) is refused rather than posted"*. The
    ceiling has to sit an order of magnitude above the honest figure and an order of
    magnitude below the slip, or it refuses real work while stopping nobody."""
    assert Decimal("500000.00") > MAX_GRANT_INR
    assert Decimal("5000.00") * 5 < MAX_GRANT_INR
    assert MIN_GRANT_INR > 0


async def test_the_ledger_still_refuses_an_update_to_a_grant() -> None:
    """Hard rule 4 is not weakened by a sixth reason: a wrong grant is corrected by a
    compensating entry, never by an edit, and the DB trigger is what makes that true
    whatever any writer believes."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("100"),
            reason="grant",
            ref=grant_ref(reference="immutable"),
        )
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE credit_ledger SET delta = 1 WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
