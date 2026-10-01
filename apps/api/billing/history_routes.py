"""The client's statement list and daily spend series (D-660).

    GET /v1/billing/statements     every month with a statement, newest first, paged
    GET /v1/billing/spend/daily    what left the wallet each IST day over a window

Both require `billing:read` — the permission `GET /v1/billing/invoice` and
`GET /v1/billing/spend` take, which owners hold and staff do not (SEC-COMP §5), and which is
not mutating, so a D-22 view-as session sees what the client sees. The tenant comes from the
principal and the session is RLS-scoped to it; there is no tenant parameter to point
elsewhere. The computations live in `billing/history.py`; this file only publishes them.

NOT mounted here — `main.py` mounts it with the other `/v1/billing/*` routers.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing import history
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/billing", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
BillingReader = Annotated[Principal, Depends(requires("billing:read"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatementSummaryOut(Strict):
    """One month's statement, summarised. Money is a paise string (hard rule 7)."""

    #: IST billing month, YYYY-MM — the key: `GET /v1/billing/invoice?month=<month>`.
    month: str
    #: False for the current IST month, whose statement still grows.
    closed: bool
    #: `bill_of_supply` while Calevate is not GST-registered (D-659), as on the statement.
    document_type: str
    invoice_number: str
    #: The statement's own `total_inr`, from the same `build_invoice` call.
    total_inr: str
    #: Credit that landed on the wallet in the month: payments, pack bonuses, positive
    #: corrections and goodwill grants — the wallet screen's "added" definition.
    credit_added_inr: str
    #: What left the wallet in the month: calls, extra dashboard AI and negative
    #: corrections — the wallet screen's "spent" definition, by debit date.
    wallet_spent_inr: str
    calls: int
    minutes_used: str


class StatementListOut(Strict):
    statements: list[StatementSummaryOut]
    #: Pass as `before` for the next (older) page; null on the last page.
    next_before: str | None


class SpendDayOut(Strict):
    #: IST calendar date, YYYY-MM-DD.
    date: str
    calls_inr: str
    ai_assist_inr: str
    adjustments_inr: str
    spent_inr: str


class AgentDailySpendOut(Strict):
    #: Null for call debits whose call this account cannot resolve to an agent.
    agent_id: UUID | None
    agent_name: str | None
    calls_inr: str


class SpendSeriesOut(Strict):
    """Daily wallet spend in IST. Each money column of `days` sums EXACTLY to the total of
    the same name, and `by_agent[].calls_inr` sums exactly to `calls_inr`."""

    #: What the figures are: debits off the prepaid wallet, dated by the debit (see
    #: `billing/history.py` on why this is not the month's calling charge).
    basis: Literal["wallet_debits"]
    timezone: Literal["Asia/Kolkata"]
    #: Inclusive IST dates, YYYY-MM-DD.
    from_date: str
    to_date: str
    days: list[SpendDayOut]
    calls_inr: str
    ai_assist_inr: str
    adjustments_inr: str
    spent_inr: str
    by_agent: list[AgentDailySpendOut]


@router.get(
    "/statements",
    response_model=StatementListOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This account's monthly statements, newest first",
    description=(
        "One row per IST month from the month the account opened to now, each summarising "
        "the statement `GET /v1/billing/invoice?month=` returns for it. Paged by `before` "
        "(a YYYY-MM month; rows strictly older are returned) and bounded by `limit`."
    ),
)
async def list_statements(
    session: Session,
    principal: BillingReader,
    limit: Annotated[int, Query(ge=1, le=history.MAX_STATEMENTS)] = history.DEFAULT_STATEMENTS,
    before: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> StatementListOut:
    assert principal.tenant_id is not None
    page = await history.statement_page(
        session, tenant_id=principal.tenant_id, limit=limit, before=before
    )
    return StatementListOut(
        statements=[
            StatementSummaryOut(
                month=row.month,
                closed=row.closed,
                document_type=row.document_type,
                invoice_number=row.invoice_number,
                total_inr=str(row.total_inr),
                credit_added_inr=str(row.credit_added_inr),
                wallet_spent_inr=str(row.wallet_spent_inr),
                calls=row.calls,
                minutes_used=str(row.minutes_used),
            )
            for row in page.statements
        ],
        next_before=page.next_before,
    )


@router.get(
    "/spend/daily",
    response_model=SpendSeriesOut,
    openapi_extra=permission_meta("billing:read"),
    summary="What left the wallet each day (IST), with explicit zero days",
    description=(
        "Send `days` (7, 30 or 90, ending today IST) or both `from` and `to` (IST dates, "
        f"inclusive, at most {history.MAX_SERIES_DAYS} days). Defaults to the last 30 days."
    ),
)
async def daily_spend(
    session: Session,
    principal: BillingReader,
    days: Annotated[int | None, Query(ge=7, le=90, description="7, 30 or 90")] = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> SpendSeriesOut:
    assert principal.tenant_id is not None
    start, end = history.series_window(days=days, start=from_date, end=to_date)
    series = await history.spend_series(
        session, tenant_id=principal.tenant_id, start=start, end=end
    )
    return SpendSeriesOut(
        basis="wallet_debits",
        timezone="Asia/Kolkata",
        from_date=series.start.isoformat(),
        to_date=series.end.isoformat(),
        days=[
            SpendDayOut(
                date=day.day.isoformat(),
                calls_inr=str(day.calls_inr),
                ai_assist_inr=str(day.ai_assist_inr),
                adjustments_inr=str(day.adjustments_inr),
                spent_inr=str(day.spent_inr),
            )
            for day in series.days
        ],
        calls_inr=str(series.calls_inr),
        ai_assist_inr=str(series.ai_assist_inr),
        adjustments_inr=str(series.adjustments_inr),
        spent_inr=str(series.spent_inr),
        by_agent=[
            AgentDailySpendOut(
                agent_id=agent.agent_id, agent_name=agent.agent_name, calls_inr=str(agent.calls_inr)
            )
            for agent in series.by_agent
        ],
    )


__all__ = ["router"]
