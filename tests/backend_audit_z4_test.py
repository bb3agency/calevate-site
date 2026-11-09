"""Backend audit 10 Nov 2026, lane Z4 (after the call): the home screen's missed-calls link
opens on exactly the calls it counted, and "no test calls" leaves out a paying account's
test calls as the dashboard does."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from apps.api.crm import lens
from apps.api.crm.service import DAILY_CALL_CLASSES, dashboard
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return uuid.UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar())
        )


async def _call(
    tenant_id: uuid.UUID,
    *,
    status: str,
    started: bool = True,
    trial: bool = False,
    paid_test: bool = False,
    lead_id: uuid.UUID | None = None,
) -> uuid.UUID:
    call_id = uuid.uuid4()
    now = datetime.now(UTC) - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at, trial_call, paid_test_call, lead_id) "
                "VALUES (:id, :t, :a, :e, 'outbound', :s, :st, :at, :at, :trial, :paid, :l)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": await _agent(tenant_id),
                "e": f"z4-{uuid.uuid4().hex}",
                "s": status,
                "st": now if started else None,
                "at": now,
                "trial": trial,
                "paid": paid_test,
                "l": lead_id,
            },
        )
        if lead_id is not None:
            await session.execute(
                text("UPDATE leads SET last_call_id = :c WHERE id = :l"),
                {"c": call_id, "l": lead_id},
            )
    return call_id


def test_the_missed_group_is_the_dashboards_missed_count() -> None:
    assert sorted(lens.CALL_STATUS_GROUPS["missed"]) == sorted(
        [*DAILY_CALL_CLASSES["no_answer"], *DAILY_CALL_CLASSES["failed"]]
    )


async def test_the_missed_link_lists_exactly_the_calls_the_home_screen_counted() -> None:
    tenant_id, slug, token = await _make_tenant()
    missed = {
        await _call(tenant_id, status="no_answer"),
        await _call(tenant_id, status="busy"),
        await _call(tenant_id, status="voicemail"),
        await _call(tenant_id, status="failed"),
        # A dial that never rang: no `started_at`. It is a missed call today on both sides.
        await _call(tenant_id, status="failed", started=False),
    }
    await _call(tenant_id, status="completed")
    await _call(tenant_id, status="no_answer", trial=True)
    await _call(tenant_id, status="no_answer", paid_test=True)

    async with tenant_session(tenant_id) as session:
        today = (await dashboard(session)).daily_7d[-1]
    counted = today.failed + today.no_answer
    assert counted == len(missed)

    async with _client() as client:
        listed = await client.get(
            "/v1/calls",
            params={
                "status": "missed",
                "test_calls": "false",
                "since": _ist_midnight(),
                "limit": 200,
            },
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert listed.status_code == 200, listed.text
    assert {uuid.UUID(row["id"]) for row in listed.json()} == missed


async def test_no_test_calls_leaves_out_a_paying_accounts_test_calls() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    real = await _call(tenant_id, status="completed")
    await _call(tenant_id, status="completed", paid_test=True)
    await _call(tenant_id, status="completed", trial=True)
    async with tenant_session(tenant_id) as session:
        ids = await lens.call_ids(session, lens.CallFilters(test_calls=False))
    assert ids == [real]


async def test_no_test_calls_leaves_out_leads_whose_latest_call_was_a_paid_test() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    leads: dict[str, uuid.UUID] = {}
    async with tenant_session(tenant_id) as session:
        for name in ("real", "paid_test"):
            leads[name] = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, data, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, "
                    "'manual', 'new', '{}'::jsonb, now(), now())"
                ),
                {
                    "i": leads[name],
                    "t": tenant_id,
                    "a": agent_id,
                    "p": f"+9197{uuid.uuid4().int % 100000000:08d}",
                    "n": name,
                },
            )
    await _call(tenant_id, status="completed", lead_id=leads["real"])
    await _call(tenant_id, status="completed", paid_test=True, lead_id=leads["paid_test"])
    params: dict[str, object] = {}
    clauses = lens.lead_row_clauses(lens.LeadRowFilters(test_calls=False), params)
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text(f"SELECT l.id FROM leads l WHERE {' AND '.join(clauses)}"), params
        )
        found = {uuid.UUID(str(r[0])) for r in rows.all()}
    # `_make_tenant` seeds a lead of its own with no calls; it stays in either way.
    assert leads["real"] in found
    assert leads["paid_test"] not in found


def _ist_midnight() -> str:
    """Today 00:00 in India, as the Calls screen's `day=` link sends it."""
    day = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
    return f"{day.isoformat()}T00:00:00+05:30"
