"""The Calls screen's filters (outcome, direction, date range) and its CSV export.

The export is the list the owner is looking at, with numbers in full: owner-only
(`calls:read_raw`), audited, refused for staff, and never another tenant's calls.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

pytestmark = [pytest.mark.rls]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _seed_calls(tenant_id: uuid.UUID) -> datetime:
    now = datetime.now(UTC).replace(microsecond=0)
    async with tenant_session(tenant_id) as s:
        agent_id = (await s.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        rows = (
            ("inbound", "answered", now - timedelta(hours=1), "+919800000001"),
            ("outbound", "needs_you", now - timedelta(days=2), "+919800000002"),
            ("inbound", "hung_up_early", now - timedelta(days=40), "+919800000003"),
        )
        for direction, outcome, started, number in rows:
            await s.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, outcome_tag, started_at, duration_s, from_e164, to_e164, "
                    "created_at, updated_at) VALUES (:id, :t, :a, :e, :d, 'completed', :o, "
                    ":s, 61, :frm, :to, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"exp-{uuid.uuid4().hex[:10]}",
                    "d": direction,
                    "o": outcome,
                    "s": started,
                    "frm": number if direction == "inbound" else "+918000000000",
                    "to": number if direction == "outbound" else "+918000000000",
                },
            )
    return now


async def test_the_list_narrows_by_outcome_direction_and_date() -> None:
    tenant_id, slug, token = await _make_tenant()
    now = await _seed_calls(tenant_id)
    async with _client() as http:
        by_outcome = await http.get("/v1/calls?outcome=needs_you", headers=_headers(slug, token))
        by_direction = await http.get("/v1/calls?direction=inbound", headers=_headers(slug, token))
        since = (now - timedelta(days=7)).isoformat()
        by_date = await http.get(
            "/v1/calls", params={"since": since}, headers=_headers(slug, token)
        )
    assert [c["outcome_tag"] for c in by_outcome.json()] == ["needs_you"]
    assert {c["direction"] for c in by_direction.json()} == {"inbound"}
    assert len(by_direction.json()) == 2
    assert len(by_date.json()) == 2, by_date.text


async def test_a_date_without_a_zone_is_refused_rather_than_guessed() -> None:
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        refused = await http.get(
            "/v1/calls", params={"since": "2026-10-10T00:00:00"}, headers=_headers(slug, token)
        )
    assert refused.status_code == 422
    assert refused.json()["type"].endswith("/call_filter_time_without_zone")


async def test_the_owner_exports_what_they_filtered_with_full_numbers_and_an_audit_row() -> None:
    tenant_id, slug, token = await _make_tenant()
    await _seed_calls(tenant_id)
    async with _client() as http:
        exported = await http.get(
            "/v1/calls/export.csv?direction=outbound", headers=_headers(slug, token)
        )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert rows[0][:3] == ["Started (India time)", "Direction", "Number"]
    assert len(rows) == 2
    assert rows[1][1] == "Outgoing"
    # The number arrives in full, tab-guarded so a spreadsheet keeps the leading +.
    assert rows[1][2].strip() == "+919800000002"
    async with tenant_session(tenant_id) as s:
        audited = (
            await s.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'calls.export' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert audited == 1


async def test_staff_cannot_export_calls() -> None:
    _tenant_id, slug, token = await _make_tenant(role="staff")
    async with _client() as http:
        refused = await http.get("/v1/calls/export.csv", headers=_headers(slug, token))
    assert refused.status_code == 403


async def test_a_neighbours_calls_never_reach_the_file() -> None:
    victim, _slug, _token = await _make_tenant()
    await _seed_calls(victim)
    _attacker, slug, token = await _make_tenant()
    async with _client() as http:
        exported = await http.get("/v1/calls/export.csv", headers=_headers(slug, token))
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert len(rows) == 1, "only the header: the neighbour's calls are invisible"


async def test_test_calls_can_be_left_out_and_a_row_names_its_lead() -> None:
    """The call log's "Include test calls" switch, and the lead's name beside its number."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as s:
        agent_id = (await s.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await s.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, '+919800000009', 'Lakshmi', "
                "'inbound_call', 'new', '{}'::jsonb, now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id},
        )
        for trial, lead in ((True, None), (False, lead_id)):
            await s.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, started_at, duration_s, from_e164, to_e164, trial_call, lead_id, "
                    "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', "
                    "now(), 30, '+919800000009', '+918000000000', :trial, :lead, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"tc-{uuid.uuid4().hex[:10]}",
                    "trial": trial,
                    "lead": lead,
                },
            )
    async with _client() as http:
        everything = await http.get("/v1/calls", headers=_headers(slug, token))
        real_only = await http.get(
            "/v1/calls", params={"test_calls": "false"}, headers=_headers(slug, token)
        )
        exported = await http.get(
            "/v1/calls/export.csv", params={"test_calls": "false"}, headers=_headers(slug, token)
        )
    assert sorted(c["test_call"] for c in everything.json()) == [False, True]
    assert [c["test_call"] for c in real_only.json()] == [False]
    assert real_only.json()[0]["lead_name"] == "Lakshmi"
    assert len(list(csv.reader(io.StringIO(exported.text)))) == 2


async def test_the_list_narrows_to_one_agent() -> None:
    """The agent page links to the call log with `?agent_id=`; the list and the file honour it."""
    tenant_id, slug, token = await _make_tenant()
    await _seed_calls(tenant_id)
    async with tenant_session(tenant_id) as s:
        agent_id = (await s.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
    other = uuid.uuid4()
    async with _client() as http:
        mine = await http.get(
            "/v1/calls", params={"agent_id": str(agent_id)}, headers=_headers(slug, token)
        )
        nobody = await http.get(
            "/v1/calls", params={"agent_id": str(other)}, headers=_headers(slug, token)
        )
        exported = await http.get(
            "/v1/calls/export.csv", params={"agent_id": str(other)}, headers=_headers(slug, token)
        )
    assert len(mine.json()) == 3
    assert {c["agent_id"] for c in mine.json()} == {str(agent_id)}
    assert nobody.json() == []
    assert len(list(csv.reader(io.StringIO(exported.text)))) == 1
