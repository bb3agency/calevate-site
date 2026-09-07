"""Fixtures shared by the `credit_lots_*` suites (D-547, Phase B1).

One place to make a tenant, put credit on its wallet and open a lot, so that eight test
files cannot drift about what "a funded wallet with two lots" means. Deliberately NOT in
`tests/conftest.py`: nothing outside this feature needs them yet, and a helper in conftest
is a helper every suite pays to import.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.api.admin import service as admin_service
from apps.api.billing import lots
from apps.api.billing.service import record_entry
from apps.api.db.session import tenant_session
from sqlalchemy import text

#: The ₹5,000-pack rates (plan §2.2 `growth`), used wherever a test needs "some ordinary
#: pack" and does not care which.
GROWTH = (Decimal("5.00"), Decimal("7.00"))
#: The ₹15,000-pack rates (`plus`) — a CHEAPER minute on both voices, which is what makes
#: a two-lot split at two rates visible.
PLUS = (Decimal("4.70"), Decimal("6.50"))


async def make_tenant(prefix: str = "lot") -> UUID:
    created = await admin_service.create_organization(
        name="Lots Clinic",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def credit_entry(tenant_id: UUID, *, amount: str, ref: str | None = None) -> UUID:
    """Append a top-up and return the entry's id — what `open_lot` needs to link to."""
    ref = ref or f"pay-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal(amount),
            reason="topup",
            ref=ref,
            # A top-up that only PARTLY repays an overdraft is money that really arrived,
            # and `record_entry` refuses a positive delta that leaves the balance negative
            # unless told otherwise. Phase B2's §4.B.5 books the repayment before opening
            # a lot; the fixtures here have to be able to reach that state.
            allow_negative=True,
        )
        entry_id = (
            await session.execute(
                text(
                    "SELECT id FROM credit_ledger WHERE tenant_id = :t AND ref = :r "
                    "AND reason = 'topup'"
                ),
                {"t": tenant_id, "r": ref},
            )
        ).scalar_one()
    return UUID(str(entry_id))


async def add_lot(
    tenant_id: UUID,
    *,
    credits_inr: str,
    rates: tuple[Decimal, Decimal] = GROWTH,
    source: lots.LotSource = "topup",
    pack_id: str | None = "growth",
    override_of_pack_id: str | None = None,
) -> UUID:
    """Money in, and the lot it opens — the pair every credit-adding writer will do in one
    transaction once Phase B2 wires them."""
    entry_id = await credit_entry(tenant_id, amount=credits_inr)
    async with tenant_session(tenant_id) as session:
        return await lots.open_lot(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal(credits_inr),
            sarvam_inr_per_min=rates[0],
            cartesia_inr_per_min=rates[1],
            source=source,
            pack_id=pack_id,
            ledger_entry_id=entry_id,
            override_of_pack_id=override_of_pack_id,
        )


async def lot_rows(tenant_id: UUID) -> list[dict[str, Any]]:
    """Every lot of a tenant, open or closed, oldest first — the assertion surface."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, source, pack_id, override_of_pack_id, credits_total, "
                    "credits_remaining, sarvam_inr_per_min, cartesia_inr_per_min, "
                    "closed_at FROM credit_lots WHERE tenant_id = :t "
                    "ORDER BY opened_at, id"
                ),
                {"t": tenant_id},
            )
        ).mappings()
        return [dict(row) for row in rows]
