"""One-time charges: the onboarding setup fee, billed through the invoice (D-63).

`plans.setup_fee` existed as a column for as long as this repo has had a schema and was
read by nothing — the fee was quoted in a message and collected out of band, which is
the state `scripts/check_wiring.py` recorded. This module is what closes it.

WHAT MAKES IT ONCE, AND WHY THAT ARGUMENT SURVIVES A RACE
---------------------------------------------------------
An invoice here is a DERIVED statement (`billing/invoice.py`) — it is recomputed from
the ledgers every time anyone looks at it — so "charged on the first invoice" cannot
mean "charged the first time this function runs". It has to mean a durable fact that
regeneration re-reads rather than re-creates. That fact is one row in
`one_time_charges`, and the whole of the once-ness is the unique index over
`(tenant_id, kind, ref)`:

* the write is an unconditional `INSERT … ON CONFLICT DO NOTHING`. There is no
  `SELECT … WHERE NOT EXISTS` in front of it, because a read-then-write is exactly the
  hole two concurrent invoice generations fall through (BACKEND-PATTERNS §5: put the
  guard in the write). The second writer blocks on the index entry until the first
  commits, then inserts nothing;
* a REGENERATED invoice re-runs the same insert, conflicts, and reads back the row that
  is already there — so it prints the same line with the same amount, forever;
* a PLAN CHANGE cannot re-charge: the key is `(tenant_id, kind, ref)` and carries no
  plan id, so a second plan quoting its own `setup_fee` conflicts with the first
  charge. Re-onboarding the same organization is the same argument;
* a REVERSAL is still possible without touching hard rule 4: a new row under a different
  `ref` with a negative `amount` renders as a credit line on the same statement.

An advisory lock (the `credit_ledger` pattern) would have worked too and is deliberately
NOT used: that ledger has to READ its predecessor to compute `balance_after`, so its
critical section spans a read and a write and only a lock can cover it. Here there is
nothing to read — the row is either there or it is not — and a unique index is the
cheaper, stricter guarantee that also binds a future writer who forgets the lock.

WHICH MONTH IT LANDS ON
-----------------------
The tenant's ONBOARDING month: the IST month of `organizations.created_at`. Not "the
first invoice anybody happens to render", which would make July's statement depend on
whether August's was opened first — a statement that changes depending on what else you
looked at is the defect `billing/plans.py` exists to prevent, one level up. The amount
is the `setup_fee` of the plan in effect at that month's pricing instant, resolved
through the one helper every money reader uses, and then FROZEN in the row: `plans` is
mutable, and a fee re-derived on each render could change after the client has paid.

The cost of that choice, stated plainly: a tenant whose onboarding month is never
rendered is never billed the fee. It is not lost — the row is written the first time
that month IS rendered, whenever that happens — but the fee does not chase the client
into a later month on its own.

Money is NUMERIC INR (hard rule 7) and every rupee amount on the line goes through
`service.to_paise`, the same one function as the rest of the invoice.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

from .plans import ist_billing_month, plan_in_effect_sql
from .service import to_paise

log = get_logger(__name__)

# The setup fee's coordinates in the ledger. `ref` is constant because there is one
# onboarding per organization — that constant IS the once-per-tenant guarantee.
SETUP_FEE_KIND = "setup_fee"
SETUP_FEE_REF = "onboarding"
SETUP_FEE_DESCRIPTION = "One-time onboarding & setup"


async def _record_setup_fee(
    session: AsyncSession, *, tenant_id: UUID, month: str, priced_at: datetime
) -> None:
    """Append the setup charge for this tenant, if their plan quotes one and it has not
    been billed. Idempotent by the unique index, never by a preceding read."""
    plan = (
        await session.execute(
            # The SAME resolution the invoice's other numbers come from, at the SAME
            # instant, so the fee is quoted by the plan that priced the month rather
            # than by whichever row a second `ORDER BY` happened to surface.
            text(plan_in_effect_sql("id, setup_fee")),
            {"tid": tenant_id, "at": priced_at},
        )
    ).first()
    if plan is None or plan[1] is None:
        return
    fee = Decimal(str(plan[1]))
    # Zero is not a charge and neither is a negative one. A ₹0.00 line invites a dispute
    # about nothing (the rule the overage line already follows), and a negative
    # `setup_fee` is a discount nobody designed — it would print as a credit the client
    # never agreed to, so it is refused here with a line an operator can act on.
    if fee < 0:
        log.warning(
            "setup_fee_negative_not_billed",
            extra={"tenant_id": str(tenant_id), "plan_id": str(plan[0])},
        )
        return
    if fee == 0:
        return

    await session.execute(
        text(
            "INSERT INTO one_time_charges (id, tenant_id, kind, ref, description, amount, "
            "billing_month, plan_id, occurred_at, created_at) VALUES (:id, :tid, :kind, :ref, "
            ":description, :amount, :month, :plan_id, now(), now()) "
            "ON CONFLICT (tenant_id, kind, ref) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "kind": SETUP_FEE_KIND,
            "ref": SETUP_FEE_REF,
            "description": SETUP_FEE_DESCRIPTION,
            "amount": fee,
            "month": month,
            "plan_id": plan[0],
        },
    )
    # Ids and a month, never the amount: a tenant's commercial terms are not ours to
    # scatter through log aggregation (the discipline `warn_no_plan_in_effect` states).
    log.info(
        "setup_fee_billed",
        extra={"tenant_id": str(tenant_id), "billing_month": month},
    )


async def one_time_charge_lines(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    month: str,
    onboarded_at: datetime,
    priced_at: datetime,
) -> list[dict[str, Any]]:
    """The invoice lines for this tenant-month's one-time charges.

    Billing the setup fee happens HERE, on the invoice that carries it, because the
    statement is the artifact the client is billed by — there is no `invoices` table for
    a signup-time side effect to hang off, and a fee recorded at signup and rendered
    from somewhere else would be two sources for one number. The write is idempotent,
    monotone (a row is only ever added, never changed) and confined to the tenant's own
    onboarding month, so rendering an invoice can record what was already owed and can
    never change it.

    **WHAT THAT COSTS, NAMED RATHER THAN LEFT TO BE DISCOVERED: the charge is recorded
    when the statement carrying it is RENDERED, and nothing in this product renders
    statements on a schedule.** `GET /v1/admin/tenants/{id}/invoice` is the only caller,
    so a tenant whose first invoice nobody opens is never charged their setup fee. That
    is an improvement on the state before this (the fee was collected out of band, i.e.
    by somebody remembering), and it is still a billing step that depends on a human
    opening a screen. It is also why this is a GET with a side effect, which is worth a
    reviewer's attention even though the write is admin-only (`billing:read`,
    `realm="admin"`, so D-22 impersonation cannot reach it), idempotent and monotone.
    Two things would close it and neither belongs in this slice: a monthly invoicing job
    (there is no `cron` for billing in `workers/settings.py` — check before assuming one
    appeared), or an explicit `POST .../issue` that separates issuing from reading. D-63
    records the choice; whichever lands, the ledger row stays the source of truth and
    this function keeps working unchanged.

    Runs under a tenant-scoped session: `one_time_charges` and `plans` are both RLS'd.
    """
    if ist_billing_month(onboarded_at) == month:
        await _record_setup_fee(session, tenant_id=tenant_id, month=month, priced_at=priced_at)

    rows = (
        await session.execute(
            # `tenant_id` in the predicate as well as in RLS, for the reason
            # `usage_summary` names it: the answer should depend on the argument, not on
            # which session it was handed. Ordered so a reversal always prints under the
            # charge it reverses.
            text(
                "SELECT description, amount FROM one_time_charges "
                "WHERE tenant_id = :tid AND billing_month = :month "
                "ORDER BY occurred_at, id"
            ),
            {"tid": tenant_id, "month": month},
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
