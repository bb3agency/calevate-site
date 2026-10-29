"""Pip's charts and tables (D-934): typed specs built from the account's real data.

Each chart is one `ChartAbility`: a name, the permission the screen showing the same
figures declares, and a builder that calls an EXISTING service read — `analytics.service`
(the Performance screen), `crm/service` under the leads lens, `billing/history.spend_series`
(the Spend screen), the call-backs list, the questions list, practice-test runs, and for the
admin console the directory, health board and per-client spend walks. No builder writes SQL
of its own; tenancy is the RLS session it is handed, never a WHERE clause.

The same `build_in` serves the chat (through the `report_chart` / `fleet_chart` read tools)
and a pinned dashboard card (`copilot/pin_routes.py`), so a pin re-runs under the VIEWER's role: a
staff member who may not see billing gets a refusal on a spend card an owner pinned, not
the owner's figures.

The model never sees a spec. It gets a few lines of text (`spec_text`) and the browser gets
the spec itself through the `chart` stream frame: `_COLLECTED` carries the specs a turn's
read tools built out of the concurrent tool runs to `service._run_read_tools`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.admin.health import client_health
from apps.api.agents import roster
from apps.api.agents.test_conversations import latest_run
from apps.api.analytics import service as analytics
from apps.api.analytics.schemas import SummaryBucket
from apps.api.billing.history import spend_series
from apps.api.billing.plans import IST
from apps.api.callbacks import service as callbacks_service
from apps.api.copilot.chart_spec import (
    DEFAULT_CHART_DAYS,
    MAX_CHART_DAYS,
    MAX_CHART_ROWS,
    ChartArgs,
    ChartAxis,
    ChartColumn,
    ChartOpen,
    ChartSeries,
    ChartSpec,
)
from apps.api.copilot.tools import ReadTool, ToolContext, _clean
from apps.api.core.rbac import Permission, role_has
from apps.api.crm import lens as crm_lens
from apps.api.crm import service as crm_service
from apps.api.crm.schemas import LeadLensIn
from apps.api.db.session import tenant_session
from apps.api.teach import questions as teach_questions

ChartRealm = Literal["client", "admin"]

#: Builds one spec from a session already scoped for the chart's realm.
Builder = Callable[[AsyncSession, ToolContext, ChartArgs], Awaitable[ChartSpec]]


@dataclass(frozen=True, slots=True)
class ChartAbility:
    name: str
    realm: ChartRealm
    #: The permission the console screen with the same figures declares.
    permission: Permission
    build: Builder


class ChartRefusedError(Exception):
    """A chart this viewer may not see, or one that cannot be built. `reason` is a
    sentence for a person; it names no value."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _n(value: int | Decimal) -> str:
    return str(value)


def _bucket(days: int) -> SummaryBucket:
    """Days up to a month, weeks up to six months, months beyond: at most ~31 bars."""
    if days <= 31:
        return "day"
    return "week" if days <= 186 else "month"


def _window(args: ChartArgs) -> analytics.Window:
    return analytics.resolve_window(days=args.days, to=None)


def _span(window: analytics.Window) -> str:
    return f"{window.start:%d %b} to {window.end:%d %b %Y} (IST)"


def _shown(shown: int, total: int) -> int | None:
    """`shown` when the rows were cut, else None: a whole list says no "top N"."""
    return shown if total > shown else None


def _of(shown: int, total: int) -> int | None:
    return total if total > shown else None


def _ist(day: date) -> str:
    return day.isoformat()


# --- calls ---------------------------------------------------------------------------


async def _calls_by_day(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    assert ctx.tenant_id is not None
    window = _window(args)
    bucket = _bucket(window.days)
    result = await analytics.summary(
        session,
        tenant_id=ctx.tenant_id,
        window=window,
        bucket=bucket,
        agent_id=None,
        test_calls=False,
        may_see_spend=False,
    )
    return ChartSpec(
        chart="calls_by_day",
        args=args,
        kind="stacked_bar",
        title=f"Calls each {bucket}",
        unit="calls",
        x=ChartAxis(
            label=bucket.title(), bucket=bucket, labels=[_ist(r.from_date) for r in result.rows]
        ),
        series=[
            ChartSeries(
                key="answered", label="Answered", values=[_n(r.answered) for r in result.rows]
            ),
            ChartSeries(
                key="missed", label="Missed", values=[_n(r.calls - r.answered) for r in result.rows]
            ),
        ],
        total=_n(result.calls),
        counted=f"Every call {_span(window)}, by IST {bucket}. Test calls left out. "
        "Missed = rang but no conversation.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Calls", path="/calls"),
    )


async def _answered_vs_missed(
    session: AsyncSession, ctx: ToolContext, args: ChartArgs
) -> ChartSpec:
    window = _window(args)
    line = await analytics.timeline(session, window=window, agent_id=None, test_calls=False)
    return ChartSpec(
        chart="answered_vs_missed",
        args=args,
        kind="pie",
        title="Answered and missed calls",
        unit="calls",
        x=ChartAxis(label="Calls", bucket="category", labels=["Answered", "Missed"]),
        series=[
            ChartSeries(
                key="calls",
                label="Calls",
                values=[_n(line.answered), _n(line.calls - line.answered)],
            )
        ],
        total=_n(line.calls),
        counted=f"Every call {_span(window)}. Test calls left out.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Calls", path="/calls"),
    )


async def _calls_grouped(
    session: AsyncSession, args: ChartArgs, *, by: Literal["outcome", "agent"]
) -> ChartSpec:
    window = _window(args)
    result = await analytics.call_groups(
        session, window=window, by=by, agent_id=None, test_calls=False, limit=MAX_CHART_ROWS
    )
    if by == "outcome":
        labels = [g.key or "No outcome" for g in result.groups]
    else:
        labels = [g.label or "Removed agent" for g in result.groups]
    series = (
        [ChartSeries(key="calls", label="Calls", values=[_n(g.calls) for g in result.groups])]
        if by == "outcome"
        else [
            ChartSeries(
                key="answered", label="Answered", values=[_n(g.answered) for g in result.groups]
            ),
            ChartSeries(
                key="missed",
                label="Missed",
                values=[_n(g.calls - g.answered) for g in result.groups],
            ),
        ]
    )
    return ChartSpec(
        chart=f"calls_by_{by}",
        args=args,
        kind="bar" if by == "outcome" else "stacked_bar",
        title=f"Calls by {by}",
        unit="calls",
        x=ChartAxis(label=by.title(), bucket="category", labels=labels),
        series=series,
        total=_n(result.calls),
        counted=f"Every call {_span(window)}, counted per {by}. Test calls left out.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Performance", path="/performance"),
        shown=_shown(len(result.groups), result.groups_total),
        of=_of(len(result.groups), result.groups_total),
    )


async def _calls_by_outcome(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    return await _calls_grouped(session, args, by="outcome")


async def _calls_by_agent(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    return await _calls_grouped(session, args, by="agent")


async def _talk_minutes(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    window = _window(args)
    result = await analytics.stats(session, window=window, agent_id=None, test_calls=False)
    metric = next(m for m in result.metrics if m.key == "talk_minutes")
    value = metric.value if metric.value is not None else Decimal(0)
    return ChartSpec(
        chart="talk_minutes",
        args=args,
        kind="number",
        title="Minutes on calls",
        unit="minutes",
        series=[ChartSeries(key="minutes", label="Minutes", values=[_n(value)])],
        total=_n(value),
        counted=f"Talk time of answered calls {_span(window)}. Test calls left out."
        + (
            f" The {window.days} days before: {metric.previous} minutes."
            if metric.previous is not None
            else ""
        ),
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Performance", path="/performance"),
    )


# --- leads ---------------------------------------------------------------------------


def _lead_lens(window: analytics.Window, **extra: Any) -> LeadLensIn:
    return LeadLensIn(created_from=window.start, created_to=window.end, **extra)


async def _leads_by_day(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    window = _window(args)
    line = await analytics.timeline(session, window=window, agent_id=None, test_calls=False)
    return ChartSpec(
        chart="leads_by_day",
        args=args,
        kind="line",
        title="New leads each day",
        unit="leads",
        x=ChartAxis(label="Day", bucket="day", labels=[_ist(d.ist_date) for d in line.days]),
        series=[
            ChartSeries(key="leads", label="New leads", values=[_n(d.leads) for d in line.days])
        ],
        total=_n(line.leads),
        counted=f"Leads created {_span(window)}, by IST day.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Leads", path="/leads"),
    )


async def _leads_by_status(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    window = _window(args)
    scope = await crm_lens.resolve_lead_scope(session, _lead_lens(window))
    page = await crm_service.list_leads_page(session, limit=1, more=scope.more)
    names = list(page.status_counts)
    return ChartSpec(
        chart="leads_by_status",
        args=args,
        kind="bar",
        title="Leads by status",
        unit="leads",
        x=ChartAxis(label="Status", bucket="category", labels=[n.replace("_", " ") for n in names]),
        series=[
            ChartSeries(
                key="leads", label="Leads", values=[_n(page.status_counts[n]) for n in names]
            )
        ],
        total=_n(sum(page.status_counts.values())),
        counted=f"Leads created {_span(window)}, by their status now.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Leads", path="/leads"),
    )


async def _leads_grouped(
    session: AsyncSession, args: ChartArgs, *, by: crm_service.LeadGroupBy
) -> ChartSpec:
    window = _window(args)
    scope = await crm_lens.resolve_lead_scope(session, _lead_lens(window))
    found = await crm_service.lead_groups(session, by=by, more=scope.more)
    shown = found.groups[:MAX_CHART_ROWS]
    fallback = "Unknown" if by == "source" else "Removed agent"
    return ChartSpec(
        chart=f"leads_by_{by}",
        args=args,
        kind="bar",
        title=f"Leads by {by}",
        unit="leads",
        x=ChartAxis(
            label=by.title(),
            bucket="category",
            labels=[(label or fallback).replace("_", " ") for _, label, _ in shown],
        ),
        series=[ChartSeries(key="leads", label="Leads", values=[_n(n) for _, _, n in shown])],
        total=_n(found.total),
        counted=f"Leads created {_span(window)}, counted per {by}.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Leads", path="/leads"),
        shown=_shown(len(shown), found.groups_total),
        of=_of(len(shown), found.groups_total),
    )


async def _leads_by_source(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    return await _leads_grouped(session, args, by="source")


async def _leads_by_agent(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    return await _leads_grouped(session, args, by="agent")


async def _hot_leads(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    """The hot leads, newest change first — the Leads screen with the hot stage picked. Not
    windowed: a hot lead from last month still needs a call."""
    del ctx
    page = await crm_service.list_leads_page(session, limit=MAX_CHART_ROWS, status="hot")
    rows = [
        [
            lead.name or "No name yet",
            _n(lead.call_count),
            lead.assigned_to_name or "Nobody",
            f"{lead.updated_at.astimezone(IST):%d %b %H:%M}",
        ]
        for lead in page.items
    ]
    return ChartSpec(
        chart="hot_leads",
        args=args,
        kind="table",
        title="Hot leads",
        unit="leads",
        columns=[
            ChartColumn(key="lead", label="Lead"),
            ChartColumn(key="calls", label="Calls", numeric=True),
            ChartColumn(key="owner", label="Owner"),
            ChartColumn(key="updated", label="Last change (IST)"),
        ],
        rows=rows,
        total=_n(page.total),
        counted="Every lead whose status is hot now, most recently changed first.",
        open=ChartOpen(screen="Leads", path="/leads", query={"status": "hot"}),
        shown=_shown(len(rows), page.total),
        of=_of(len(rows), page.total),
    )


async def _callbacks_due(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    found = await callbacks_service.list_callbacks(
        session, limit=MAX_CHART_ROWS + 1, open_only=True
    )
    shown = found[:MAX_CHART_ROWS]
    rows = [
        [
            f"{row['requested_at'].astimezone(IST):%d %b %H:%M}",
            "Held: campaign paused" if row["held"] else "Waiting",
            _n(int(row["attempts"])),
        ]
        for row in shown
    ]
    more = len(found) > len(shown)
    return ChartSpec(
        chart="callbacks_due",
        args=args,
        kind="table",
        title="Call-backs due",
        unit="count",
        columns=[
            ChartColumn(key="due", label="Due (IST)"),
            ChartColumn(key="state", label="State"),
            ChartColumn(key="attempts", label="Tries", numeric=True),
        ],
        rows=rows,
        total=None if more else _n(len(rows)),
        counted="Call-backs still waiting, soonest first."
        + (
            f" The first {len(rows)} are shown; the rest are on the Call-backs screen."
            if more
            else ""
        ),
        open=ChartOpen(screen="Call-backs", path="/callbacks"),
    )


# --- campaigns, money, knowledge, tests ------------------------------------------------


async def _campaign_progress(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    window = _window(args)
    result = await analytics.campaign_timelines(
        session, window=window, campaign_id=None, limit=MAX_CHART_ROWS
    )
    campaigns = result.campaigns
    return ChartSpec(
        chart="campaign_progress",
        args=args,
        kind="stacked_bar",
        title="Campaign calls",
        unit="calls",
        x=ChartAxis(label="Campaign", bucket="category", labels=[c.name for c in campaigns]),
        series=[
            ChartSeries(
                key="connected", label="Connected", values=[_n(c.connected) for c in campaigns]
            ),
            ChartSeries(
                key="not_connected",
                label="Not connected",
                values=[_n(c.dials - c.connected) for c in campaigns],
            ),
        ],
        total=_n(sum(c.dials for c in campaigns)),
        counted=f"Calls each campaign placed {_span(window)}, the busiest "
        f"{MAX_CHART_ROWS} at most.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Campaigns", path="/campaigns"),
    )


async def _spend_by_day(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    assert ctx.tenant_id is not None
    window = _window(args)
    series = await spend_series(
        session, tenant_id=ctx.tenant_id, start=window.start, end=window.end
    )
    return ChartSpec(
        chart="spend_by_day",
        args=args,
        kind="bar",
        title="Spend each day",
        unit="inr",
        x=ChartAxis(label="Day", bucket="day", labels=[_ist(d.day) for d in series.days]),
        series=[
            ChartSeries(
                key="spent", label="Spent (₹)", values=[_n(d.spent_inr) for d in series.days]
            )
        ],
        total=_n(series.spent_inr),
        counted=f"What left your credit {_span(window)}, by IST day: calls, AI help, "
        "number rental and adjustments.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Credits & billing", path="/billing", query={"tab": "usage"}),
    )


async def _knowledge_gaps(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    assert ctx.tenant_id is not None
    found = await teach_questions.list_questions(session, tenant_id=ctx.tenant_id)
    shown = found.items[:MAX_CHART_ROWS]
    why = {"callers": "Callers asked", "practice": "Practice test", "setup": "Setup"}
    rows = [[_clean(q.question), why.get(q.why, q.why), _n(q.callers)] for q in shown]
    return ChartSpec(
        chart="knowledge_gaps",
        args=args,
        kind="table",
        title="Questions your agents could not answer",
        unit="count",
        columns=[
            ChartColumn(key="question", label="Question"),
            ChartColumn(key="why", label="Why"),
            ChartColumn(key="callers", label="Calls", numeric=True),
        ],
        rows=rows,
        total=_n(found.open_count),
        counted="Open questions, most asked first.",
        open=ChartOpen(screen="What your agents know", path="/knowledge"),
        shown=_shown(len(rows), found.open_count),
        of=_of(len(rows), found.open_count),
    )


async def _test_results(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    del ctx
    agents = await roster.list_agents(session, limit=MAX_CHART_ROWS)
    names: list[str] = []
    counts: dict[str, list[int]] = {"passed": [], "needs_fix": [], "failed": []}
    for agent in agents:
        run = await latest_run(session, agent.id)
        if run is None or run.status != "done":
            continue
        names.append(agent.name)
        for verdict, column in counts.items():
            column.append(sum(1 for r in run.results if r.get("verdict") == verdict))
    labels = {"passed": "Passed", "needs_fix": "Needs a fix", "failed": "Failed"}
    return ChartSpec(
        chart="test_results",
        args=args,
        kind="stacked_bar",
        title="Practice test results",
        unit="count",
        x=ChartAxis(label="Agent", bucket="category", labels=names),
        series=[
            ChartSeries(key=key, label=labels[key], values=[_n(v) for v in column])
            for key, column in counts.items()
        ],
        total=_n(sum(sum(column) for column in counts.values())),
        counted="Each agent's latest finished practice test run. Agents never tested are left out.",
        open=ChartOpen(screen="Agents", path="/agents"),
    )


# --- admin: across clients -------------------------------------------------------------


async def _fleet_calls(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    """`GET /v1/admin/tenants`' own counts. Its call figure is the last 7 days, so the chart
    says so whatever window was asked for."""
    del ctx
    rows = await admin_service.tenant_overview(session, limit=admin_service.MAX_DIRECTORY_PAGE)
    ranked = sorted(rows, key=lambda r: (-int(r["calls_7d"]), str(r["name"])))
    shown = ranked[:MAX_CHART_ROWS]
    return ChartSpec(
        chart="fleet_calls",
        args=ChartArgs(days=7),
        kind="bar",
        title="Calls by client, last 7 days",
        unit="calls",
        x=ChartAxis(label="Client", bucket="category", labels=[str(r["name"]) for r in shown]),
        series=[
            ChartSeries(key="calls", label="Calls", values=[_n(int(r["calls_7d"])) for r in shown])
        ],
        total=_n(sum(int(r["calls_7d"]) for r in rows)),
        counted="Every call of each client in the last 7 days, busiest first.",
        open=ChartOpen(screen="Clients", path=""),
        shown=_shown(len(shown), len(rows)),
        of=_of(len(shown), len(rows)),
    )


async def _fleet_failures(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    """The client-health board: each account's live signals by severity, worst first."""
    del ctx
    board = await client_health(session)
    shown = board[:MAX_CHART_ROWS]

    def count(row: Any, severity: str) -> str:
        return _n(sum(1 for s in row.signals if s.severity == severity))

    return ChartSpec(
        chart="fleet_failures",
        args=ChartArgs(days=7),
        kind="stacked_bar",
        title="Problems by client",
        unit="count",
        x=ChartAxis(label="Client", bucket="category", labels=[row.name for row in shown]),
        series=[
            ChartSeries(key="stop", label="Broken", values=[count(r, "stop") for r in shown]),
            ChartSeries(key="warn", label="Warning", values=[count(r, "warn") for r in shown]),
        ],
        total=_n(sum(len(r.signals) for r in board)),
        counted="Live health signals on each client now, worst first. Healthy clients are "
        "left out.",
        open=ChartOpen(screen="Client health", path="/health"),
        shown=_shown(len(shown), len(board)),
        of=_of(len(shown), len(board)),
    )


async def _fleet_spend(session: AsyncSession, ctx: ToolContext, args: ChartArgs) -> ChartSpec:
    """Each client's wallet spend over the window, read inside the client's own tenant
    session with the Spend screen's reader — the directory walk `fleet_spend` makes."""
    del ctx
    window = _window(args)
    rows = await admin_service.tenant_overview(session, limit=admin_service.MAX_DIRECTORY_PAGE)
    spent: list[tuple[str, Decimal]] = []
    for row in rows:
        async with tenant_session(row["id"]) as scoped:
            series = await spend_series(
                scoped, tenant_id=row["id"], start=window.start, end=window.end
            )
        spent.append((str(row["name"]), series.spent_inr))
    ranked = sorted(spent, key=lambda pair: (-pair[1], pair[0]))
    shown = ranked[:MAX_CHART_ROWS]
    return ChartSpec(
        chart="fleet_spend",
        args=args,
        kind="bar",
        title="Spend by client",
        unit="inr",
        x=ChartAxis(label="Client", bucket="category", labels=[name for name, _ in shown]),
        series=[ChartSeries(key="spent", label="Spent (₹)", values=[_n(v) for _, v in shown])],
        total=_n(sum((v for _, v in spent), Decimal(0))),
        counted=f"What left each client's credit {_span(window)}, highest first.",
        window_from=window.start,
        window_to=window.end,
        open=ChartOpen(screen="Spend", path="/spend"),
        shown=_shown(len(shown), len(spent)),
        of=_of(len(shown), len(spent)),
    )


#: Every chart, in wire order (the tool's enum): append, never reorder.
ABILITIES: Final[tuple[ChartAbility, ...]] = (
    ChartAbility("calls_by_day", "client", "calls:read", _calls_by_day),
    ChartAbility("answered_vs_missed", "client", "calls:read", _answered_vs_missed),
    ChartAbility("calls_by_outcome", "client", "calls:read", _calls_by_outcome),
    ChartAbility("calls_by_agent", "client", "calls:read", _calls_by_agent),
    ChartAbility("talk_minutes", "client", "calls:read", _talk_minutes),
    ChartAbility("leads_by_day", "client", "leads:read", _leads_by_day),
    ChartAbility("leads_by_status", "client", "leads:read", _leads_by_status),
    ChartAbility("leads_by_source", "client", "leads:read", _leads_by_source),
    ChartAbility("leads_by_agent", "client", "leads:read", _leads_by_agent),
    ChartAbility("hot_leads", "client", "leads:read", _hot_leads),
    ChartAbility("callbacks_due", "client", "leads:read", _callbacks_due),
    ChartAbility("campaign_progress", "client", "calls:read", _campaign_progress),
    ChartAbility("spend_by_day", "client", "billing:read", _spend_by_day),
    ChartAbility("knowledge_gaps", "client", "agents:read", _knowledge_gaps),
    ChartAbility("test_results", "client", "agents:read", _test_results),
    ChartAbility("fleet_calls", "admin", "admin:tenants", _fleet_calls),
    ChartAbility("fleet_failures", "admin", "admin:tenants", _fleet_failures),
    ChartAbility("fleet_spend", "admin", "billing:read", _fleet_spend),
)

BY_NAME: Final[Mapping[str, ChartAbility]] = {a.name: a for a in ABILITIES}


def names(realm: ChartRealm) -> list[str]:
    return [a.name for a in ABILITIES if a.realm == realm]


def chart_args(raw: Mapping[str, Any]) -> ChartArgs:
    """`days` from a model or a stored pin; null or junk is the default, out of range is
    clamped (the schema cannot say `minimum`)."""
    days = raw.get("days")
    if not isinstance(days, int) or isinstance(days, bool):
        return ChartArgs(days=DEFAULT_CHART_DAYS)
    return ChartArgs(days=max(1, min(days, MAX_CHART_DAYS)))


def ability(name: str, realm: ChartRealm) -> ChartAbility:
    found = BY_NAME.get(name)
    if found is None or found.realm != realm:
        raise ChartRefusedError("There is no such chart.")
    return found


def refusal_for(found: ChartAbility, role: str | None) -> str | None:
    """Why this viewer may not see this chart, or None."""
    if role is None or not role_has(role, found.permission):
        return (
            f"You do not have permission to see this ({found.permission}). Ask the account owner."
        )
    return None


async def build_in(
    session: AsyncSession,
    context: ToolContext,
    name: str,
    raw: Mapping[str, Any],
    realm: ChartRealm,
) -> ChartSpec:
    """One spec, on a session already scoped for `realm`. Raises `ChartRefusedError`."""
    found = ability(name, realm)
    refused = refusal_for(found, context.role)
    if refused is not None:
        raise ChartRefusedError(refused)
    try:
        return await found.build(session, context, chart_args(raw))
    except ValidationError as exc:  # a lens the account's data cannot satisfy
        raise ChartRefusedError("This chart could not be built from your data.") from exc


# --- what the model reads, and the side channel to the browser -----------------------

#: The specs this turn's read tools built, in the order they finished. Set by
#: `service._run_read_tools` around one batch; a tool run outside a batch (a job, a test)
#: builds the text and drops the spec.
_COLLECTED: ContextVar[list[ChartSpec] | None] = ContextVar("copilot_charts", default=None)


@contextlib.contextmanager
def collecting() -> Iterator[list[ChartSpec]]:
    found: list[ChartSpec] = []
    token = _COLLECTED.set(found)
    try:
        yield found
    finally:
        _COLLECTED.reset(token)


def _values_line(spec: ChartSpec) -> str:
    if spec.kind == "table":
        return f"{len(spec.rows)} row(s): " + "; ".join(", ".join(row) for row in spec.rows[:5])
    if spec.x is None:
        return ", ".join(f"{s.label} {s.values[0]}" for s in spec.series if s.values)
    pairs: list[str] = []
    for index, label in enumerate(spec.x.labels[-12:]):
        at = len(spec.x.labels) - min(12, len(spec.x.labels)) + index
        pairs.append(f"{label}: " + ", ".join(f"{s.label} {s.values[at]}" for s in spec.series))
    return "; ".join(pairs)


def spec_text(spec: ChartSpec, *, pin_hint: bool) -> str:
    """What the model is told: that the person can see the chart, its figures in brief, and
    how to pin it. A few lines, because every token is re-read on each later turn."""
    cut = f" Top {spec.shown} of {spec.of}." if spec.shown is not None else ""
    lines = [
        f"SHOWN to the person as a chart: {spec.title}. {spec.counted}{cut}",
        f"Total {spec.total}." if spec.total is not None else "",
        _values_line(spec),
        "Say in one or two sentences what stands out; do not list every figure."
        + (f" To pin it: chart_pin chart={spec.chart} days={spec.args.days}." if pin_hint else ""),
    ]
    return _clean("\n".join(line for line in lines if line))


def _tool_executor(
    realm: ChartRealm,
) -> Callable[[AsyncSession, ToolContext, Mapping[str, Any]], Awaitable[str]]:
    async def run(session: AsyncSession, context: ToolContext, args: Mapping[str, Any]) -> str:
        name = args.get("chart")
        if not isinstance(name, str):
            return "Say which `chart`."
        try:
            spec = await build_in(session, context, name, args, realm)
        except ChartRefusedError as refused:
            return f"Not shown: {refused.reason} Tell the person; do not guess the figures."
        collected = _COLLECTED.get()
        if collected is not None:
            collected.append(spec)
        return spec_text(spec, pin_hint=realm == "client")

    return run


def _parameters(realm: ChartRealm) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "chart": {"type": "string", "enum": names(realm)},
            "days": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
        "required": ["chart", "days"],
        "additionalProperties": False,
    }


#: The client read. Its own permission is the floor every client role holds; each chart
#: checks the permission its own screen declares (`ChartAbility.permission`).
REPORT_CHART: Final = ReadTool(
    name="report_chart",
    description="A chart or table of this account's data, shown to the person.",
    parameters=_parameters("client"),
    permission="org:read",
    run=_tool_executor("client"),
)

#: The admin read, across clients, on the directory session.
FLEET_CHART: Final = ReadTool(
    name="fleet_chart",
    description="A chart across clients, shown to the operator; last N days (null 30).",
    parameters=_parameters("admin"),
    permission="admin:tenants",
    scope="platform",
    run=_tool_executor("admin"),
)

CHART_READS: Final[tuple[ReadTool, ...]] = (REPORT_CHART,)


__all__ = [
    "ABILITIES",
    "BY_NAME",
    "CHART_READS",
    "FLEET_CHART",
    "REPORT_CHART",
    "ChartAbility",
    "ChartRefusedError",
    "build_in",
    "chart_args",
    "collecting",
    "names",
    "refusal_for",
    "spec_text",
]
