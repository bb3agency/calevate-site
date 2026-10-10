"""One-time charges on the invoice: the record of setup fees already billed (D-63).

D-707 (10 Oct 2026) ended setup fees: nothing issues one any more, and the nightly job
that did (`apps/workers/billing.py`) now raises the monthly platform fee instead. The
setup-fee rows already in `one_time_charges` stay — the ledger is append-only (hard
rule 4) and an invoice for an onboarding month must still print what was billed then —
so this module keeps their coordinates and the invoice's read of them.

`one_time_charge_lines` is a pure read; the unique index over `(tenant_id, kind, ref)` is
what made each historical charge happen once, and a reversal is a new row under a
different `ref` with a negative amount, never an edit.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .number_rental import INVOICED_RENTAL_KIND
from .service import to_paise

# The setup fee's coordinates in the ledger. `ref` is constant because there is one
# onboarding per organization — that constant IS the once-per-tenant guarantee.
SETUP_FEE_KIND = "setup_fee"
SETUP_FEE_REF = "onboarding"
SETUP_FEE_DESCRIPTION = "One-time onboarding & setup"


async def one_time_charge_lines(
    session: AsyncSession, *, tenant_id: UUID, month: str
) -> list[dict[str, Any]]:
    """The invoice lines for this tenant-month's one-time charges. A pure read.

    Runs under a tenant-scoped session: `one_time_charges` is RLS'd.
    """
    rows = (
        await session.execute(
            # `tenant_id` in the predicate as well as in RLS, for the reason
            # `usage_summary` names it: the answer should depend on the argument, not on
            # which session it was handed. Ordered so a reversal always prints under the
            # charge it reverses. An invoiced number rental is printed by
            # `number_rental.rental_statement_lines`, grouped by price as a prepaid
            # client's is, so it is left out here rather than printed twice.
            text(
                "SELECT description, amount FROM one_time_charges "
                "WHERE tenant_id = :tid AND billing_month = :month AND kind <> :rental "
                "ORDER BY occurred_at, id"
            ),
            {"tid": tenant_id, "month": month, "rental": INVOICED_RENTAL_KIND},
        )
    ).all()

    return [
        {
            "description": description,
            # `Decimal("1")` like the plan-fee line: every quantity on this document is
            # serialized the same way as the money beside it.
            "qty": Decimal("1"),
            "unit_inr": to_paise(Decimal(str(amount))),
            "amount_inr": to_paise(Decimal(str(amount))),
        }
        for description, amount in rows
    ]


__all__ = [
    "SETUP_FEE_DESCRIPTION",
    "SETUP_FEE_KIND",
    "SETUP_FEE_REF",
    "one_time_charge_lines",
]
