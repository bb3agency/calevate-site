"""`leads.first_call_id` reaches the wire — the call the relationship STARTED on.

It was one of `check_half_wired.WRITE_ONLY_BASELINE`'s dated deferrals: written by the
post-call upsert's INSERT arm (`apps/workers/pipeline.py`, whose `DO UPDATE` arm
deliberately never touches it, so it cannot drift forward) and read by nothing. The
registry said in so many words what closed it — "giving it a reader means adding a field
to `LeadOut` — a response-model change, which regenerates
`apps/web/src/lib/api/openapi.json`. Closes with that snapshot, in the change that adds
the field." This is that change, and this file is the part of it a reviewer cannot see
from the diff.

**WHY THE TWO IDS ARE DIFFERENT IN EVERY FIXTURE HERE.** `_lead_out` maps a positional
row onto `LeadOut` — `r[9]`, `r[10]`, … — so inserting a column into `_LEAD_COLUMNS`
shifts every field after it. A fixture whose first and last call were the same call would
pass against a projection that had swapped them, and one with no call ids at all would
pass against a projection that had shifted `created_at` into a call-id slot. Both are the
mistake this change could have made.

The assertions go through the HTTP surface rather than the service, because the deferral
was about the WIRE: a field on the Pydantic model that no route serialised would have
closed nothing.
"""

from __future__ import annotations

import uuid

import httpx
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _lead_with_two_calls(tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A repeat caller: `(lead_id, first_call_id, last_call_id)`, all distinct.

    The two call ids are plain UUID columns and not foreign keys (`crm/models.py`'s module
    docstring says so), so no `calls` rows are needed to state the fact under test.
    """
    lead_id, first_call_id, last_call_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "first_call_id, last_call_id, call_count, is_repeat_caller, created_at, "
                "updated_at) VALUES (:i, :t, :a, :p, 'Repeat Caller', 'inbound_call', 'new', "
                ":first, :last, 2, true, now(), now())"
            ),
            {
                "i": lead_id,
                "t": tenant_id,
                "a": agent_id,
                "p": f"+9197{uuid.uuid4().int % 100000000:08d}",
                "first": first_call_id,
                "last": last_call_id,
            },
        )
    return lead_id, first_call_id, last_call_id


async def test_the_lead_detail_names_the_call_the_lead_started_on() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id, first_call_id, last_call_id = await _lead_with_two_calls(tenant_id)

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}", headers=_headers(slug, token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_call_id"] == str(first_call_id)
    # The pair, asserted together: this is what a projection with a shifted index breaks,
    # and asserting either one alone would pass against a swap.
    assert body["last_call_id"] == str(last_call_id)


async def test_the_leads_list_carries_it_too() -> None:
    """The list and the detail select the SAME projection (`crm.service._LEAD_COLUMNS`),
    so a field that appeared on one and not the other would mean the projection had been
    forked — which is the defect `_LEAD_COLUMNS` exists to prevent."""
    tenant_id, slug, token = await _make_tenant()
    lead_id, first_call_id, last_call_id = await _lead_with_two_calls(tenant_id)

    async with _client() as http:
        response = await http.get("/v1/leads", headers=_headers(slug, token))

    assert response.status_code == 200, response.text
    # Found by id, not by position: a freshly minted account already carries the seeded
    # demo lead, and a positional assertion would be a test that passes for the wrong row.
    rows = [row for row in response.json()["items"] if row["id"] == str(lead_id)]
    assert len(rows) == 1, "the lead this test inserted is in its own account's list"
    assert rows[0]["first_call_id"] == str(first_call_id)
    assert rows[0]["last_call_id"] == str(last_call_id)


async def test_a_lead_no_call_created_reports_neither_id() -> None:
    """NULL is the honest answer for an imported or hand-entered lead, and it is the arm
    a positional shift turns into a `created_at` timestamp failing UUID validation."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, :p, 'Walk In', 'manual', 'new', "
                "now(), now())"
            ),
            {
                "i": lead_id,
                "t": tenant_id,
                "a": agent_id,
                "p": f"+9197{uuid.uuid4().int % 100000000:08d}",
            },
        )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}", headers=_headers(slug, token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_call_id"] is None
    assert body["last_call_id"] is None
