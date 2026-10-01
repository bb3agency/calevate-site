"""A client's money over time: the months they have statements for, and spend per day.

Two reads the billing screens were missing (D-660). Neither is a new computation:

- **the statement list** is `invoice.build_invoice` run once per listed month, so each
  row's `total_inr` IS the statement it links to, plus the month's credit added and wallet
  spend summed with the wallet screen's own SQL (`wallet.CREDIT_ADDED_SQL`,
  `wallet.DRAWDOWN_BUCKETS_SQL`);
- **the daily spend series** is the wallet drawdown (`wallet.read_runway`'s three outgoing
  buckets) grouped by IST day, so a window's days sum to the drawdown over the same window
  exactly.

WHY THE SERIES IS THE WALLET'S AND NOT THE MONTH'S CALLING CHARGE. `/v1/billing/spend`'s
`period_charge_inr` attributes a call's debit to the month the CALL ran in
(`service._CALL_IN_MONTH`), because a statement belongs to the month of the supply. A
daily chart answers "what left my balance on this day", which is the debit's own instant;
re-keying each debit to its call's day would need the call's usage rows per debit and still
could not place a dashboard-AI block or an operator correction on any call. The two agree
on every closed month except across a late-settling call at a month boundary, and the
response says which basis it is (`basis`).

Money is `Decimal` summed in SQL over NUMERIC and published as paise strings (hard rule 7).
Each published column is split from its own paise total by `service.allocate_paise`, so the
days add up to the total beside them exactly rather than to within a paisa of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import OVERAGE_META_KIND
from apps.api.billing.invoice import build_invoice
from apps.api.billing.plans import IST, ist_billing_month, ist_month_window, parse_billing_month
from apps.api.billing.service import allocate_paise, to_paise
from apps.api.billing.wallet import CREDIT_ADDED_SQL, DRAWDOWN_BUCKETS_SQL
from apps.api.core.errors import ProblemError

#: The longest window one series request may cover. Ninety-two rather than ninety so a
#: calendar quarter (up to 92 days) fits; the payload is one row per day either way.
MAX_SERIES_DAYS: Final = 92

#: The lengths `days=` accepts. A query string arrives as text, and `Literal[7, 30, 90]`
#: refuses "7" outright in strict mode, so the set is checked here instead.
SERIES_LENGTHS: Final = frozenset({7, 30, 90})

#: Statements per page. Each row builds a whole statement, so this bounds the work as well
#: as the payload, and the route is on the `bulk_read` rate-limit profile for that reason.
DEFAULT_STATEMENTS: Final = 6
MAX_STATEMENTS: Final = 12

_ZERO = Decimal("0")

#: A ledger `ref` that is a call id. `usage` debits written by `charge_for_call` carry the
#: call's id; a dashboard-AI block's ref (`ai_assist:<YYYY-MM>`) does not, and a cast of the
#: column would fail the whole statement on the first such row — so the CASE guards it.
_CALL_REF = (
    "CASE WHEN e.ref ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
    "THEN e.ref::uuid END"
)

#: ONE statement, two reductions of one snapshot (the `GROUPING SETS` reason
#: `attribution._CALL_ROWS_SQL` records): per IST day, and per agent. Read separately, a
#: debit committed between the two reads would give a per-agent split that does not add to
#: the daily total. Half-open on `occurred_at` so the index on (tenant_id, occurred_at)
#: drives it; the IST day is only computed for the rows already in range.
_SERIES_SQL: Final = f"""
WITH d AS (
  SELECT e.delta, e.reason, e.meta,
         (e.occurred_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
         c.agent_id, a.name AS agent_name
    FROM credit_ledger e
    LEFT JOIN calls c ON e.reason = 'usage' AND c.id = {_CALL_REF}
    LEFT JOIN agents a ON a.id = c.agent_id
   WHERE e.tenant_id = :tid AND e.occurred_at >= :start AND e.occurred_at < :end
)
SELECT GROUPING(day) AS per_agent, day, agent_id, agent_name, {DRAWDOWN_BUCKETS_SQL}
  FROM d
 GROUP BY GROUPING SETS ((day), (agent_id, agent_name))
"""

#: Credit added and wallet spend per IST month over a range of months, in one pass.
_MONTH_TOTALS_SQL: Final = f"""
SELECT to_char(occurred_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') AS month,
       {CREDIT_ADDED_SQL}, {DRAWDOWN_BUCKETS_SQL}
  FROM credit_ledger
 WHERE tenant_id = :tid AND occurred_at >= :start AND occurred_at < :end
 GROUP BY 1
"""


@dataclass(frozen=True, slots=True)
class SpendDay:
    day: date
    calls_inr: Decimal
    ai_assist_inr: Decimal
    adjustments_inr: Decimal
    spent_inr: Decimal


@dataclass(frozen=True, slots=True)
class AgentSpend:
    """One agent's call debits in the window. `agent_id` None is call debits that name no
    call this account can see (a debit whose call row is absent)."""

    agent_id: UUID | None
    agent_name: str | None
    calls_inr: Decimal


@dataclass(frozen=True, slots=True)
class SpendSeries:
    start: date
    end: date
    days: tuple[SpendDay, ...]
    calls_inr: Decimal
    ai_assist_inr: Decimal
    adjustments_inr: Decimal
    spent_inr: Decimal
    by_agent: tuple[AgentSpend, ...]


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def series_window(
    *,
    days: int | None,
    start: date | None,
    end: date | None,
    now: datetime | None = None,
) -> tuple[date, date]:
    """The inclusive IST date range a request names, or a 422 saying what is wrong.

    Either `days` (ending today, IST) or BOTH `from` and `to`; never a mixture, because a
    request naming a length and a range has said two things and we would be choosing one.
    """
    today = today_ist(now)
    if days is not None and days not in SERIES_LENGTHS:
        raise _invalid_range("`days` is 7, 30 or 90.")
    if start is None and end is None:
        length = days or 30
        return today - timedelta(days=length - 1), today
    if days is not None or start is None or end is None:
        raise _invalid_range("Send `days`, or both `from` and `to` — not a mixture.")
    if end < start:
        raise _invalid_range("`to` is before `from`.")
    if end > today:
        raise _invalid_range("`to` is in the future; the series ends today at the latest.")
    if (end - start).days + 1 > MAX_SERIES_DAYS:
        raise _invalid_range(f"A series covers at most {MAX_SERIES_DAYS} days.")
    return start, end


def _invalid_range(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="invalid_spend_range",
        title="Invalid date range",
        detail=detail,
        remediation=(
            f"Use days=7, 30 or 90, or from=YYYY-MM-DD&to=YYYY-MM-DD (IST, at most "
            f"{MAX_SERIES_DAYS} days, ending no later than today)."
        ),
    )


def _ist_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=IST)


def _dec(value: object) -> Decimal:
    return Decimal(str(value)) if value is not None else _ZERO


async def spend_series(
    session: AsyncSession, *, tenant_id: UUID, start: date, end: date
) -> SpendSeries:
    """What left the wallet each IST day from `start` to `end` inclusive. Empty days are
    explicit zeros. Must run under a tenant-scoped session (`credit_ledger`, `calls` and
    `agents` are RLS'd)."""
    rows = (
        await session.execute(
            text(_SERIES_SQL),
            {
                "tid": tenant_id,
                "start": _ist_midnight(start),
                "end": _ist_midnight(end + timedelta(days=1)),
                "ai_kind": OVERAGE_META_KIND,
            },
        )
    ).all()

    raw_days: dict[date, tuple[Decimal, Decimal, Decimal]] = {}
    raw_agents: list[tuple[UUID | None, str | None, Decimal]] = []
    for per_agent, day, agent_id, agent_name, calls, ai, adjustments in rows:
        if per_agent:
            if _dec(calls) > 0:
                raw_agents.append(
                    (
                        UUID(str(agent_id)) if agent_id is not None else None,
                        str(agent_name) if agent_name is not None else None,
                        _dec(calls),
                    )
                )
        else:
            raw_days[day] = (_dec(calls), _dec(ai), _dec(adjustments))

    calendar = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    zero = (_ZERO, _ZERO, _ZERO)
    raw = [raw_days.get(day, zero) for day in calendar]
    raw_calls = [r[0] for r in raw]
    raw_ai = [r[1] for r in raw]
    raw_adj = [r[2] for r in raw]
    raw_spent = [r[0] + r[1] + r[2] for r in raw]

    total_calls = to_paise(sum(raw_calls, _ZERO))
    total_ai = to_paise(sum(raw_ai, _ZERO))
    total_adj = to_paise(sum(raw_adj, _ZERO))
    # The SAME rounding `wallet_routes.read_wallet_summary` applies to `spent_inr`: the raw
    # sum, quantized once — not the sum of three rounded buckets.
    total_spent = to_paise(sum(raw_spent, _ZERO))

    calls_days = allocate_paise(raw_calls, total_calls)
    ai_days = allocate_paise(raw_ai, total_ai)
    adj_days = allocate_paise(raw_adj, total_adj)
    spent_days = allocate_paise(raw_spent, total_spent)

    # Agents sorted by spend, largest first, then by name for a stable order; the
    # allocation is over that order so ties resolve the same way on every read.
    raw_agents.sort(key=lambda agent: (-agent[2], agent[1] or "", str(agent[0] or "")))
    agent_amounts = allocate_paise([agent[2] for agent in raw_agents], total_calls)

    return SpendSeries(
        start=start,
        end=end,
        days=tuple(
            SpendDay(
                day=day,
                calls_inr=calls_days[i],
                ai_assist_inr=ai_days[i],
                adjustments_inr=adj_days[i],
                spent_inr=spent_days[i],
            )
            for i, day in enumerate(calendar)
        ),
        calls_inr=total_calls,
        ai_assist_inr=total_ai,
        adjustments_inr=total_adj,
        spent_inr=total_spent,
        by_agent=tuple(
            AgentSpend(agent_id=agent[0], agent_name=agent[1], calls_inr=amount)
            for agent, amount in zip(raw_agents, agent_amounts, strict=True)
        ),
    )


@dataclass(frozen=True, slots=True)
class StatementSummary:
    month: str
    closed: bool
    document_type: str
    invoice_number: str
    total_inr: Decimal
    credit_added_inr: Decimal
    wallet_spent_inr: Decimal
    calls: int
    minutes_used: Decimal


@dataclass(frozen=True, slots=True)
class StatementPage:
    statements: tuple[StatementSummary, ...]
    #: Pass as `before` for the next (older) page; None when this page reached the month
    #: the account was opened.
    next_before: str | None


def _previous_month(month: str) -> str:
    year, mon = parse_billing_month(month)
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


async def statement_page(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    limit: int,
    before: str | None,
    now: datetime | None = None,
) -> StatementPage:
    """Every IST month from the account's opening month to now, newest first, a page at a
    time. Every such month HAS a statement (it is derived, D-46), including a month with
    nothing billed, which is listed with a zero total rather than hidden: a gap in a list
    of monthly statements reads as a missing document."""
    current = ist_billing_month(now or datetime.now(UTC))
    created = (
        await session.execute(
            text("SELECT created_at FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    if created is None:
        raise ProblemError.not_found("Organization")
    first = ist_billing_month(created)

    newest = current
    if before is not None:
        parse_billing_month(before)
        newest = min(_previous_month(before), current)

    months: list[str] = []
    month = newest
    while month >= first and len(months) < limit:
        months.append(month)
        month = _previous_month(month)
    if not months:
        return StatementPage(statements=(), next_before=None)

    totals_rows = (
        await session.execute(
            text(_MONTH_TOTALS_SQL),
            {
                "tid": tenant_id,
                "start": ist_month_window(months[-1])[0],
                "end": ist_month_window(months[0])[1],
                "ai_kind": OVERAGE_META_KIND,
            },
        )
    ).all()
    totals = {
        str(row[0]): (_dec(row[1]), _dec(row[2]) + _dec(row[3]) + _dec(row[4]))
        for row in totals_rows
    }

    summaries: list[StatementSummary] = []
    for listed in months:
        invoice = await build_invoice(session, tenant_id=tenant_id, month=listed)
        added, spent = totals.get(listed, (_ZERO, _ZERO))
        summaries.append(
            StatementSummary(
                month=listed,
                closed=listed < current,
                document_type=str(invoice["document_type"]),
                invoice_number=str(invoice["invoice_number"]),
                total_inr=invoice["total_inr"],
                credit_added_inr=to_paise(added),
                wallet_spent_inr=to_paise(spent),
                calls=int(invoice["usage"]["calls"]),
                minutes_used=invoice["usage"]["minutes_used"],
            )
        )
    oldest = months[-1]
    return StatementPage(
        statements=tuple(summaries),
        next_before=oldest if oldest > first else None,
    )


__all__ = [
    "DEFAULT_STATEMENTS",
    "MAX_SERIES_DAYS",
    "MAX_STATEMENTS",
    "SERIES_LENGTHS",
    "AgentSpend",
    "SpendDay",
    "SpendSeries",
    "StatementPage",
    "StatementSummary",
    "series_window",
    "spend_series",
    "statement_page",
    "today_ist",
]
