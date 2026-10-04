"""The RECURRING cost of a phone number — the one this product had no home for (D-537).

**WHY THIS EXISTS AT ALL.** Every cost this platform records is per-CALL: a call happens,
`pipeline._meter` writes `usage_events` rows keyed on `call_id`, and a month with no calls
costs nothing. A phone number is not that shape. It is charged monthly whether anybody
rings it or not, it is charged for a client who has stopped using the product, and it is
charged by a vendor whose invoice nobody in this system reads. An unbilled monthly cost
per client is a margin leak that compounds silently — it has no incident, no alarm and no
bound — and it was the founder's own question about this decision.

**THE HOME ALREADY EXISTED AND WAS EMPTY.** `usage_events.unit_type` has carried
`number_rental` since the ledger shipped, in `CLIENT_BILLED_UNIT_TYPES`, with NO WRITER —
correctly, while Model B meant a client rented their number from their own operator and
Calevate never paid for it. `billing/attribution.UnattributedCost` was built for exactly
this row ("`number_rental` is the whole of it and NOTHING WRITES ONE") and so was the
second partial unique index, `ux_usage_events_tenant_unit_ref` on
`(tenant_id, unit_type, ref)` where `ref IS NOT NULL AND call_id IS NULL`. So this module
adds no table, no column and no index: it is the writer three earlier pieces of work
already made room for, which is why a callless cost lands in every total that claims to be
a partition and breaks none of them.

MONEY (hard rule 7)
-------------------
* **NUMERIC INR, never float.** The vendor quotes dollars; `phone_numbers
  .monthly_rental_usd` holds the dollars as `NUMERIC(12,4)`, and the rupee is computed
  here, once, and stored in `unit_cost_paid`.
* **THE RATE IS THE MONTH'S, NOT THE PURCHASE'S.** Bolna debits its wallet in dollars on
  the renewal date, so our rupee cost genuinely differs month to month. Freezing the
  purchase-day rate onto the row would produce a ledger that disagrees with the bank by a
  little, for ever, in a direction nobody could reconstruct. `core/fx.usd_inr_rate_now` is
  the one door, and which rate was used is stamped into `meta` because an append-only row
  cannot be corrected in place (hard rule 4) and the only way it is ever explained later is
  that it says so itself.
* **`qty` IS ONE MONTH.** Not thirty days and not a proration: the vendor charges a whole
  month on the renewal date and stops charging when the number is deleted. A fractional
  first month would be a number we invented; `released_at` is what makes the last month
  stop, and the month a number is released in is charged in full because the vendor
  charged it in full.
* **THIS IS OUR COST, NOT A PRICE.** `unit_cost_paid` is what Calevate paid. What the
  CLIENT pays is a different fact with a different home: the attested rupee price frozen
  on `phone_numbers.client_inr_per_month` at purchase, debited from the wallet by
  `charge_number_rental` below (D-665). The two never meet in one figure.

THE CLIENT'S CHARGE (D-665)
---------------------------
A prepaid client is debited the frozen monthly price on the day they buy the number and
again on each monthly renewal date, from the wallet's lots at face value, through the
same `record_usage_from_lots` door a call and a dashboard-AI block use. The row is a
`usage` entry carrying `meta.kind = RENTAL_CHARGE_META_KIND`, which is how the wallet
screen, the daily spend series, the ledger and the statement tell it from a call.

* **The period is the number's own month**, anchored on the IST date the number was
  recorded (`phone_numbers.created_at`): bought on the 31st, it renews on the last day of
  a shorter month and on the 31st again after it. Each period starts in a different
  calendar month, so the key is `rental_ref(number_id, <YYYY-MM the period starts in>)` —
  the same spelling as our cost's key, in a different ledger.
* **Idempotent on that key** under the per-tenant credit lock (`record_usage_from_lots`
  looks for the row before it consumes a lot) and in the database
  (`ux_credit_ledger_tenant_reason_ref`), so a retried tick or a replayed purchase never
  charges a period twice.
* **A renewal the wallet cannot cover still lands** (`allow_negative=True`), as call
  minutes do: the number is live and renewing at the carrier, so the charge is owed, and
  the overdraft is what the signed balance shows as "You owe" until the next top-up.
WHO PAYS WHICH PERIOD (founder, 3 Oct 2026) — `collect_number_rental` is the one place
it is decided, for the purchase and the daily renewal alike:

* **Prepaid accounts** are debited from the wallet, as above.
* **Invoiced (managed) accounts** have no wallet: the period becomes a "Phone number
  rental" line on their invoice at the same frozen price, written to `one_time_charges`
  (kind `number_rental`, the same `rental_ref` key), so it is idempotent per (number,
  period) exactly as the debit is. It is not part of the retainer.
* **A closed account** (`organizations.closed_at` set, erased or not) is charged nothing.
* **A period that begins inside the account's trial** is charged nothing, on either
  route. Charging resumes at the first renewal date after the trial, never backwards.
* **A number recorded before D-665 shipped** starts at `phone_numbers.rental_charged_from`,
  the first renewal date after the deploy, stamped by the migration that shipped it.

⚠ **THE PRICE IS THE VENDOR'S QUOTE AT PURCHASE, AND A VENDOR PRICE RISE IS NOT SEEN BY
THIS MODULE.** `monthly_rental_usd` is whatever the search result the operator accepted
said (`bolna-findings/mirror/pages/api-reference/phone-numbers/search.md:126-133`). Their
listing endpoint reports a current `price` per number (`get_all.md:103-106`) and
`workers/number_rental.py::reconcile_engine_numbers` compares the two and alarms —
this module deliberately does not fetch, because a meter that makes a vendor call cannot
run inside the caller's transaction and a rate limit must never be able to skip a charge.

IDEMPOTENT IN THE DATABASE, NOT IN AN `IF`
-------------------------------------------
`ref` is `number_rental:<number_id>:<YYYY-MM>` and the insert is `ON CONFLICT … DO
NOTHING` against the index predicate spelled verbatim. The failure this survives is the
same tick arriving twice — a retried job, two workers, a month boundary crossed
mid-run — and a check-then-write would let both copies read "not metered yet". The
namespace is OURS and is validated rather than trusted, for `ai_quota.ASSIST_REF_PREFIX`'s
reason: idempotency is a switch that turns metering OFF, so a key any caller could supply
is a way to make a cost disappear.

NO PII (hard rule 6). The `meta` carries the number's ROW id, never the E.164 — a phone
number is exactly what rule 6 names, and a ledger is the last place to put one.
"""

from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import INDEX_PREDICATE
from apps.api.billing.lots import AiAssistDemand
from apps.api.billing.plans import (
    IST,
    billing_month_of_ist_date,
    ist_month_window,
    parse_billing_month,
)
from apps.api.billing.rates import MONEY_Q, PREPAID_TIERS, ROUNDING
from apps.api.billing.service import plan_tier_of, record_usage_from_lots, to_paise
from apps.api.billing.trials import trial_covers
from apps.api.core.fx import usd_inr_rate_now
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.tenancy.closure import read_closure

log = get_logger(__name__)

#: The `usage_events.unit_type` this module writes, and the only one it may.
RENTAL_UNIT_TYPE: Final = "number_rental"

#: The `usage_events.ref` namespace this module owns: `number_rental:<uuid>:<YYYY-MM>`.
#: Validated rather than trusted (module docstring) — and the SHAPE is what makes the
#: idempotency meaningful: one row per number per IST billing month, decided by the
#: database's unique index and not by anybody's read.
RENTAL_REF_PREFIX: Final = "number_rental:"
_REF_RE: Final = re.compile(r"^number_rental:[0-9a-f-]{36}:\d{4}-\d{2}$")


def rental_ref(number_id: UUID, month: str) -> str:
    """THE key. One number, one IST billing month, one charge.

    `parse_billing_month` is called for its refusal, not its value: a caller that passed
    `"2026-13"` would otherwise mint a key no month will ever collide with and charge the
    same rental twice.
    """
    parse_billing_month(month)
    return f"{RENTAL_REF_PREFIX}{number_id}:{month}"


@dataclass(frozen=True, slots=True)
class RentalMetered:
    """What one month's rental cost us, and whether this call is what recorded it.

    `recorded` is False for a replay — the row was already there — and the caller must not
    treat that as an error or as a second charge. It is returned rather than swallowed
    because a job that reports "metered 40 numbers" when 39 were replays is a job whose
    output means nothing.
    """

    ref: str
    cost_inr: Decimal
    recorded: bool


_INSERT_RENTAL = f"""
INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid,
                          ref, occurred_at, meta, created_at)
VALUES (:id, :tid, NULL, :unit, 1, :cost, :ref, now(), CAST(:meta AS jsonb), now())
ON CONFLICT (tenant_id, unit_type, ref) WHERE {INDEX_PREDICATE}
DO NOTHING
RETURNING id
"""


def rental_inr(monthly_rental_usd: Decimal) -> tuple[Decimal, str, str | None]:
    """One month's rental in rupees, plus the rate's provenance.

    Quantized at `MONEY_Q` with `ROUNDING` — the storage quantum and mode this repository
    has exactly one spelling of — because `unit_cost_paid` is NUMERIC(12,4) and a value
    that does not fit it is rounded by the database silently, at whatever mode the server
    happens to use.
    """
    resolved = usd_inr_rate_now(get_settings().usd_inr_rate)
    cost = (monthly_rental_usd * resolved.rate).quantize(MONEY_Q, rounding=ROUNDING)
    return cost, resolved.source, resolved.as_of.isoformat() if resolved.as_of else None


async def record_number_rental(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    number_id: UUID,
    month: str,
    monthly_rental_usd: Decimal,
    provider: str | None,
) -> RentalMetered:
    """Meter ONE number's rental for ONE IST billing month. The only writer of the unit.

    Commits in the CALLER's transaction, like every other meter in this system: a rental
    recorded whose surrounding work rolled back is a charge against a number nobody
    bought.

    A ZERO OR NEGATIVE RENTAL IS REFUSED RATHER THAN RECORDED. A zero is not a free number
    — it is a price we failed to read (the vendor's `price` was missing, or was quoted in a
    currency this product refuses), and writing it would put a permanent ₹0 into an
    append-only ledger that no later correction can replace. The caller alarms instead.
    """
    if monthly_rental_usd <= 0:
        raise ValueError(
            f"a rental of {monthly_rental_usd} USD is not a price; refusing to meter a "
            "number whose cost could not be read"
        )
    ref = rental_ref(number_id, month)
    # AN `assert`, NOT AN `if`/`raise`, AND THE DIFFERENCE IS THE POINT. `rental_ref` is
    # the only mint: it takes a `UUID` and a month `parse_billing_month` has already
    # refused unless it is `YYYY-MM`, so a ref of the wrong shape is not a state this
    # function can be handed. Written as a branch it was an arm no test could ever enter,
    # which is why it carried a coverage suppression — and a suppressed branch on a money
    # path is one nobody will ever see fail. The invariant is worth STATING (the namespace
    # is ours and idempotency is a switch that turns metering off), so it stays as the
    # postcondition it always was, with `rental_ref`'s own shape pinned by a test instead.
    assert _REF_RE.match(ref), "a number rental ref must be minted by `rental_ref`"
    cost, fx_source, fx_as_of = rental_inr(monthly_rental_usd)
    # Hard rule 6: the number's ROW id and the carrier, never the E.164.
    meta = {
        "number_id": str(number_id),
        "provider": provider,
        "month": month,
        "source_usd": str(monthly_rental_usd),
        "fx_source": fx_source,
        "fx_as_of": fx_as_of,
    }
    row = (
        await session.execute(
            text(_INSERT_RENTAL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "unit": RENTAL_UNIT_TYPE,
                "cost": cost,
                "ref": ref,
                "meta": json.dumps(meta),
            },
        )
    ).first()
    recorded = row is not None
    log.info(
        "number_rental_metered",
        extra={"number_id": str(number_id), "month": month, "recorded": recorded},
    )
    return RentalMetered(ref=ref, cost_inr=cost, recorded=recorded)


# --- the client's charge (D-665) ------------------------------------------------------

#: The `credit_ledger.meta.kind` of a rental debit. `reason` stays `usage` (the enum is
#: constrained by `ck_credit_ledger_reason_enum`), so this is what separates the rental
#: from a call on every reader of the wallet.
RENTAL_CHARGE_META_KIND: Final = "number_rental"

#: The client's word for the line, on the ledger, the spend breakdown and the statement.
#: Our cost, the carrier and the number itself never appear beside it.
RENTAL_CHARGE_LABEL: Final = "Phone number rental"


def _add_months(anchor: date, months: int) -> date:
    """`anchor` moved `months` calendar months on, the day clamped to the month's last.

    Always computed from the ANCHOR, never chained from the previous renewal: chaining
    would walk a number bought on the 31st down to the 28th for ever after February.
    """
    index = anchor.month - 1 + months
    year, month = anchor.year + index // 12, index % 12 + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def rental_period_start(anchor: date, on: date) -> date:
    """The first day of the rental period `on` falls in, for a number anchored on `anchor`.

    Both are IST dates. A day before the anchor belongs to no period and is refused
    rather than answered with the anchor, which would charge a period that has not begun.
    """
    if on < anchor:
        raise ValueError("a rental period cannot start before the number was bought")
    months = (on.year - anchor.year) * 12 + (on.month - anchor.month)
    start = _add_months(anchor, months)
    return start if start <= on else _add_months(anchor, months - 1)


def ist_date(moment: datetime) -> date:
    """The IST calendar date of an instant — the only zone renewals are dated in."""
    return moment.astimezone(IST).date()


def today_ist() -> date:
    return ist_date(datetime.now(UTC))


async def is_prepaid(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Does this account HAVE a wallet to debit? `PREPAID_TIERS` names the motion once."""
    return await plan_tier_of(session, tenant_id) in PREPAID_TIERS


@dataclass(frozen=True, slots=True)
class RentalCharge:
    """One period's rental as the wallet answered it.

    `charged` is False on a replay: the period was already debited and nothing moved.
    """

    ref: str
    period_start: date
    amount_inr: Decimal
    charged: bool


async def charge_number_rental(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    number_id: UUID,
    anchor: date,
    period_start: date,
    inr_per_month: Decimal,
) -> RentalCharge:
    """Debit ONE period of ONE number's rental from the wallet. The only writer of it.

    In the CALLER's transaction: at purchase that is the transaction that records the
    number, so a number cannot exist with its first month unpaid, nor a first month be
    debited for a number whose row rolled back.

    `allow_negative=True` on both paths. At renewal because the number is still renewing
    at the carrier, exactly the argument `charge_for_call` makes. At purchase because the
    carrier has already been paid when this runs: refusing here would roll back the row
    of a number we hold and pay for, and `_assert_can_afford` has already refused the
    purchase the wallet could not cover before any money moved.

    A zero or negative price is refused rather than written (`record_number_rental`'s
    reason): it is a price nobody attested, not a free number.
    """
    if inr_per_month <= 0:
        raise ValueError("a rental price must be positive; refusing to charge a number for it")
    if period_start != rental_period_start(anchor, period_start):
        raise ValueError("period_start must be a renewal date of this number")
    ref = rental_ref(number_id, billing_month_of_ist_date(period_start))
    amount = to_paise(inr_per_month)
    meta: dict[str, Any] = {
        "kind": RENTAL_CHARGE_META_KIND,
        # The row id, never the E.164 (hard rule 6).
        "number_id": str(number_id),
        "period_start": period_start.isoformat(),
        "inr_per_month": str(amount),
    }
    debit = await record_usage_from_lots(
        session,
        tenant_id=tenant_id,
        ref=ref,
        demand=AiAssistDemand(credits=amount),
        meta=meta,
        allow_negative=True,
    )
    log.info(
        "number_rental_charged",
        extra={
            "tenant_id": str(tenant_id),
            "number_id": str(number_id),
            "period_start": period_start.isoformat(),
            "charged": debit.charged,
        },
    )
    return RentalCharge(
        ref=ref, period_start=period_start, amount_inr=amount, charged=debit.charged
    )


#: The `one_time_charges.kind` of an invoiced (managed) account's rental period.
INVOICED_RENTAL_KIND: Final = "number_rental"

_INSERT_INVOICED_RENTAL: Final = """
INSERT INTO one_time_charges (id, tenant_id, kind, ref, description, amount,
                              billing_month, plan_id, occurred_at, created_at)
VALUES (:id, :tid, :kind, :ref, :description, :amount, :month, NULL, now(), now())
ON CONFLICT (tenant_id, kind, ref) DO NOTHING
RETURNING id
"""


async def invoice_number_rental(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    number_id: UUID,
    period_start: date,
    inr_per_month: Decimal,
) -> bool:
    """Put ONE period of ONE number on an invoiced account's statement. True if written.

    The statement month is the month the period starts in, the month already in the key,
    so a tick that runs late across a month boundary still bills the period on the
    statement it belongs to. Idempotent on `ux_one_time_charges_tenant_kind_ref`.
    """
    if inr_per_month <= 0:
        raise ValueError("a rental price must be positive; refusing to invoice a number for it")
    month = billing_month_of_ist_date(period_start)
    row = (
        await session.execute(
            text(_INSERT_INVOICED_RENTAL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "kind": INVOICED_RENTAL_KIND,
                "ref": rental_ref(number_id, month),
                "description": RENTAL_CHARGE_LABEL,
                "amount": to_paise(inr_per_month),
                "month": month,
            },
        )
    ).first()
    return row is not None


#: What happened to one period: `charged` (wallet) and `invoiced` moved money, `replayed`
#: found it already done, and the other three are the founder's reasons for charging
#: nothing (module docstring).
RentalOutcome = Literal["charged", "invoiced", "replayed", "closed", "trial", "before_first_period"]


async def collect_number_rental(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    number_id: UUID,
    recorded_at: datetime,
    charged_from: date | None,
    period_start: date,
    inr_per_month: Decimal,
) -> RentalOutcome:
    """Collect ONE period of ONE number's rental, by whichever route the account pays.

    THE one decision, for the purchase and the renewal alike, in the caller's transaction.
    `recorded_at` is `phone_numbers.created_at` and `charged_from` its
    `rental_charged_from`.

    The trial is asked about the instant the period BEGAN, not about today: a period that
    opened inside the trial stays free after the trial ends, which is what makes "charging
    starts from the next renewal date" true without a back-charge. The first period begins
    when the number was recorded rather than at midnight, so a number bought an hour into a
    trial is not charged for having been bought on the day the trial started.
    """
    anchor = ist_date(recorded_at)
    if period_start != rental_period_start(anchor, period_start):
        raise ValueError("period_start must be a renewal date of this number")
    if charged_from is not None and period_start < charged_from:
        return "before_first_period"
    if (await read_closure(session, tenant_id=tenant_id)).is_closed:
        return "closed"
    began = (
        recorded_at
        if period_start == anchor
        else datetime.combine(period_start, time.min, tzinfo=IST)
    )
    if await trial_covers(session, tenant_id=tenant_id, at=began):
        return "trial"
    if await is_prepaid(session, tenant_id=tenant_id):
        charge = await charge_number_rental(
            session,
            tenant_id=tenant_id,
            number_id=number_id,
            anchor=anchor,
            period_start=period_start,
            inr_per_month=inr_per_month,
        )
        return "charged" if charge.charged else "replayed"
    written = await invoice_number_rental(
        session,
        tenant_id=tenant_id,
        number_id=number_id,
        period_start=period_start,
        inr_per_month=inr_per_month,
    )
    return "invoiced" if written else "replayed"


#: The month's rental periods, grouped by price so every statement line multiplies out.
#: A prepaid period is dated by its DEBIT (`occurred_at`), an invoiced one by the
#: `billing_month` it was written for; an account is on one route or the other, and the
#: two halves are summed rather than kept apart so the line reads the same either way.
_RENTAL_LINES_SQL: Final = """
SELECT amount, COUNT(*) AS periods FROM (
    SELECT -delta AS amount
      FROM credit_ledger
     WHERE tenant_id = :tid AND reason = 'usage' AND (meta->>'kind') = :kind
       AND occurred_at >= :start AND occurred_at < :end
    UNION ALL
    SELECT amount
      FROM one_time_charges
     WHERE tenant_id = :tid AND kind = :invoiced_kind AND billing_month = :month
) AS rentals
 GROUP BY amount
 ORDER BY 1
"""


async def rental_statement_lines(
    session: AsyncSession, *, tenant_id: UUID, month: str
) -> list[dict[str, Any]]:
    """The statement lines for this tenant-month's rental periods. A pure read.

    One line per distinct monthly price rather than one per number: `qty` is the number
    of rental periods charged and `unit_inr` the price, so `qty * unit_inr` is the line's
    amount exactly — the one arithmetic a client checks by hand. No periods, no line.
    `charges.one_time_charge_lines` leaves the invoiced periods to this function.
    """
    start, end = ist_month_window(month)
    rows = (
        await session.execute(
            text(_RENTAL_LINES_SQL),
            {
                "tid": tenant_id,
                "kind": RENTAL_CHARGE_META_KIND,
                "invoiced_kind": INVOICED_RENTAL_KIND,
                "start": start,
                "end": end,
                "month": month,
            },
        )
    ).all()
    lines: list[dict[str, Any]] = []
    for amount, periods in rows:
        unit = to_paise(Decimal(str(amount)))
        qty = Decimal(int(periods))
        lines.append(
            {
                "description": RENTAL_CHARGE_LABEL,
                "qty": qty,
                "unit_inr": unit,
                "amount_inr": to_paise(unit * qty),
            }
        )
    return lines


async def rental_revenue_inr(session: AsyncSession, *, tenant_id: UUID, month: str) -> Decimal:
    """What this tenant-month's rental periods were charged: the statement lines' sum, so
    the margin board books exactly what the statement bills. Our cost of the same periods
    is the `number_rental` usage row, already in every cost total."""
    lines = await rental_statement_lines(session, tenant_id=tenant_id, month=month)
    return sum((line["amount_inr"] for line in lines), Decimal("0.00"))


__all__ = [
    "INVOICED_RENTAL_KIND",
    "RENTAL_CHARGE_LABEL",
    "RENTAL_CHARGE_META_KIND",
    "RENTAL_REF_PREFIX",
    "RENTAL_UNIT_TYPE",
    "RentalCharge",
    "RentalMetered",
    "RentalOutcome",
    "charge_number_rental",
    "collect_number_rental",
    "invoice_number_rental",
    "is_prepaid",
    "ist_date",
    "record_number_rental",
    "rental_inr",
    "rental_period_start",
    "rental_ref",
    "rental_revenue_inr",
    "rental_statement_lines",
    "today_ist",
]
