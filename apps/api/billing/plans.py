"""WHICH `plans` row is in effect, and AT WHICH INSTANT (DATA-MODEL §8).

`plans.effective_from` / `plans.effective_to` are the row's VALID TIME: the period
during which those terms are the terms we agreed with the client. Until this module
existed they were declared, migrated and read by nothing — every reader resolved a
tenant's plan as `ORDER BY created_at DESC LIMIT 1`, the NEWEST ROW. Those two rules
are not the same rule, and the gap between them was a money bug in both directions:

- an operator preparing a price change in advance (`effective_from` next month) changed
  TODAY's bill, the client's usage panel, the worst-case call-cost quote and the
  dispatch ceiling, the moment the row was inserted;
- and because an invoice here is a DERIVED statement rather than a stored row
  (`billing/invoice.py`), re-rendering July's invoice AFTER a plan change re-priced
  July at the new rate. A statement that changes when you look at it twice is not a
  statement.

THE STANDARD SHAPE, AND WHERE WE SIT IN IT
------------------------------------------
This is valid-time (application-time) versioning — SQL:2011 application-time period
tables, the same thing a warehouse calls an SCD Type 2 dimension. Two pieces of that
standard are adopted here verbatim, because they exist for reasons we have too:

* **The period is half-open, `[effective_from, effective_to)`** — SQL:2011's period
  semantics are "closed-open" (cs.ulb.ac.be/public/_media/teaching/infoh415/
  tempfeaturessql2011.pdf §2). A closed-closed window makes the changeover instant
  belong to BOTH rows, so the day a plan is superseded is priced by a coin flip. With
  half-open, an operator can write `old.effective_to = new.effective_from` — the
  obvious gesture — and it is exactly right with no gap and no overlap.
* **Point-in-time query, not "latest"** — `effective_from <= t AND t < effective_to`,
  with the instant `t` passed in rather than assumed to be now. Which instant is the
  caller's decision and it is NOT always now (see `month_pricing_instant`).

One piece we deliberately do NOT adopt: SQL:2011's `PERIOD ... WITHOUT OVERLAPS`
temporal primary key (Postgres 18; on pg16 the equivalent is an `EXCLUDE USING gist
(tenant_id WITH =, tstzrange(effective_from, effective_to) WITH &&)` and `btree_gist`).
It cannot be added to this table as it stands and would not be enough if it could:

- every `plans` row that exists today has `effective_from = effective_to = NULL`, an
  unbounded window, and any two of them overlap. An exclusion constraint would refuse
  the table's own contents;
- `billing/caps.py::apply_client_caps` MINTS a windowless row for a tenant with no plan
  so the client's own cap has somewhere to live, and that row must keep working;
- NULL bounds are not a defect to be migrated away. `effective_from IS NULL` means
  "since forever" and `effective_to IS NULL` means "until further notice", which is
  what an open-ended retainer actually is.

So instead of forbidding overlap, resolution is a **total order** and overlap is
resolved deterministically rather than refused: among the rows whose window contains
the instant, the one with the LATEST `effective_from` wins (NULL sorting as
`-infinity`, which is what "since forever" means), and `created_at DESC, id DESC`
breaks the remaining tie. Two consequences worth stating:

- a dated row beats an undated one once it comes into effect, so the ordinary
  operator gesture — leave the old windowless row alone, INSERT the new terms with an
  `effective_from` — is correct without a second statement;
- with every window NULL the order collapses to `created_at DESC, id DESC`, which is
  the newest-row rule this repo had before. Every existing plan row therefore resolves
  exactly as it did yesterday: this change re-prices nobody on the day it lands.

The `id DESC` tail is the same load-bearing tail as `ix_credit_ledger_tenant_recent`
(DATA-MODEL §8): "newest" has to be a TOTAL order or two readers disagree about which
row it is, and two rows inserted in one transaction share a `created_at`.

WHAT A TENANT WITH NO ROW IN EFFECT MEANS, AND THE COST WE ACCEPT
-----------------------------------------------------------------
It means the same as no `plans` row at all — no fee, no included minutes, no rate, no
ceiling, the default concurrency — which is the doctrine `billing/caps.py` already
argues for at length ("a missing plan row means the default and never a refusal; the
alternative reads a new client's empty billing setup as a ceiling of zero and takes
their phones down on day one").

The cost, stated plainly because it is new: an operator who sets `effective_to` on a
live plan WITHOUT inserting a successor drops that tenant's spend cap and their overage
rate on the stroke of that instant, silently. That is why `warn_no_plan_in_effect`
exists and why both money readers call it — a tenant with plan rows and none in effect
is a misconfiguration, and it gets a log line an operator can act on rather than a
quietly free month. The alternative (fall back to the expired row) was rejected: it
would charge a client at terms whose end date we were explicitly told, which is the one
thing an end date must prevent.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

# India has no DST, so the billing offset is a constant and not a zoneinfo lookup —
# the same +05:30 `billing.service._IST_MONTH` adds in SQL, as a Python tzinfo.
IST = timezone(timedelta(hours=5, minutes=30))

# The SQL literal for "now", for the callers that price the present. Named so a reader
# of `CAPS_CTE` can see WHICH instant is being resolved at, rather than finding a bare
# `now()` inside a CTE and having to guess whether that was a decision.
NOW_SQL = "now()"

_BILLING_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def plan_in_effect_sql(columns: str, *, at: str = ":at") -> str:
    """`SELECT {columns} FROM plans` for the ONE row in effect at `at`.

    `at` is a SQL expression, not a value — `":at"` for a caller that binds an instant
    (pricing a specific month), `NOW_SQL` for a caller that means the present. It is
    interpolated because every call site in this repo passes one of those two module
    constants; a caller that passes a user string is writing an injection, and no
    caller does. The COLUMNS are interpolated for the same reason and by the same
    callers (`caps.py` needs `LEAST(...)` expressions, not column names).

    Half-open on purpose: `effective_from <= at < effective_to`. See the module
    docstring for why, and for why the ordering is a total order rather than an
    overlap constraint.
    """
    return f"""
        SELECT {columns}
        FROM plans
        WHERE tenant_id = :tid
          AND (effective_from IS NULL OR effective_from <= {at})
          AND (effective_to IS NULL OR effective_to > {at})
        ORDER BY COALESCE(effective_from, '-infinity'::timestamptz) DESC,
                 created_at DESC,
                 id DESC
        LIMIT 1
    """


def ist_billing_month(moment: datetime) -> str:
    """Which IST billing month an instant falls in — `"2026-08"`.

    THE Python side of `billing.service._IST_MONTH`, which does the same +05:30 shift in
    SQL. Two spellings of "which month is this" is how a panel and a bill end up
    disagreeing about a 23:00 IST call, so callers that hold an instant in Python (the
    tenant's `organizations.created_at`, `now()`) come here rather than adding their own
    offset — `current_billing_month` is this function applied to now.

    REFUSES a naive datetime instead of assuming one. `astimezone` on a naive instant
    silently reads it in the process's local timezone, which on a UTC container and an
    IST laptop gives two different billing months for the same row. Every timestamp this
    is called with comes from a `timestamptz` column or `datetime.now(UTC)`, so a naive
    one means a caller lost the timezone somewhere upstream and the honest answer is to
    say so rather than to bill a month we guessed.
    """
    if moment.tzinfo is None:
        raise ValueError("a billing month needs an aware instant (timestamptz or UTC-aware)")
    return moment.astimezone(IST).strftime("%Y-%m")


def parse_billing_month(month: str) -> tuple[int, int]:
    """`"2026-07"` -> `(2026, 7)`, or a 422 the caller can act on.

    Strict rather than lenient, and this is a behaviour change worth naming: `month` is
    an unvalidated query parameter on three routes, and before effective dating a
    nonsense value simply matched no `usage_events` and returned a zero month. It can no
    longer be waved through, because it now also selects WHICH PLAN prices the answer —
    and a month we cannot parse is one we cannot honestly price. A 422 saying what the
    format is beats a ₹0.00 invoice for `?month=july`.
    """
    if not _BILLING_MONTH.match(month):
        raise ProblemError(
            kind="validation",
            code="invalid_billing_month",
            title="Invalid billing month",
            detail="A billing month looks like 2026-07 (YYYY-MM, IST).",
            remediation="Use YYYY-MM, or omit the parameter for the current month.",
        )
    year, _, mon = month.partition("-")
    return int(year), int(mon)


def month_pricing_instant(month: str, *, now: datetime | None = None) -> datetime:
    """The instant at which an IST billing month is priced: the moment inside that
    month that is nearest to now.

    Three cases, and each one is a decision:

    - **A CLOSED month prices at its last instant.** July is priced by the plan that
      was in effect on 31 July at 23:59:59.999999 IST, whatever has happened to the
      tenant's plan since. That is what makes a derived invoice re-renderable: the
      answer does not depend on the day you ask, which is the promise
      `billing/invoice.py`'s deterministic invoice number is worthless without.
    - **The CURRENT month prices at NOW** — not at the month's end, which is still in
      the future. Pricing today's panel at 31 August would let a plan dated 25 August
      change the bill on the 12th, which is the exact defect this module exists to
      close, merely moved from months to days.
    - **A month entirely in the FUTURE prices at its first instant**, so a quote for
      December uses the terms that will be in force in December rather than today's.

    NO PRORATION, and it is a real limitation rather than an oversight: a month is
    priced by ONE plan. `included_min` is a monthly allowance, so splitting a month
    across two plans would have to split the allowance too, and there is no answer to
    "how many of the 500 included minutes belong to each half" that a client would
    recognise as theirs. The industry answer is the same one: a plan change takes
    effect at a billing boundary. Consequence to know before dating a row mid-month:
    the whole month prices on the row in effect at the instant above.
    """
    year, mon = parse_billing_month(month)
    start = datetime(year, mon, 1, tzinfo=IST)
    next_month = (
        datetime(year + 1, 1, 1, tzinfo=IST)
        if mon == 12
        else datetime(year, mon + 1, 1, tzinfo=IST)
    )
    # The last instant that is still IN the month, at timestamptz's own resolution —
    # the half-open window's `at < effective_to` must not admit the NEXT month's plan.
    end = next_month - timedelta(microseconds=1)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return min(max(moment, start.astimezone(UTC)), end.astimezone(UTC))


async def warn_no_plan_in_effect(
    session: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> bool:
    """Log when a tenant HAS plan rows and none of them is in effect.

    Returns whether it warned, so a test can pin that the line is emitted rather than
    trusting a log. Costs one indexed count and is only reached on the path where a
    plan lookup already came back empty — a tenant with no plan row at all is a normal
    state (nothing in this codebase creates one) and says nothing.

    Ids and counts only, never a rupee amount or a client name: this is the same log
    discipline as everywhere else (hard rule 6 is about PII, and a tenant's commercial
    terms are not ours to scatter through log aggregation either).
    """
    rows = int(
        (
            await session.execute(
                text("SELECT count(*) FROM plans WHERE tenant_id = :tid"), {"tid": tenant_id}
            )
        ).scalar()
        or 0
    )
    if rows == 0:
        return False
    log.warning(
        "plan_window_leaves_tenant_unpriced",
        extra={
            "tenant_id": str(tenant_id),
            "plan_rows": rows,
            "at": (at or datetime.now(UTC)).isoformat(),
            # What to do about it, on the line itself: an operator reading this at 2am
            # should not have to find this module to know the shape of the fix.
            "remedy": "insert a successor plan row, or clear effective_to on the current one",
        },
    )
    return True


__all__ = [
    "IST",
    "NOW_SQL",
    "ist_billing_month",
    "month_pricing_instant",
    "parse_billing_month",
    "plan_in_effect_sql",
    "warn_no_plan_in_effect",
]
