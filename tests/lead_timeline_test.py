"""`GET /v1/leads/{id}/timeline` — the record that existed and nobody could read.

`lead_events` is written by six producers across three deployables and, until this
slice, was read only in aggregate by the needs-attention queue. "We called them twice,
the WhatsApp was refused, the campaign gave up" was on record and invisible to the
person it is about.

The claims under test, in falling order of what they cost if wrong:

1. **The payload is PROJECTED, never serialized.** `lead_events.payload` is schemaless
   JSONB. Today's six producers store ids, authored codes and counters — the audit is
   written out key by key above `crm.service.lead_timeline` — but the read has to hold
   hard rules 5 and 6 for the SEVENTH producer too. So the test below plants a phone
   number, a transcript line and an extraction blob in a payload and requires that none
   of it reaches the response. That is the only version of this test worth having:
   asserting against today's well-behaved writers would pass against an implementation
   that passed the blob straight through.
2. **A refusal is not an empty timeline.** Another tenant's lead id is a 404, the same
   answer a lead that never existed gets.
3. **The numbers describe the SET, not the page** (BUILD-LOG §52).
4. **The read is a READ.** D-22 makes "view as client" read-only by refusing every
   MUTATING permission, so a history gated on `leads:write` would be invisible to
   support at the exact moment support is looking. `tests/impersonation_reads_test.py`
   asserts that rule over the whole route table; this file walks the impersonating
   session through the actual endpoint.

CONCURRENCY: every test mints its own organization and reads only through it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import httpx
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.lead_assignment_test import (
    _colleague,
    _headers,
    _name_the_member,
    _the_lead,
    _the_member,
)

# A full E.164 number, a transcript line and an extraction payload — the three things
# hard rules 5 and 6 name. None of them may come back out of the timeline.
PLANTED_PHONE = "+919876543210"
PLANTED_TRANSCRIPT = "Caller said their Aadhaar is 4321 8765 0987"


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _event(
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    *,
    event_type: str,
    payload: dict[str, object],
    actor: str = "system",
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:i, :t, :l, :ty, CAST(:p AS jsonb), :a, "
                "now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "l": lead_id,
                "ty": event_type,
                "p": json.dumps(payload),
                "a": actor,
            },
        )


# --- redaction: the whole reason this is a projection --------------------------


async def test_a_payload_carrying_pii_reaches_no_part_of_the_response() -> None:
    """The seventh producer, simulated.

    Every key below is one a real producer already writes BESIDE (`rule` beside `kind`,
    `call_id` beside `status`), plus three that carry exactly what hard rules 5 and 6
    forbid. A read that serialized `payload` — or that whitelisted keys but passed their
    values through — fails here; the projection passes because it composes its own prose
    and admits only values shaped like our own ids and authored codes.
    """
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    await _event(
        tenant_id,
        lead_id,
        event_type="note",
        payload={
            "kind": "blocked",
            "rule": "dnc",
            # The three forbidden shapes.
            "phone_e164": PLANTED_PHONE,
            "transcript": PLANTED_TRANSCRIPT,
            "extraction": {"budget": "45 lakh", "caller_name": "Ramesh Kumar"},
        },
    )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))

    assert response.status_code == 200, response.text
    body = response.text
    assert PLANTED_PHONE not in body
    # Not merely the formatted string: the digits in sequence are what identify the
    # person, and a partial leak is still a leak.
    assert "9876543210" not in body
    assert "Aadhaar" not in body
    assert "45 lakh" not in body
    assert "Ramesh Kumar" not in body
    # …while the row itself is still there, in the client's own words.
    item = response.json()["items"][0]
    assert item["title"] == "Call blocked"
    assert "asked not to be called" in item["detail"], "the remedy the attention queue uses"


async def test_a_reason_that_is_prose_rather_than_a_code_is_dropped() -> None:
    """`SendResult.reason` promises an AUTHORED code and says why ("never vendor prose —
    a provider error string is untrusted text that may quote the payload we just sent
    it"). `_code` is the gate that survives the day a producer forgets."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    await _event(
        tenant_id,
        lead_id,
        event_type="notification",
        payload={
            "channel": "whatsapp",
            "delivered": False,
            "attempts": 3,
            "reason": f"Meta rejected message to {PLANTED_PHONE}: template mismatch",
        },
    )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))

    assert PLANTED_PHONE not in response.text
    assert "Meta rejected" not in response.text
    item = response.json()["items"][0]
    assert item["title"] == "Hot-lead alert not sent by WhatsApp"
    assert item["detail"] == "We could not deliver it after 3 attempt(s)."


async def test_an_authored_reason_code_is_kept_because_it_is_actionable() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    await _event(
        tenant_id,
        lead_id,
        event_type="notification",
        payload={
            "channel": "whatsapp",
            "kind": "campaign_escalation",
            "delivered": False,
            "attempts": 2,
            "reason": "recipient_not_opted_in",
        },
    )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))
    item = response.json()["items"][0]
    assert item["title"] == "Follow-up message not sent by WhatsApp"
    assert "recipient_not_opted_in" in item["detail"]


async def test_the_engine_handle_stays_inside_the_engine_boundary() -> None:
    """`ingest.service._timeline` stores the ENGINE's id for the dial. It is a vendor
    identifier (hard rule 2), so the projection reads the row and emits our own line
    instead of the handle."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    await _event(
        tenant_id,
        lead_id,
        event_type="call",
        payload={"kind": "call", "engine_call_id": "bolna_exec_9f2c11"},
    )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))
    assert "bolna_exec_9f2c11" not in response.text
    item = response.json()["items"][0]
    assert item["title"] == "Call placed"
    assert item["call_id"] is None


# --- what the timeline says ----------------------------------------------------


async def test_the_history_reads_newest_first_and_names_who_did_it() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)
    await _name_the_member(member, "Priya Nair")
    call_id = uuid.uuid4()

    await _event(
        tenant_id,
        lead_id,
        event_type="call",
        payload={"call_id": str(call_id), "status": "completed"},
    )
    async with _client() as http:
        await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"status": "hot", "assigned_to": str(member)},
        )
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))

    body = response.json()
    assert body["total"] == 3
    titles = [item["title"] for item in body["items"]]
    # Newest first, and the call — written before the PATCH — is last.
    assert titles[-1] == "Call completed"
    assert set(titles[:2]) == {"Moved to hot", "Assigned to Priya Nair"}

    call_line = body["items"][-1]
    assert call_line["actor_kind"] == "system"
    assert call_line["actor_name"] is None
    assert call_line["call_id"] == str(call_id)

    human = next(item for item in body["items"] if item["title"] == "Moved to hot")
    assert human["actor_kind"] == "member"
    assert human["actor_name"] == "Priya Nair", "'who moved this to won?' is the point"


async def test_an_unassignment_reads_as_an_event_rather_than_as_a_gap() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)

    async with _client() as http:
        await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(member)},
        )
        await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"assigned_to": None}
        )
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))

    assert response.json()["items"][0]["title"] == "Owner removed"


async def test_an_owner_who_left_the_account_is_not_named_from_the_global_users_table() -> None:
    """`users` has no RLS. Naming an assignee through it would print a stranger; the
    resolution goes through `memberships`, so a person this tenant can no longer see
    reads as one."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    other_tenant, _, _ = await _make_tenant()
    stranger = await _the_member(other_tenant)
    await _name_the_member(stranger, "Somebody Else")
    # Written straight to the row: the API refuses this assignment (see
    # `lead_assignment_test`), so the only way to reach the "cannot name them" branch is
    # to put the state there — which is also what a removed membership leaves behind.
    await _event(
        tenant_id, lead_id, event_type="assignment", payload={"assigned_to": str(stranger)}
    )

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))

    assert "Somebody Else" not in response.text
    item = response.json()["items"][0]
    assert item["title"] == "Assigned"
    assert item["detail"] == "The owner is no longer on this account."


def test_a_type_this_build_does_not_know_still_reaches_the_screen() -> None:
    """A deploy sitting behind its own migration must not delete a client's history.

    Asserted against the projection and the response model directly rather than through
    a planted row: reaching the branch through the API would need the CHECK constraint
    dropped, and the app role is deliberately not the table owner — nor would a suite
    sharing this database be entitled to unconstrain a table for the duration.

    Both halves matter and only one of them is the projection's. The FIRST is that
    `_project_event` composes a neutral line rather than raising; the SECOND is that
    `LeadTimelineEventOut.type` is a plain `str`, so `extra="forbid"` does not turn one
    unfamiliar row into a 500 that takes the whole page with it.
    """
    from apps.api.crm.schemas import LeadTimelineEventOut
    from apps.api.crm.service import _project_event

    title, detail, call_id = _project_event("merge", {"leads": ["x", "y"]}, {})
    assert (title, detail, call_id) == ("Activity", None, None)

    event = LeadTimelineEventOut(
        id=uuid7(),
        type="merge",
        occurred_at=datetime.now(UTC),
        actor_kind="system",
        title=title,
    )
    assert event.type == "merge"


# --- the numbers, the bound, and the refusals ----------------------------------


async def test_total_counts_the_set_and_items_counts_the_page() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    for index in range(7):
        await _event(
            tenant_id,
            lead_id,
            event_type="status_change",
            payload={"status": "contacted"},
            actor="system",
        )
        assert index >= 0

    async with _client() as http:
        response = await http.get(
            f"/v1/leads/{lead_id}/timeline?limit=3", headers=_headers(slug, token)
        )
    body = response.json()
    assert len(body["items"]) == 3
    # The number that would be 3 if somebody counted the page — the shape §52 records
    # four separate defects for.
    assert body["total"] == 7
    assert body["limit"] == 3 and body["offset"] == 0


async def test_an_empty_timeline_is_a_200_and_a_missing_lead_is_a_404() -> None:
    """The two states a screen must render differently, told apart by the server first."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    assert tenant_id

    async with _client() as http:
        empty = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))
        missing = await http.get(
            f"/v1/leads/{uuid.uuid4()}/timeline", headers=_headers(slug, token)
        )
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")


async def test_another_tenants_lead_is_a_404_and_not_an_empty_history() -> None:
    """Under RLS "not found" and "belongs to somebody else" are deliberately the same
    answer. An empty 200 would be worse than a leak of the id: it would tell the caller
    the lead exists."""
    _tenant_a, slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    their_lead = await _the_lead(tenant_b)
    await _event(tenant_b, their_lead, event_type="status_change", payload={"status": "won"})

    async with _client() as http:
        response = await http.get(
            f"/v1/leads/{their_lead}/timeline", headers=_headers(slug_a, token_a)
        )
    assert response.status_code == 404
    assert "won" not in response.text


async def test_the_limit_is_validated_rather_than_clamped() -> None:
    """`min(limit, 100)` turns a negative limit into a silently short page; the route
    validates instead, exactly as `/v1/attention` argues for itself."""
    _tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(_tenant_id)
    async with _client() as http:
        too_many = await http.get(
            f"/v1/leads/{lead_id}/timeline?limit=500", headers=_headers(slug, token)
        )
        negative = await http.get(
            f"/v1/leads/{lead_id}/timeline?limit=-1", headers=_headers(slug, token)
        )
    assert too_many.status_code == 422
    assert negative.status_code == 422


async def test_staff_can_read_a_timeline_because_it_is_a_read() -> None:
    _tenant_id, slug, token = await _make_tenant(role="staff")
    lead_id = await _the_lead(_tenant_id)
    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))
    assert response.status_code == 200


async def test_a_read_only_impersonating_admin_can_read_the_timeline() -> None:
    """D-22's other side, walked through the live endpoint rather than asserted off the
    route table: support opens a client's screen precisely when something has gone
    wrong, and the lead's history is the thing that says what."""
    tenant_id, slug, _token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    await _event(tenant_id, lead_id, event_type="status_change", payload={"status": "hot"})

    admin_clerk = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:i, :c, 'Ops', 'operator', now(), now())"
            ),
            {"i": uuid.uuid4(), "c": admin_clerk},
        )

    async with _client() as http:
        response = await http.get(
            f"/v1/leads/{lead_id}/timeline",
            headers={
                "Authorization": f"Bearer dev:admin:{admin_clerk}",
                "X-Org-Slug": slug,
                "X-Impersonate-Org": slug,
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["title"] == "Moved to hot"


async def test_the_actor_of_a_colleagues_edit_is_named_for_everyone_on_the_team() -> None:
    """A staff member reading the timeline must see who acted, not a UUID and not a
    blank — the column is the answer to "who gave this to me"."""
    tenant_id, owner_slug, owner_token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    owner = await _the_member(tenant_id)
    await _name_the_member(owner, "Anitha Rao")
    mate = await _colleague(tenant_id, "Kiran Babu")

    async with _client() as http:
        await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(owner_slug, owner_token),
            json={"assigned_to": str(mate)},
        )
        response = await http.get(
            f"/v1/leads/{lead_id}/timeline", headers=_headers(owner_slug, owner_token)
        )

    item = response.json()["items"][0]
    assert item["title"] == "Assigned to Kiran Babu"
    assert item["actor_name"] == "Anitha Rao"
