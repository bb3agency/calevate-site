"""The voice platform's call insights (D-940): read by the adapter into our own model, stored
on the call with the customer's words redacted, shown on the call detail, and cleared with
the call's other transcript-derived prose."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.crm import service as crm
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import ThinnestEngine, parse_insights
from apps.workers import retention
from apps.workers.pipeline import _record_reading, stored_insights
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import CallInsights
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import create_org_with_receptionist

# The example on `call.analysed` (snapshots/2026-10-29/pages/api-reference/webhooks.md:453-465).
_INSIGHTS: dict[str, Any] = {
    "outcome": "interested",
    "noReason": None,
    "objections": [{"text": "Budget is tight", "kind": "price"}],
    "issues": [],
    "nextStep": {
        "kind": "visit",
        "at": "2026-10-31T04:30:00.000Z",
        "note": "Site visit on Saturday",
        "status": "open",
        "followedUpAt": None,
    },
}


def test_the_documented_reading_parses_into_our_names() -> None:
    insights = parse_insights(_INSIGHTS)
    assert insights is not None
    assert (insights.outcome, insights.no_reason) == ("interested", None)
    assert [(o.text, o.kind) for o in insights.objections] == [("Budget is tight", "price")]
    assert insights.issues == []
    step = insights.next_step
    assert step is not None
    assert (step.kind, step.note, step.status) == ("visit", "Site visit on Saturday", "open")
    assert step.at == datetime(2026, 10, 31, 4, 30, tzinfo=UTC)


def test_no_reading_and_an_unknown_outcome_are_no_insights() -> None:
    assert parse_insights(None) is None
    assert parse_insights({**_INSIGHTS, "outcome": "maybe"}) is None


def test_unknown_kinds_are_other_blank_texts_dropped_and_limits_held() -> None:
    insights = parse_insights(
        {
            "outcome": "not_interested",
            "noReason": "weather",
            "objections": [{"text": " ", "kind": "price"}]
            + [{"text": "x" * 200, "kind": "mood"}] * 7,
            "issues": [{"text": "App login fails", "kind": "login"}, "junk"],
            "nextStep": {"kind": "teleport"},
        }
    )
    assert insights is not None
    assert insights.no_reason is None
    assert len(insights.objections) == 4
    assert {o.kind for o in insights.objections} == {"other"}
    assert all(len(o.text) == 120 for o in insights.objections)
    assert [(i.text, i.kind) for i in insights.issues] == [("App login fails", "login")]
    assert insights.next_step is None


def test_the_snapshot_carries_insights_only_once_the_call_is_read() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    call = {"id": "call_1", "status": "completed", "insights": _INSIGHTS}
    assert engine._snapshot(call, workspace=None).insights is None
    read = engine._snapshot({**call, "analysedAt": "2026-10-29T10:00:00Z"}, workspace=None)
    assert read.insights is not None and read.insights.outcome == "interested"
    assert "Budget is tight" not in repr(read)


def test_the_customers_words_are_redacted_before_they_are_stored() -> None:
    insights = CallInsights.model_validate(
        {
            "outcome": "callback",
            "objections": [{"text": "Call me on 9876543210 after salary day", "kind": "timing"}],
            "issues": [{"text": "Paid from 9876543210 twice", "kind": "billing"}],
            "next_step": {"kind": "callback", "note": "Ring 9876543210 on Friday"},
        }
    )
    stored = stored_insights(insights)
    assert stored is not None and "9876543210" not in stored
    assert "salary day" in stored
    assert stored_insights(None) is None


async def test_the_reading_step_stores_it_redacted_and_a_reading_without_one_keeps_it() -> None:
    tenant_id, call_id = await _call_with_insights(stored=False)
    said = {**_INSIGHTS, "objections": [{"text": "Call 9876543210 after Diwali", "kind": "timing"}]}
    read = ExecutionSnapshot(
        engine_call_id=f"local:{call_id}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        insights=parse_insights(said),
    )
    await _record_reading(tenant_id, call_id, read, None)
    await _record_reading(tenant_id, call_id, read.model_copy(update={"insights": None}), None)
    async with tenant_session(tenant_id) as session:
        held = (
            await session.execute(
                text("SELECT insights FROM calls WHERE id = :id"), {"id": call_id}
            )
        ).scalar_one()
    assert held["outcome"] == "interested"
    assert "9876543210" not in held["objections"][0]["text"]
    assert "Diwali" in held["objections"][0]["text"]


async def _call_with_insights(*, stored: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Insight Estates",
        slug=f"ins-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    call_id = uuid7()
    insights = parse_insights(_INSIGHTS)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "ended_at, insights, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'outbound', 'completed', :ended, CAST(:i AS jsonb), now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"local:{call_id}",
                "ended": datetime.now(UTC) - timedelta(days=2),
                "i": stored_insights(insights) if stored else None,
            },
        )
    return tenant_id, call_id


async def test_the_call_detail_shows_the_stored_reading_to_its_own_account_only() -> None:
    tenant_id, call_id = await _call_with_insights()
    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
    assert detail.insights is not None
    assert detail.insights.outcome == "interested"
    assert [o.text for o in detail.insights.objections] == ["Budget is tight"]
    assert detail.insights.next_step is not None
    assert detail.insights.next_step.kind == "visit"

    other, _ = await _call_with_insights()
    async with tenant_session(other) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE id = :id AND insights IS NOT NULL"),
                {"id": call_id},
            )
        ).scalar_one()
    assert seen == 0


async def test_the_transcript_clock_clears_the_reading_with_the_summary() -> None:
    tenant_id, call_id = await _call_with_insights()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(retention._SUMMARY_SQL),
            {"cutoff": datetime.now(UTC) - timedelta(days=1), "batch": 100},
        )
        held = (
            await session.execute(
                text("SELECT insights FROM calls WHERE id = :id"), {"id": call_id}
            )
        ).scalar_one()
        detail = await crm.get_call(session, call_id)
    assert held is None and detail.insights is None


async def test_the_column_refuses_a_value_that_is_not_a_reading() -> None:
    tenant_id, call_id = await _call_with_insights()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(IntegrityError, match="insights"):
            await session.execute(
                text("UPDATE calls SET insights = '[1]'::jsonb WHERE id = :id"), {"id": call_id}
            )
