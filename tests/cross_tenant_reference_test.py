"""A tenant may not NAME a neighbour's row in something it writes (D-193).

`tests/adversarial_pass_test.py` drives the READ side: tenant B asks for tenant A's
`{id}` and must be told 404. This is the WRITE side, and RLS does not cover it on its
own — PostgreSQL runs referential-integrity checks with row security bypassed, so a
policy's `WITH CHECK` stops B forging a row INTO A while the foreign key inside B's own
row is validated against the whole table and happily accepts A's id.

What that produced before the fix, driven over HTTP with a valid tenant-B session:

    POST /v1/campaigns
    {"agent_id": "<TENANT A's agent>", "name": "x", "classification": "service",
     "concurrency": 1}
    -> 201 Created

    POST /v1/campaigns
    {"agent_id": "<B's own>", "name": "x", "classification": "promotional",
     "number_id": "<A's DLT-registered number>",
     "dlt_template_id": "<A's approved voice template>", "concurrency": 1}
    -> 201 Created

    POST /v1/compliance/messaging-consent
    {"phone": "+91...", "status": "granted", "source": "inbound_call_verbal",
     "call_id": "<A's call>", "evidence": {"form": "ivr", "version": "1"}}
    -> 201 Created, and the row is in `consent_ledger`

The consent one is the worst of the three and it is the reason this is a test rather
than a note: `consent_ledger` is in `db/registry.APPEND_ONLY_TABLES` (hard rule 4), so
an opt-in evidenced by a conversation the tenant was never party to is a DPDP record
that can never be corrected — only compensated by a second row that also cannot say the
first was a lie about whose call it was.

The campaign ones are not currently a disclosure, and the tests below say so rather than
overclaiming: every consumer checked fails closed, because the launch gate's joins run
under the caller's own session (a foreign number reads back as `number_missing`) and
`check_dispatch` scopes the agent by `tenant_id` explicitly. What survived was a stored
cross-tenant reference — one un-scoped `JOIN` away from being a disclosure, and
`campaigns/service.py` already carries a hand-written `AND p.tenant_id = c.tenant_id` on
one such join — and a campaign the client owns, can see, and can never launch: its own
launch-check answers "Campaign not found" because `_campaign_facts` INNER JOINs `agents`.

Concurrency: this repo's tests share one Postgres. Everything below is scoped to
run-unique tenants and nothing asserts a global count.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]


def _client() -> AsyncClient:
    """A CALL-unique documentation address (RFC 3849), so no two runs share a limiter
    bucket."""
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)), base_url="http://api"
    )


async def _make_org() -> dict[str, object]:
    return await admin_service.create_organization(
        name="Reference Clinic",
        slug=f"xref-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _make_owner(tenant_id: uuid.UUID) -> str:
    """A real `users` row with a real owner membership. Returns the dev token."""
    user_id = uuid.uuid4()
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
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return f"dev:client:{user_id}"


async def _agent_of(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as s:
        return uuid.UUID(
            str(
                (
                    await s.execute(
                        text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"),
                        {"t": tenant_id},
                    )
                ).scalar_one()
            )
        )


def _problem(response: object) -> str:
    payload = response.json()  # type: ignore[attr-defined]
    return str(payload.get("type", "")).rsplit("/", 1)[-1] if isinstance(payload, dict) else ""


@pytest.fixture
async def neighbours() -> tuple[dict[str, object], dict[str, object]]:
    return await _make_org(), await _make_org()


async def test_a_campaign_cannot_name_a_neighbours_agent(
    neighbours: tuple[dict[str, object], dict[str, object]],
) -> None:
    """`agent_id` is the caller's to send and not the caller's to choose."""
    org_a, org_b = neighbours
    agent_a = await _agent_of(uuid.UUID(str(org_a["id"])))
    token_b = await _make_owner(uuid.UUID(str(org_b["id"])))

    async with _client() as http:
        response = await http.post(
            "/v1/campaigns",
            headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": str(org_b["slug"])},
            json={
                "agent_id": str(agent_a),
                "name": "campaign on a neighbour's agent",
                "classification": "service",
                "concurrency": 1,
            },
        )

    # 404 rather than 403, for the reason the IDOR sweep pins: from inside a tenant,
    # "not yours" and "no such row" are the same fact, and separating them would
    # publish the existence of a neighbour's agents.
    assert response.status_code == 404, response.text
    assert _problem(response) == "not_found"


async def test_a_campaign_cannot_dial_from_a_neighbours_registered_number(
    neighbours: tuple[dict[str, object], dict[str, object]],
) -> None:
    """The number and the DLT template are the two that carry a REGULATOR's name.

    A 140-series header and an approved voice template are registered to the client's own
    Principal Entity. A campaign of B's that cites A's is Calevate placing traffic under
    the wrong PE — which is whose complaint count it lands on (SEC-COMP §1).
    """
    org_a, org_b = neighbours
    tenant_a = uuid.UUID(str(org_a["id"]))
    agent_b = await _agent_of(uuid.UUID(str(org_b["id"])))
    token_b = await _make_owner(uuid.UUID(str(org_b["id"])))

    number_a, template_a = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_a) as s:
        await s.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, "
                "created_at, updated_at) VALUES (:i, :t, :e, '140', 'registered', now(), now())"
            ),
            {"i": number_a, "t": tenant_a, "e": f"+9114000{uuid.uuid4().int % 100000:05d}"},
        )
        await s.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, status, "
                "body, created_at, updated_at) VALUES (:i, :t, 'voice', 'promotional', "
                "'approved', 'Tenant A registered wording', now(), now())"
            ),
            {"i": template_a, "t": tenant_a},
        )

    headers = {"Authorization": f"Bearer {token_b}", "X-Org-Slug": str(org_b["slug"])}
    body: dict[str, object] = {
        "agent_id": str(agent_b),
        "name": "campaign on a neighbour's header",
        "classification": "promotional",
        "concurrency": 1,
    }
    async with _client() as http:
        with_number = await http.post(
            "/v1/campaigns", headers=headers, json={**body, "number_id": str(number_a)}
        )
        with_template = await http.post(
            "/v1/campaigns", headers=headers, json={**body, "dlt_template_id": str(template_a)}
        )

    assert with_number.status_code == 404, with_number.text
    assert with_template.status_code == 404, with_template.text
    assert _problem(with_number) == "not_found"
    assert _problem(with_template) == "not_found"

    # Nothing was stored. The point of the check being BEFORE the INSERT rather than a
    # constraint after it is that a refused campaign leaves no row at all.
    async with tenant_session(uuid.UUID(str(org_b["id"]))) as s:
        stored = (
            await s.execute(
                text("SELECT count(*) FROM campaigns WHERE number_id = :n OR dlt_template_id = :d"),
                {"n": number_a, "d": template_a},
            )
        ).scalar_one()
    assert stored == 0


async def test_a_consent_grant_cannot_cite_a_neighbours_call(
    neighbours: tuple[dict[str, object], dict[str, object]],
) -> None:
    """The append-only one, and therefore the one that could never have been undone.

    A spoken opt-in has to name the conversation it happened in (`_assert_grant_is_
    evidenced`). Before D-193 that call could be anybody's, and `consent_ledger` is
    INSERT-only under hard rule 4 — so the wrong row would have been permanent.
    """
    org_a, org_b = neighbours
    tenant_a = uuid.UUID(str(org_a["id"]))
    agent_a = await _agent_of(tenant_a)
    token_b = await _make_owner(uuid.UUID(str(org_b["id"])))

    call_a = uuid.uuid4()
    async with tenant_session(tenant_a) as s:
        await s.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status) "
                "VALUES (:i, :t, :a, :e, 'inbound', 'completed')"
            ),
            {"i": call_a, "t": tenant_a, "a": agent_a, "e": f"eng-{uuid.uuid4().hex[:10]}"},
        )

    async with _client() as http:
        response = await http.post(
            "/v1/compliance/messaging-consent",
            headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": str(org_b["slug"])},
            json={
                "phone": "+919000000123",
                "status": "granted",
                "source": "inbound_call_verbal",
                "call_id": str(call_a),
                "evidence": {"form": "ivr", "version": "1"},
            },
        )

    assert response.status_code == 404, response.text
    assert _problem(response) == "not_found"

    # The ledger is append-only, so "nothing was written" is the only recoverable state
    # and is what this asserts. Read on tenant A's own session: B could not see the row
    # either way, and the question is whether it EXISTS.
    async with tenant_session(tenant_a) as s:
        leaked = (
            await s.execute(
                text("SELECT count(*) FROM consent_ledger WHERE call_id = :c"), {"c": call_a}
            )
        ).scalar_one()
    assert leaked == 0, "an opt-in citing another tenant's call reached the append-only ledger"


async def test_the_guard_still_allows_a_tenants_own_references(
    neighbours: tuple[dict[str, object], dict[str, object]],
) -> None:
    """Non-vacuity, and the half a refusal-only test cannot prove.

    Every assertion above is satisfied by a route that refuses EVERYTHING, so the same
    request built from the tenant's OWN rows has to still succeed — otherwise the fix is
    an outage wearing a security test.
    """
    _org_a, org_b = neighbours
    tenant_b = uuid.UUID(str(org_b["id"]))
    agent_b = await _agent_of(tenant_b)
    token_b = await _make_owner(tenant_b)

    number_b = uuid.uuid4()
    async with tenant_session(tenant_b) as s:
        await s.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, "
                "created_at, updated_at) VALUES (:i, :t, :e, '140', 'registered', now(), now())"
            ),
            {"i": number_b, "t": tenant_b, "e": f"+9114000{uuid.uuid4().int % 100000:05d}"},
        )
        call_b = uuid.uuid4()
        await s.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status) "
                "VALUES (:i, :t, :a, :e, 'inbound', 'completed')"
            ),
            {"i": call_b, "t": tenant_b, "a": agent_b, "e": f"eng-{uuid.uuid4().hex[:10]}"},
        )

    headers = {"Authorization": f"Bearer {token_b}", "X-Org-Slug": str(org_b["slug"])}
    async with _client() as http:
        campaign = await http.post(
            "/v1/campaigns",
            headers=headers,
            json={
                "agent_id": str(agent_b),
                "name": "a campaign on its own rows",
                "classification": "promotional",
                "number_id": str(number_b),
                "concurrency": 1,
            },
        )
        consent = await http.post(
            "/v1/compliance/messaging-consent",
            headers=headers,
            json={
                "phone": "+919000000124",
                "status": "granted",
                "source": "inbound_call_verbal",
                "call_id": str(call_b),
                "evidence": {"form": "ivr", "version": "1"},
            },
        )

    assert campaign.status_code == 201, campaign.text
    assert consent.status_code == 201, consent.text


async def test_a_null_reference_is_still_a_legal_draft(
    neighbours: tuple[dict[str, object], dict[str, object]],
) -> None:
    """`number_id` and `dlt_template_id` are nullable and a draft may omit them.

    The guard no-ops on `None` deliberately: refusing an absent number here would move
    the launch gate's `number_missing` blocker to creation time and make a half-filled
    draft impossible to save, which is a product change dressed as a security fix.
    """
    _org_a, org_b = neighbours
    tenant_b = uuid.UUID(str(org_b["id"]))
    agent_b = await _agent_of(tenant_b)
    token_b = await _make_owner(tenant_b)

    async with _client() as http:
        response = await http.post(
            "/v1/campaigns",
            headers={"Authorization": f"Bearer {token_b}", "X-Org-Slug": str(org_b["slug"])},
            json={
                "agent_id": str(agent_b),
                "name": "a draft with nothing attached yet",
                "classification": "service",
                "concurrency": 1,
            },
        )
    assert response.status_code == 201, response.text
