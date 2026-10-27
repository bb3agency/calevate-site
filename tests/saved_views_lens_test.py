"""Saved views hold the whole lens, on the Leads table and the Calls log (D-893 L2).

A Leads view keeps the call filters (came in, last call, outcome, follow-up, call-back) as
well as stage, owner and facets, so applying it puts all of them back. A day range is fixed
days or "the last N days", answered with the days it covers on the day it is read. The Calls
log saves views in the same table under `screen = 'calls'`, private and tenant-isolated
like a Leads view.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from apps.api.billing.plans import IST
from apps.api.crm.schemas import CallViewFilters, SavedViewFilters, ViewDaysIn
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from tests.lead_columns_test import _tenant
from tests.lead_saved_views_test import _second_member

LEAD_VIEWS = "/v1/leads/views"
CALL_VIEWS = "/v1/calls/views"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


# ------------------------------------------------------------------ the day range


def test_a_rolling_range_drops_fixed_days_and_reads_as_the_last_n_days() -> None:
    span = ViewDaysIn(from_day=date(2026, 1, 1), to_day=date(2026, 1, 2), last_days=7)
    assert (span.from_day, span.to_day) == (None, None)
    assert span.days(date(2026, 10, 27)) == (date(2026, 10, 21), date(2026, 10, 27))


@pytest.mark.parametrize(
    "fields",
    [{}, {"from_day": "2026-10-20", "to_day": "2026-10-19"}, {"last_days": 0}],
)
def test_an_empty_backwards_or_zero_range_is_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ViewDaysIn.model_validate(fields)


def test_a_view_turns_into_the_lens_it_selects() -> None:
    today = date(2026, 10, 27)
    lead = SavedViewFilters.model_validate(
        {
            "status": "hot",
            "fields": {"budget": ["high", "mid"]},
            "created": {"last_days": 7},
            "last_call": {"from_day": "2026-10-01"},
            "last_outcome": "needs_you",
            "follow_up": "not_done",
            "callback_open": False,
            "test_calls": False,
        }
    ).lens(today)
    assert lead.created_from == date(2026, 10, 21) and lead.created_to == today
    assert lead.last_call_from == date(2026, 10, 1) and lead.last_call_to is None
    assert sorted(lead.f) == ["budget:high", "budget:mid"]
    assert (lead.follow_up, lead.callback_open, lead.test_calls) == ("not_done", False, False)

    call = CallViewFilters.model_validate({"when": {"last_days": 1}, "direction": "inbound"}).lens(
        today
    )
    assert (call.from_day, call.to_day, call.direction) == (today, today, "inbound")


# ------------------------------------------------------------------ Leads views


async def test_a_leads_view_stores_and_returns_every_lens_filter() -> None:
    t = await _tenant()
    body = {
        "name": "Missed this week",
        "filters": {
            "status": "new",
            "created": {"last_days": 7},
            "last_call": {"from_day": "2026-10-01", "to_day": "2026-10-10"},
            "last_outcome": "needs_you",
            "direction": "inbound",
            "test_calls": False,
            "callback_open": True,
            "follow_up": "not_done",
            "captured": [{"key": "city", "op": "contains", "value": "Hyd"}],
        },
    }
    async with _client() as http:
        created = await http.post(LEAD_VIEWS, json=body, headers=t.headers)
        listed = await http.get(LEAD_VIEWS, headers=t.headers)

    assert created.status_code == 201, created.text
    [view] = listed.json()["items"]
    filters = view["filters"]
    today = _today()
    # Rolling: stored as a count, read back with the days it covers today.
    assert filters["created"] == {
        "from_day": (today - timedelta(days=6)).isoformat(),
        "to_day": today.isoformat(),
        "last_days": 7,
    }
    assert filters["last_call"] == {
        "from_day": "2026-10-01",
        "to_day": "2026-10-10",
        "last_days": None,
    }
    assert filters["last_outcome"] == "needs_you"
    assert (filters["direction"], filters["test_calls"]) == ("inbound", False)
    assert (filters["callback_open"], filters["follow_up"]) == (True, "not_done")
    assert filters["captured"] == [{"key": "city", "op": "contains", "value": "Hyd"}]

    async with tenant_session(t.tenant_id) as session:
        stored = (
            await session.execute(text("SELECT filters -> 'created' FROM lead_saved_views"))
        ).scalar()
    assert stored == {"from_day": None, "to_day": None, "last_days": 7}, "kept as a count"


async def test_a_view_saved_before_the_call_filters_still_loads() -> None:
    t = await _tenant()
    async with _client() as http:
        created = await http.post(LEAD_VIEWS, json={"name": "Old"}, headers=t.headers)
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text('UPDATE lead_saved_views SET filters = \'{"status": "hot"}\'::jsonb')
        )
    async with _client() as http:
        listed = await http.get(LEAD_VIEWS, headers=t.headers)

    assert created.status_code == 201
    [view] = listed.json()["items"]
    assert view["filters"]["status"] == "hot"
    assert view["filters"]["created"] is None and view["filters"]["test_calls"] is True


# ------------------------------------------------------------------ Calls views


async def test_tenant_b_cannot_see_tenant_as_call_view() -> None:
    a = await _tenant()
    b = await _tenant()
    async with _client() as http:
        created = await http.post(
            CALL_VIEWS, json={"name": "Missed", "filters": {"outcome": "missed"}}, headers=a.headers
        )
        seen_by_b = await http.get(CALL_VIEWS, headers=b.headers)

    assert created.status_code == 201, created.text
    assert seen_by_b.json()["items"] == []
    async with tenant_session(b.tenant_id) as session:
        rows = (await session.execute(text("SELECT count(*) FROM lead_saved_views"))).scalar()
    assert rows == 0
    async with untenanted_session() as session:
        rows = (await session.execute(text("SELECT count(*) FROM lead_saved_views"))).scalar()
    assert rows == 0


async def test_call_views_keep_their_filters_and_stay_off_the_leads_screen() -> None:
    t = await _tenant()
    body = {
        "name": "Inbound today",
        "filters": {
            "direction": "inbound",
            "when": {"last_days": 1},
            "test_calls": False,
            "follow_up": "done",
            "callback_open": False,
        },
    }
    async with _client() as http:
        created = await http.post(CALL_VIEWS, json=body, headers=t.headers)
        # One name may exist on both screens.
        same_name = await http.post(LEAD_VIEWS, json={"name": "Inbound today"}, headers=t.headers)
        clash = await http.post(CALL_VIEWS, json={"name": "Inbound today"}, headers=t.headers)
        call_views = await http.get(CALL_VIEWS, headers=t.headers)
        lead_views = await http.get(LEAD_VIEWS, headers=t.headers)

    assert created.status_code == 201, created.text
    assert same_name.status_code == 201, same_name.text
    assert clash.status_code == 409
    [view] = call_views.json()["items"]
    today = _today().isoformat()
    assert view["filters"]["when"] == {"from_day": today, "to_day": today, "last_days": 1}
    assert view["filters"]["direction"] == "inbound"
    assert (view["filters"]["test_calls"], view["filters"]["follow_up"]) == (False, "done")
    assert [v["name"] for v in lead_views.json()["items"]] == ["Inbound today"]
    assert lead_views.json()["items"][0]["id"] != view["id"]


async def test_a_call_view_is_renamed_repinned_and_deleted_by_its_owner_only() -> None:
    t = await _tenant()
    colleague = await _second_member(t)
    theirs = {"Authorization": f"Bearer {colleague}", "X-Org-Slug": t.slug}
    async with _client() as http:
        created = await http.post(CALL_VIEWS, json={"name": "A"}, headers=t.headers)
        view_id = created.json()["id"]
        foreign = await http.patch(f"{CALL_VIEWS}/{view_id}", json={"name": "X"}, headers=theirs)
        # A Leads route cannot reach a Calls view either.
        cross_screen = await http.delete(f"{LEAD_VIEWS}/{view_id}", headers=t.headers)
        patched = await http.patch(
            f"{CALL_VIEWS}/{view_id}",
            json={"name": "B", "filters": {"outcome": "missed"}},
            headers=t.headers,
        )
        deleted = await http.delete(f"{CALL_VIEWS}/{view_id}", headers=t.headers)
        gone = await http.get(CALL_VIEWS, headers=t.headers)

    assert foreign.status_code == 404
    assert cross_screen.status_code == 404
    assert patched.status_code == 200, patched.text
    assert (patched.json()["name"], patched.json()["filters"]["outcome"]) == ("B", "missed")
    assert deleted.status_code == 204
    assert gone.json()["items"] == []


async def test_a_call_view_is_refused_an_unknown_filter() -> None:
    t = await _tenant()
    async with _client() as http:
        refused = await http.post(
            CALL_VIEWS,
            json={
                "name": "X",
                "filters": {"since": "2026-10-01T00:00:00Z", "id": str(uuid.uuid4())},
            },
            headers=t.headers,
        )
    assert refused.status_code == 422
