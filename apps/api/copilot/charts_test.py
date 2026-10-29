"""D-934: Pip's chart specs — one per kind, built from the account's own data under its RLS
session, refused by the permission the matching screen declares, and handed to the browser
through the collector rather than to the model."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from tests.analytics_summary_test import _debit, _lead
from tests.analytics_test import _agent, _call, _ist, _today_ist
from tests.api_security_test import _make_tenant

from apps.api.copilot import charts, service, tools
from apps.api.copilot.chart_spec import ChartArgs, ChartSpec
from apps.api.db.session import tenant_session


async def _seed(tenant_id: UUID) -> None:
    today = _today_ist()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await _call(session, tenant_id, agent_id, at=_ist(today, 10), outcome="needs_you")
        await _call(session, tenant_id, agent_id, at=_ist(today, 11), outcome="needs_you")
        await _call(
            session, tenant_id, agent_id, at=_ist(today, 12), status="no_answer", duration_s=0
        )
        hot = await _lead(session, tenant_id, agent_id, "Ravi")
        await _lead(session, tenant_id, agent_id, "Sita")
        await session.execute(text("UPDATE leads SET status = 'hot' WHERE id = :id"), {"id": hot})
        await _debit(session, tenant_id, "12.50", _ist(today, 13), "87.50")


async def _build(tenant_id: UUID, name: str, *, role: str = "owner", days: int = 7) -> ChartSpec:
    context = tools.ToolContext(tenant_id=tenant_id, role=role)
    async with tenant_session(tenant_id) as session:
        return await charts.build_in(session, context, name, {"days": days}, "client")


def _numbers(spec: ChartSpec) -> list[Decimal]:
    """Every value parses as a decimal: the wire carries strings, never floats."""
    return [Decimal(v) for s in spec.series for v in s.values]


async def test_each_kind_is_built_from_the_accounts_own_rows() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _seed(tenant_id)

    by_day = await _build(tenant_id, "calls_by_day")
    assert by_day.kind == "stacked_bar" and by_day.x is not None and by_day.x.bucket == "day"
    assert len(by_day.x.labels) == 7 and by_day.x.labels[-1] == _today_ist().isoformat()
    answered, missed = by_day.series
    assert (answered.values[-1], missed.values[-1], by_day.total) == ("2", "1", "3")
    assert "Test calls left out" in by_day.counted and by_day.open is not None

    pie = await _build(tenant_id, "answered_vs_missed")
    assert pie.kind == "pie" and pie.series[0].values == ["2", "1"]

    outcomes = await _build(tenant_id, "calls_by_outcome")
    assert outcomes.kind == "bar" and outcomes.x is not None
    assert dict(zip(outcomes.x.labels, outcomes.series[0].values, strict=True))["needs_you"] == "2"

    leads = await _build(tenant_id, "leads_by_day")
    # `_make_tenant` files one lead of its own.
    assert leads.kind == "line" and leads.total == "3"

    status = await _build(tenant_id, "leads_by_status")
    assert status.kind == "bar" and status.x is not None
    assert dict(zip(status.x.labels, status.series[0].values, strict=True))["hot"] == "1"

    source = await _build(tenant_id, "leads_by_source")
    assert source.x is not None and "inbound call" in source.x.labels

    hot = await _build(tenant_id, "hot_leads")
    assert hot.kind == "table" and [row[0] for row in hot.rows] == ["Ravi"]
    assert hot.open is not None and hot.open.query == {"status": "hot"}
    assert all("+91" not in cell for row in hot.rows for cell in row)

    minutes = await _build(tenant_id, "talk_minutes")
    assert minutes.kind == "number" and minutes.x is None and minutes.total == "2.0"

    spend = await _build(tenant_id, "spend_by_day")
    assert spend.unit == "inr" and spend.total == "12.50"
    for spec in (by_day, pie, outcomes, leads, status, source, minutes, spend):
        assert _numbers(spec)


async def test_the_proof_charts_read_the_screens_figures() -> None:
    """D-944: rupees per result from the wallet, and the weekly reply speed."""
    tenant_id, _slug, _token = await _make_tenant()
    await _seed(tenant_id)
    cost = await _build(tenant_id, "cost_per_result")
    assert cost.kind == "table" and cost.unit == "inr" and cost.total == "12.50"
    rows = {row[0]: row[1:] for row in cost.rows}
    # Two answered calls, three leads (the fixture's own included), no booking.
    assert rows["Answered call"] == ["2", "6.25"]
    assert rows["Captured lead"] == ["3", "4.17"]
    assert rows["Booked result"] == ["0", "-"]
    speed = await _build(tenant_id, "reply_speed", days=14)
    assert speed.kind == "table" and len(speed.rows) == 2
    assert speed.rows[0][1] == "3"  # this week's calls, newest first
    assert speed.rows[0][3] == "-"  # no answer time measured, never zero


async def test_another_accounts_rows_never_reach_a_chart() -> None:
    mine, _s, _t = await _make_tenant()
    theirs, _s2, _t2 = await _make_tenant()
    await _seed(theirs)
    by_day = await _build(mine, "calls_by_day")
    hot = await _build(mine, "hot_leads")
    assert by_day.total == "0" and hot.rows == [] and hot.total == "0"


async def test_a_staff_member_without_billing_gets_no_spend_chart() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _seed(tenant_id)
    context = tools.ToolContext(tenant_id=tenant_id, role="staff")
    registry = service._read_tool_registry("client")
    with charts.collecting() as built:
        refused = await tools.run_read_tool(
            "report_chart",
            json.dumps({"chart": "spend_by_day", "days": 7}),
            context=context,
            registry=registry,
        )
        allowed = await tools.run_read_tool(
            "report_chart",
            json.dumps({"chart": "calls_by_day", "days": 7}),
            context=context,
            registry=registry,
        )
    assert "Not shown" in refused and "billing:read" in refused and "12.50" not in refused
    assert [spec.chart for spec in built] == ["calls_by_day"]
    assert allowed.startswith("SHOWN to the person") and "chart_pin chart=calls_by_day" in allowed


async def test_the_model_gets_text_and_the_browser_gets_the_spec() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _seed(tenant_id)
    answer = await tools.run_read_tool(
        "report_chart",
        json.dumps({"chart": "hot_leads", "days": None}),
        context=tools.ToolContext(tenant_id=tenant_id, role="owner"),
        registry=service._read_tool_registry("client"),
    )
    # Outside a turn's collector the spec is dropped and the text still answers.
    assert "Hot leads" in answer and "Ravi" in answer


async def test_an_unknown_or_other_realm_chart_is_refused() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    context = tools.ToolContext(tenant_id=tenant_id, role="owner")
    async with tenant_session(tenant_id) as session:
        for name in ("fleet_calls", "nonsense"):
            try:
                await charts.build_in(session, context, name, {}, "client")
            except charts.ChartRefusedError as refused:
                assert refused.reason == "There is no such chart."
            else:  # pragma: no cover - the assertion is the point
                raise AssertionError(name)


def test_days_are_clamped_and_defaulted() -> None:
    assert charts.chart_args({"days": 9999}) == ChartArgs(days=366)
    assert charts.chart_args({"days": 0}) == ChartArgs(days=1)
    assert charts.chart_args({"days": True}) == ChartArgs(days=30)
    assert charts.chart_args({}) == ChartArgs(days=30)


def test_the_client_and_admin_surfaces_offer_their_own_chart_tool() -> None:
    client = [tool["function"]["name"] for tool in service.tool_array("client")]
    admin = service.offered_names("admin", account_open=False)
    assert "fleet_chart" in admin and "report_chart" not in admin
    assert "reports_find" in client and "fleet_chart" not in client
    assert "report_chart" not in {t.name for t in service.realm_read_tools("admin")}
