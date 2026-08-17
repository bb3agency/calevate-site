"""Security-critical API behaviour: auth, tenancy, redaction, impersonation.

These are the tests that would have to fail before a cross-tenant leak, a PII leak or
an unguarded endpoint could ship. Suffix `_security_test` per BACKEND-PATTERNS §9.
"""

from __future__ import annotations

import json
import uuid

import pytest
from apps.api.core.rbac import MissingPolicyError, assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

CLINIC_SCHEMA = [
    {"key": "intent", "label": "Intent", "type": "text", "description": "what they want"}
]


async def _make_tenant(role: str = "owner") -> tuple[uuid.UUID, str, str]:
    """Returns (tenant_id, slug, dev bearer token) for a fresh org with one member."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    slug = f"t-{tenant_id.hex[:10]}"

    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": slug},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, created_at, "
                "updated_at) VALUES (:id, :tid, 'Reception', 'inbound', 'Idi AI assistant.', 'Idi "
                "AI assistant.', 'This call is being recorded.', 'live', 'fake', now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, 1, CAST(:f AS jsonb), now(), "
                "now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "aid": agent_id,
                "f": json.dumps(CLINIC_SCHEMA),
            },
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :phone, 'Ravi', "
                "'inbound_call', 'new', now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "aid": agent_id,
                "phone": f"+9198{uuid.uuid4().int % 100000000:08d}",
            },
        )
    return tenant_id, slug, f"dev:client:{user_id}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_unauthenticated_request_gets_problem_json_not_a_stack_trace() -> None:
    async with _client() as http:
        response = await http.get("/v1/leads")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["kind"] == "auth"
    assert body["retryable"] is False
    assert "trace_id" in body


async def test_the_dashboard_route_answers_over_http_for_the_session_tenant() -> None:
    """The route body, not just the service function underneath it.

    Five test modules exercise `crm.service.dashboard` directly and none of them went
    through the router, so `crm/routes.py:get_dashboard` was an uncovered line on a
    hard-rule-5 surface — the coverage ratchet's `dial-path` area named it and this is
    the answer. The gap matters beyond the count: the service takes a tenant-scoped
    session and derives the tenant from `app.tenant_id` (`db.session.session_tenant`),
    so everything about whether the RIGHT tenant is answered for lives in the dependency
    chain this test is the only thing to run — a direct call passes its own session and
    proves nothing about it.

    Two tenants, because "answers" and "answers about the caller" are different claims
    and one tenant cannot tell them apart.
    """
    tenant_a, slug_a, token_a = await _make_tenant()
    _, slug_b, token_b = await _make_tenant()

    async with _client() as http:
        a = await http.get(
            "/v1/dashboard",
            headers={"Authorization": f"Bearer {token_a}", "X-Org-Slug": slug_a},
        )
        b = await http.get(
            "/v1/dashboard",
            headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b},
        )

    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    body = a.json()
    # `_make_tenant` inserts one lead and no calls, so the numbers are decidable rather
    # than merely present — a test that only asserted the keys would pass on a handler
    # returning a zeroed model for the wrong tenant.
    assert body["leads_new_7d"] == 1
    assert body["calls_today"] == 0
    assert len(body["daily_7d"]) == 7, "the server zero-fills the week (crm/schemas.py)"
    # Required on the wire now, not defaulted: this field lost its `| None` when
    # `read_spend_counters` made "no row this month" a real zero, and a nullable field
    # the server never nulls is a branch every consumer writes and no test can reach.
    assert body["minutes_used_month"] == "0"
    # Hard rule 6: the dashboard is aggregate counts. No phone number may ride along.
    assert "+91" not in a.text

    # Tenant B's own answer, from the same handler, scoped by its own session.
    assert b.json()["leads_new_7d"] == 1
    assert tenant_a is not None


async def test_each_tenant_sees_only_its_own_leads_through_the_api() -> None:
    """The RLS test proves the database isolates; this proves the API does not undo it."""
    _, slug_a, token_a = await _make_tenant()
    _, slug_b, token_b = await _make_tenant()

    async with _client() as http:
        a = await http.get(
            "/v1/leads", headers={"Authorization": f"Bearer {token_a}", "X-Org-Slug": slug_a}
        )
        b = await http.get(
            "/v1/leads", headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b}
        )
    assert a.status_code == 200 and b.status_code == 200
    a_ids = {item["id"] for item in a.json()["items"]}
    b_ids = {item["id"] for item in b.json()["items"]}
    assert a_ids and b_ids
    assert a_ids.isdisjoint(b_ids), "no lead may appear in two tenants' lists"


async def test_a_member_cannot_borrow_another_orgs_slug() -> None:
    """Naming someone else's org in the header must be a 403, not a data leak."""
    _, _slug_a, token_a = await _make_tenant()
    _, slug_b, _token_b = await _make_tenant()

    async with _client() as http:
        response = await http.get(
            "/v1/leads", headers={"Authorization": f"Bearer {token_a}", "X-Org-Slug": slug_b}
        )
    assert response.status_code == 403
    assert response.json()["kind"] == "permission"


async def test_lead_list_masks_phone_numbers() -> None:
    """Hard rule 6 at the serialization boundary: the list page is the most-screenshotted
    surface in the product, so it never carries a full number."""
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        real_phone = (await session.execute(text("SELECT phone_e164 FROM leads LIMIT 1"))).scalar()

    async with _client() as http:
        response = await http.get(
            "/v1/leads", headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )
    payload = response.text
    assert real_phone not in payload
    assert response.json()["items"][0]["phone_masked"].startswith("•")


async def test_staff_cannot_read_raw_transcripts_but_owner_can_and_it_is_audited() -> None:
    """DATA-MODEL §2: staff get no raw transcripts. Owners do, and every read writes an
    audit row in the same transaction (hard rule 5)."""
    tenant_id, slug, owner_token = await _make_tenant(role="owner")
    _, staff_slug, staff_token = await _make_tenant(role="staff")

    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
                "'completed', '+919876500000', now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"e_{call_id.hex[:10]}"},
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:id, :tid, :cid, 0, 'caller', "
                "'naa number 9876543210', 'naa number [phone ••10]', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "cid": call_id},
        )

    async with _client() as http:
        redacted = await http.get(
            f"/v1/calls/{call_id}",
            headers={"Authorization": f"Bearer {owner_token}", "X-Org-Slug": slug},
        )
        raw = await http.get(
            f"/v1/calls/{call_id}/transcript/raw",
            headers={"Authorization": f"Bearer {owner_token}", "X-Org-Slug": slug},
        )
        staff_attempt = await http.get(
            f"/v1/calls/{call_id}/transcript/raw",
            headers={"Authorization": f"Bearer {staff_token}", "X-Org-Slug": staff_slug},
        )

    assert "9876543210" not in redacted.text, "the default view is redacted"
    assert redacted.json()["transcript"][0]["redacted"] is True
    assert "9876543210" in raw.text, "the owner's audited view is not redacted"
    assert staff_attempt.status_code == 403

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'transcript.read_raw' "
                    "AND object_id = :cid"
                ),
                {"cid": str(call_id)},
            )
        ).scalar()
    assert audited == 1, "a raw read that is not audited is a rule-5 violation"


async def test_boot_assertion_rejects_a_route_with_no_declared_permission() -> None:
    """The guardrail's own test. Without this, a change to route discovery could make
    `assert_policy_registry_complete` silently check nothing."""
    from fastapi import FastAPI

    unguarded = FastAPI()

    @unguarded.get("/v1/secrets")
    async def _secrets() -> dict[str, str]:
        return {"nope": "nope"}

    with pytest.raises(MissingPolicyError, match="secrets"):
        assert_policy_registry_complete(unguarded)


async def test_boot_assertion_fails_loudly_when_it_can_see_no_routes() -> None:
    from fastapi import FastAPI

    with pytest.raises(MissingPolicyError, match="no routes"):
        assert_policy_registry_complete(FastAPI())


async def test_the_real_app_passes_its_own_policy_registry() -> None:
    assert_policy_registry_complete(app)
