"""One-time charges: the onboarding setup fee, issued on a schedule and printed by
the invoice (D-63).

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
* a REPEATED ISSUING — the nightly tick, every night, for the life of the platform —
  conflicts and writes nothing, and every render reads back the one row that is there,
  so the statement prints the same line with the same amount forever;
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

WHO RECORDS IT, AND WHY THAT IS NO LONGER THE INVOICE
-----------------------------------------------------
The first cut of this module recorded the charge from `one_time_charge_lines`, i.e. on
the RENDER of the statement carrying it, and said so in capitals: `GET /v1/admin/
tenants/{id}/invoice` was the only caller, so **a tenant whose first invoice nobody
opened was never charged their setup fee**, and a GET carried a write. Both halves are
closed here, and the two named candidates were weighed rather than combined by default:

* **A scheduled job** (`apps/workers/billing.py::issue_one_time_charges`, daily) —
  TAKEN. It is the only one of the two that removes the human from the loop, which was
  the whole defect: nothing else in this product would ever have noticed the fee was
  unbilled. Daily rather than monthly, deliberately: the fee is owed the moment an
  operator puts a plan quoting one on the tenant, not at a month boundary, and a
  monthly run would leave up to 31 days in which the tenant's own in-progress statement
  showed no setup line and then grew one. Which month the charge LANDS on is not the
  job's schedule and never was — it is the tenant's own IST onboarding month, so the
  answer does not depend on the night the job happened to run (see `issue_setup_fee`).
* **An explicit `POST .../issue`** — REJECTED, having been built in the head and thrown
  away. It separates issuing from reading, which is worth doing, but this change gets
  that separation for free by moving the write OUT of the read (`one_time_charge_lines`
  is now a pure read and `issue_setup_fee` is the writer). What the endpoint would add
  beyond that is a button, and a button is a human opening a screen — the same defect
  one layer down — plus admin API surface with no caller in `apps/web`, which this
  repo counts as a defect that looks like progress. If an operator ever needs to issue
  ahead of the nightly tick, the honest shape is an ops action that calls this same
  function, added when somebody actually needs it.

What that costs, named rather than left to be discovered: a tenant onboarded at 09:00
is not charged until the next tick, so an invoice rendered in between shows no setup
line. It is bounded by one day, it can only ever be the CURRENT month's statement
(which changes on every call anyway, being derived), and the alternative — the render
writing it — is what put a side effect behind a GET.

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
from apps.api.db.result import rowcount_of

from .plans import ist_billing_month, month_pricing_instant, plan_in_effect_sql
from .service import to_paise

log = get_logger(__name__)

# The setup fee's coordinates in the ledger. `ref` is constant because there is one
# onboarding per organization — that constant IS the once-per-tenant guarantee.
SETUP_FEE_KIND = "setup_fee"
SETUP_FEE_REF = "onboarding"
SETUP_FEE_DESCRIPTION = "One-time onboarding & setup"


async def issue_setup_fee(
    session: AsyncSession, *, tenant_id: UUID, onboarded_at: datetime
) -> bool:
    """Record this tenant's onboarding setup fee. THE one writer, and idempotent.

    Returns whether this call is the one that appended the row — for the caller's log
    and job result, never as a guard: the guard is the unique index and it is inside
    the INSERT (see the module docstring). Two callers racing both return honestly, one
    True and one False, and exactly one row exists either way.

    The month and the pricing instant are DERIVED HERE from the tenant's own
    `organizations.created_at` rather than taken from the caller, so a nightly job and a
    hand-run reconciliation cannot disagree about which statement the fee belongs to.
    `ist_billing_month` does the +05:30 shift that decides it: a tenant created at
    23:00 UTC on 31 July was onboarded on 1 August in the only timezone this business
    bills in, and their fee belongs to August.
    """
    month = ist_billing_month(onboarded_at)
    # The same instant `usage_summary` prices that month at — the month's last instant
    # once it is closed, `now` while it is open — so the fee is quoted by the plan that
    # priced the month rather than by whichever plan is current on the night the job runs.
    priced_at = month_pricing_instant(month)
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
        return False
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
        return False
    if fee == 0:
        return False

    result = await session.execute(
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
    # `rowcount` REPORTS the outcome of the write, it does not decide anything: 0 means
    # the row was already there (this caller lost a race, or ran a second time), which
    # is a success, not a failure. Nothing branches on it except the log and the job's
    # own counters.
    recorded = rowcount_of(result) > 0
    if not recorded:
        return False
    # Ids and a month, never the amount: a tenant's commercial terms are not ours to
    # scatter through log aggregation (the discipline `warn_no_plan_in_effect` states).
    log.info(
        "setup_fee_billed",
        extra={"tenant_id": str(tenant_id), "billing_month": month},
    )
    return True


async def one_time_charge_lines(
    session: AsyncSession, *, tenant_id: UUID, month: str
) -> list[dict[str, Any]]:
    """The invoice lines for this tenant-month's one-time charges. **A PURE READ.**

    It used to bill the setup fee as a side effect of being called, which made
    `GET /v1/admin/tenants/{id}/invoice` a GET that writes and made the charge depend on
    somebody opening a screen. `issue_setup_fee` is the writer now and
    `apps/workers/billing.py` is what calls it on a schedule; the module docstring
    records why that split, and not a `POST .../issue`, is the shape.

    Nothing about the statement changed: the ledger row was always the source of truth
    here, so this reads exactly what it read before and prints the same lines. What is
    gone is the case where the reading is what created them.

    Runs under a tenant-scoped session: `one_time_charges` is RLS'd.
    """
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
    "issue_setup_fee",
    "one_time_charge_lines",
]
