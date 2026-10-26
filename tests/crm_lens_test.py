"""The one definition of which leads and which calls (D-893 F2, `crm/lens.py`).

Each predicate is proved against rows on a real database (RLS on, a tenant of its own), and
then through the routes that read it: the Leads table, its export, the Calls log and Pip's
`leads_find` / `calls_find`. Dates are India days.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from apps.api.copilot import tools as copilot_tools
from apps.api.copilot.tools import ToolContext
from apps.api.core.errors import ProblemError
from apps.api.crm import lens
from apps.api.crm.schemas import CallLensIn, CapturedFieldFilterIn, LeadLensIn
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return uuid.UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar())
        )


async def _lead(
    tenant_id: uuid.UUID,
    *,
    name: str,
    created_at: datetime,
    data: dict[str, str] | None = None,
    status: str = "new",
) -> uuid.UUID:
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, 'manual', :s, "
                "CAST(:d AS jsonb), :c, :c)"
            ),
            {
                "i": lead_id,
                "t": tenant_id,
                "a": await _agent(tenant_id),
                "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
                "n": name,
                "s": status,
                "d": json.dumps(data or {}),
                "c": created_at,
            },
        )
    return lead_id


async def _call(
    tenant_id: uuid.UUID,
    *,
    lead_id: uuid.UUID | None,
    at: datetime,
    direction: str = "inbound",
    outcome: str | None = "answered",
    trial: bool = False,
    follow_up: str | None = None,
) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at, lead_id, outcome_tag, trial_call, "
                "follow_up_state) VALUES (:id, :t, :a, :e, :d, 'completed', :at, :at, :at, "
                ":l, :o, :trial, :f)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": await _agent(tenant_id),
                "e": f"lens-{uuid.uuid4().hex}",
                "d": direction,
                "at": at,
                "l": lead_id,
                "o": outcome,
                "trial": trial,
                "f": follow_up,
            },
        )
        if lead_id is not None:
            await session.execute(
                text("UPDATE leads SET last_call_id = :c WHERE id = :l"),
                {"c": call_id, "l": lead_id},
            )
    return call_id


async def _open_callback(tenant_id: uuid.UUID, lead_id: uuid.UUID, call_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO scheduled_callbacks (id, tenant_id, agent_id, source_call_id, "
                "source_execution_id, lead_id, phone_e164, requested_at, booked_at) "
                "VALUES (:id, :t, :a, :c, :ex, :l, '+919000001111', now() + interval '1 day', "
                "now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "a": await _agent(tenant_id),
                "c": call_id,
                "ex": f"ex-{uuid.uuid4().hex}",
                "l": lead_id,
            },
        )


def _ist(day: date, hour: int) -> datetime:
    return lens.day_start(day) + timedelta(hours=hour)


async def _ids(tenant_id: uuid.UUID, lens_in: LeadLensIn) -> set[uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        scope = await lens.resolve_lead_scope(session, lens_in)
        return set(await lens.lead_ids(session, scope))


@pytest.fixture
async def world() -> dict[str, object]:
    tenant_id, slug, token = await _make_tenant()
    monday = date(2026, 10, 19)
    old = await _lead(tenant_id, name="Old", created_at=_ist(monday - timedelta(days=10), 10))
    # 23:30 IST on Monday is 18:00 UTC: an India day, not a UTC one.
    late_monday = await _lead(
        tenant_id, name="Late", created_at=_ist(monday, 23).replace(minute=30)
    )
    tuesday = await _lead(
        tenant_id,
        name="Tue",
        created_at=_ist(monday + timedelta(days=1), 9),
        data={"city": "Gachibowli East", "budget": "40L"},
    )
    missed_call = await _call(
        tenant_id, lead_id=old, at=_ist(monday, 11), outcome="missed", follow_up="needs_you"
    )
    await _call(
        tenant_id,
        lead_id=late_monday,
        at=_ist(monday, 23),
        direction="outbound",
        follow_up="resolved",
    )
    await _call(tenant_id, lead_id=tuesday, at=_ist(monday + timedelta(days=1), 10), trial=True)
    await _open_callback(tenant_id, old, missed_call)
    return {
        "slug": slug,
        "tenant": tenant_id,
        "token": token,
        "monday": monday,
        "old": old,
        "late": late_monday,
        "tue": tuesday,
        "missed_call": missed_call,
    }


async def test_created_days_are_india_days(world: dict[str, object]) -> None:
    tenant, monday = world["tenant"], world["monday"]
    assert isinstance(tenant, uuid.UUID) and isinstance(monday, date)
    found = await _ids(tenant, LeadLensIn(created_from=monday, created_to=monday))
    assert found == {world["late"]}
    tuesday = monday + timedelta(days=1)
    found = await _ids(tenant, LeadLensIn(created_from=monday, created_to=tuesday))
    assert found == {world["late"], world["tue"]}


async def test_latest_call_outcome_direction_and_days(world: dict[str, object]) -> None:
    tenant, monday = world["tenant"], world["monday"]
    assert isinstance(tenant, uuid.UUID) and isinstance(monday, date)
    assert await _ids(tenant, LeadLensIn(last_outcome="missed")) == {world["old"]}
    assert await _ids(tenant, LeadLensIn(direction="outbound")) == {world["late"]}
    found = await _ids(tenant, LeadLensIn(last_call_from=monday, last_call_to=monday))
    assert found == {world["old"], world["late"]}


async def test_test_calls_follow_up_and_open_callback(world: dict[str, object]) -> None:
    tenant = world["tenant"]
    assert isinstance(tenant, uuid.UUID)
    assert world["tue"] not in await _ids(tenant, LeadLensIn(test_calls=False))
    assert world["tue"] in await _ids(tenant, LeadLensIn())
    assert await _ids(tenant, LeadLensIn(follow_up="done")) == {world["late"]}
    assert world["late"] not in await _ids(tenant, LeadLensIn(follow_up="not_done"))
    assert await _ids(tenant, LeadLensIn(callback_open=True)) == {world["old"]}
    assert world["old"] not in await _ids(tenant, LeadLensIn(callback_open=False))


async def test_captured_text_equals_and_contains_as_bound_values(
    world: dict[str, object],
) -> None:
    tenant = world["tenant"]
    assert isinstance(tenant, uuid.UUID)
    contains = CapturedFieldFilterIn(key="city", op="contains", value="gachi")
    assert await _ids(tenant, LeadLensIn(captured=[contains])) == {world["tue"]}
    equals = CapturedFieldFilterIn(key="budget", op="equals", value="40l")
    assert await _ids(tenant, LeadLensIn(captured=[equals])) == {world["tue"]}
    # A value that would be SQL if interpolated matches nothing and breaks nothing.
    hostile = CapturedFieldFilterIn(key="city", op="contains", value="' OR 1=1 --")
    assert await _ids(tenant, LeadLensIn(captured=[hostile])) == set()
    # A LIKE wildcard in the value is a character, not a wildcard.
    wildcard = CapturedFieldFilterIn(key="city", op="contains", value="%")
    assert await _ids(tenant, LeadLensIn(captured=[wildcard])) == set()


async def test_a_backwards_range_and_a_question_are_refused(world: dict[str, object]) -> None:
    tenant, monday = world["tenant"], world["monday"]
    assert isinstance(tenant, uuid.UUID) and isinstance(monday, date)
    with pytest.raises(ProblemError) as backwards:
        await _ids(tenant, LeadLensIn(created_from=monday, created_to=monday - timedelta(days=1)))
    assert backwards.value.code == "lens_dates_backwards"
    with pytest.raises(ProblemError) as asked:
        await _ids(tenant, LeadLensIn(ask="who wanted delivery"))
    assert asked.value.code == "lens_ask_not_a_set"


async def test_another_tenants_rows_never_match(world: dict[str, object]) -> None:
    other, _, _ = await _make_tenant()
    assert await _ids(other, LeadLensIn(last_outcome="missed")) == set()


async def test_the_call_lens_reads_follow_up_callbacks_and_india_days(
    world: dict[str, object],
) -> None:
    tenant, monday = world["tenant"], world["monday"]
    assert isinstance(tenant, uuid.UUID) and isinstance(monday, date)
    async with tenant_session(tenant) as session:
        monday_calls = await lens.call_ids(
            session, lens.call_filters(CallLensIn(from_day=monday, to_day=monday))
        )
        waiting = await lens.call_ids(session, lens.call_filters(CallLensIn(callback_open=True)))
        done = await lens.count_calls(session, lens.call_filters(CallLensIn(follow_up="done")))
        real = await lens.count_calls(session, lens.call_filters(CallLensIn(test_calls=False)))
    assert len(monday_calls) == 2
    assert waiting == [world["missed_call"]]
    assert done == 1
    assert real == 2


async def test_the_leads_table_export_and_calls_log_read_the_lens(
    world: dict[str, object],
) -> None:
    slug, token, monday = world["slug"], world["token"], world["monday"]
    assert isinstance(slug, str) and isinstance(token, str) and isinstance(monday, date)
    async with _client() as client:
        page = await client.post(
            "/v1/leads/search",
            json={"last_outcome": "missed", "callback_open": True},
            headers=_headers(slug, token),
        )
        assert page.status_code == 200, page.text
        assert [item["id"] for item in page.json()["items"]] == [str(world["old"])]
        calls = await client.get(
            "/v1/calls", params={"follow_up": "done"}, headers=_headers(slug, token)
        )
        assert calls.status_code == 200, calls.text
        assert len(calls.json()) == 1
        refused = await client.post(
            "/v1/leads/search",
            json={"created_from": "2026-10-20", "created_to": "2026-10-19"},
            headers=_headers(slug, token),
        )
        assert refused.status_code == 422
        assert refused.json()["type"].endswith("/lens_dates_backwards")


async def test_pip_reads_a_count_a_few_examples_and_the_lens_handle(
    world: dict[str, object],
) -> None:
    tenant, monday = world["tenant"], world["monday"]
    assert isinstance(tenant, uuid.UUID) and isinstance(monday, date)
    context = ToolContext(tenant_id=tenant, role="owner")
    answer = await copilot_tools.run_read_tool(
        "leads_search",
        json.dumps(
            {
                "status": None,
                "search": None,
                "limit": None,
                "lens": {"created_from": "2026-10-19", "created_to": "2026-10-20"},
                "detail": None,
            }
        ),
        context=context,
    )
    assert answer.startswith("2 lead(s) match these filters")
    assert 'pass lens {"created_from":"2026-10-19","created_to":"2026-10-20"} to' in answer
    calls = await copilot_tools.run_read_tool(
        "calls_recent",
        json.dumps({"status": None, "limit": None, "lens": {"follow_up": "done"}, "detail": None}),
        context=context,
    )
    assert 'pass lens {"follow_up":"done"} to the action' in calls
    bad = await copilot_tools.run_read_tool(
        "leads_search",
        json.dumps(
            {
                "status": None,
                "search": None,
                "limit": None,
                "lens": {"created_from": "last week"},
                "detail": None,
            }
        ),
        context=context,
    )
    assert bad.startswith("Not looked up: `lens.created_from`")


def test_the_lens_names_itself_for_a_plan_card() -> None:
    described = lens.describe_lead_lens(
        LeadLensIn(status="hot", last_outcome="missed", callback_open=False)
    )
    assert described == "leads stage hot, last call missed, no call-back waiting"
    assert lens.describe_lead_lens(LeadLensIn()) == "every lead"


def test_india_day_bounds() -> None:
    start = lens.day_start(date(2026, 10, 19))
    assert start.astimezone(UTC) == datetime(2026, 10, 18, 18, 30, tzinfo=UTC)
    assert lens.day_after(date(2026, 10, 19)) - start == timedelta(days=1)
