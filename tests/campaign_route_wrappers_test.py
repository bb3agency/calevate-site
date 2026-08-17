"""Four campaign routes nothing drove at the HTTP layer (PLAN part 8).

`GET /v1/campaigns/numbers`, `GET /v1/campaigns/templates`,
`POST /v1/campaigns/{campaign_id}/contacts` and
`POST /v1/campaigns/{campaign_id}/recurrence`.

The last two are exercised at the SERVICE layer by `campaign_recurrence_test` and
`campaigns_test`, which call `service.add_contacts` and
`scheduling.schedule_recurrence` directly. The first two have no test at all, and they
are the two that matter most for tenancy: both are **raw SQL with no `WHERE
tenant_id`** (`campaigns/routes.py:346,367`), so RLS is the ONLY thing standing
between one client's number list and another's. A service test cannot see that,
because there is no service — the query is in the handler.

What is asserted here:

1. **The two lists are RLS-scoped, driven.** Two tenants, each with a number and a
   template, and neither sees the other's. This is hard rule 1 asserted on the exact
   shape the rule exists for: an unqualified SELECT inside a tenant session.
2. **Mount order.** `/numbers` and `/templates` are declared BEFORE `/{campaign_id}`
   because FastAPI matches in declaration order — the hazard `two_speed_publishing_
   routes_test` calls out for `/v1/agents/lanes`. A regression turns these into a 422
   about a UUID nobody sent, so the assertion is that they answer a LIST.
3. **`add_contacts` counts rather than guesses.** A malformed number is counted, not
   silently normalised into a dialable one, and a duplicate inside one payload is
   counted once — the response model's three integers are read, not the status.
4. **`recurrence` returns the rule AND the next occurrence**, because a repeat a client
   cannot read is a repeat they cannot trust, and it is AUDITED: "who told this
   campaign to dial every Tuesday" is the question asked after a complaint.
5. **`staff` cannot do either mutation.** Both declare `leads:dispatch`, which `staff`
   does not hold — the wrong-role refusal that no route-table sweep covers.

D-22 is not re-asserted for the two mutations: `leads:dispatch` is mutating, so
`realm_boundary_test::test_no_route_declaring_a_mutating_permission_is_reachable_while_impersonating`
already drives them under a real grant.

CONCURRENCY: every case mints its own tenant, and nothing here launches or schedules a
campaign into a state the dispatch tick would act on — the recurrence written below is
cancelled on the way out, for the reason `campaign_recurrence_test` gives.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

CAMPAIGNS = "/v1/campaigns"
NUMBERS = f"{CAMPAIGNS}/numbers"
TEMPLATES = f"{CAMPAIGNS}/templates"
CONTACTS = CAMPAIGNS + "/{campaign_id}/contacts"
RECURRENCE = CAMPAIGNS + "/{campaign_id}/recurrence"

_TENANTS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
async def _leave_the_platform_quiet() -> AsyncIterator[None]:
    """Cancel every schedule this module armed.

    Not tidiness: a repeat is permanently due once its occurrence passes, so a leaked
    one makes its tenant permanently dispatchable and `dispatch_scale_test` would
    measure this suite's litter instead of D-57's property. Same reason
    `campaign_recurrence_test` carries the identical fixture.
    """
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', schedule = NULL, "
                    "updated_at = now() WHERE status IN ('scheduled', 'running', 'paused')"
                )
            )
    _TENANTS.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
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
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """(tenant, agent, slug) — an outbound-capable tenant with a live agent."""
    created = await admin_service.create_organization(
        name="Route Motors",
        slug=f"crw-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    ref = f"fakeagent_crw_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id, str(created["slug"])


async def _number_and_template(tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A registered 140-series number and an approved promotional template."""
    number_id, template_id = uuid7(), uuid7()
    e164 = f"+9180{uuid.uuid4().int % 10**8:08d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, created_at, "
                "updated_at) VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": e164},
        )
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
    return number_id, template_id, e164


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    number_id, template_id, _e164 = await _number_and_template(tenant_id)
    async with tenant_session(tenant_id) as session:
        return await service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Weekly follow-up",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=3,
            calling_hours=None,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )


async def _headers(tenant_id: uuid.UUID, slug: str, role: str = "owner") -> dict[str, str]:
    token = await _make_member(tenant_id, role=role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _audit(tenant_id: uuid.UUID, action: str) -> list[tuple[str, str, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT object_type, object_id, ip FROM audit_log "
                    "WHERE tenant_id = :t AND action = :a ORDER BY at, id"
                ),
                {"t": tenant_id, "a": action},
            )
        ).all()
    return [(str(r[0]), str(r[1]), None if r[2] is None else str(r[2])) for r in rows]


# --- the two selector lists -----------------------------------------------------------


async def test_the_number_and_template_lists_are_scoped_by_rls_alone() -> None:
    """Both handlers run an unqualified `SELECT … FROM phone_numbers` /
    `dlt_templates` (`campaigns/routes.py:346,367`). There is no `WHERE tenant_id`, on
    purpose — RLS is the tenancy boundary — which makes this the one shape where a
    policy regression is invisible everywhere except at the wire.

    Both tenants are populated, so "sees only its own" is not satisfied by an empty
    database.
    """
    tenant_a, _agent_a, slug_a = await _tenant()
    tenant_b, _agent_b, slug_b = await _tenant()
    _num_a, tmpl_a, e164_a = await _number_and_template(tenant_a)
    _num_b, tmpl_b, e164_b = await _number_and_template(tenant_b)

    async with _client() as http:
        headers_a = await _headers(tenant_a, slug_a)
        headers_b = await _headers(tenant_b, slug_b)
        numbers_a = await http.get(NUMBERS, headers=headers_a)
        numbers_b = await http.get(NUMBERS, headers=headers_b)
        templates_a = await http.get(TEMPLATES, headers=headers_a)
        templates_b = await http.get(TEMPLATES, headers=headers_b)

    for response in (numbers_a, numbers_b, templates_a, templates_b):
        assert response.status_code == 200, response.text

    # The fields the campaign form actually reads, populated — not merely a 200.
    assert [(n["e164"], n["series"], n["dlt_status"]) for n in numbers_a.json()] == [
        (e164_a, "140", "registered")
    ]
    assert [n["e164"] for n in numbers_b.json()] == [e164_b]

    assert [(t["id"], t["classification"], t["status"]) for t in templates_a.json()] == [
        (str(tmpl_a), "promotional", "approved")
    ]
    assert [t["id"] for t in templates_b.json()] == [str(tmpl_b)]
    assert templates_a.json()[0]["body"], "the body is what the operator picks between"


async def test_the_literal_segments_are_not_parsed_as_a_campaign_id() -> None:
    """`/numbers` and `/templates` are declared before `/{campaign_id}`, and FastAPI
    matches in declaration order. Reordering the module turns both into a 422 about a
    UUID nobody sent — the hazard `two_speed_publishing_routes_test` pins for
    `/v1/agents/lanes`, on a router where nothing pinned it.
    """
    tenant_id, _agent_id, slug = await _tenant()
    async with _client() as http:
        headers = await _headers(tenant_id, slug)
        numbers = await http.get(NUMBERS, headers=headers)
        templates = await http.get(TEMPLATES, headers=headers)
    for name, response in (("numbers", numbers), ("templates", templates)):
        assert response.status_code == 200, f"{name}: {response.text}"
        assert isinstance(response.json(), list), (
            f"{name} answered an object — the literal segment is being matched by "
            "`/{campaign_id}`, which is a declaration-order regression"
        )


# --- contacts -------------------------------------------------------------------------


async def test_adding_contacts_counts_malformed_and_duplicate_rather_than_guessing() -> None:
    """The three integers ARE the response: an operator pasting a CSV needs to know
    that 2 of 5 rows will never be dialled, and a handler that silently normalised a
    malformed number into a dialable one would report 5 added and dial a stranger."""
    tenant_id, agent_id, slug = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with _client() as http:
        response = await http.post(
            CONTACTS.format(campaign_id=campaign_id),
            headers=await _headers(tenant_id, slug),
            json={
                "contacts": [
                    {"phone": "9876510001", "name": "Asha"},
                    {"phone": "9876510002", "name": "Bhanu", "custom": {"model": "Nexon"}},
                    # The same subscriber twice in one paste — one row, counted once.
                    {"phone": "9876510001", "name": "Asha again"},
                    {"phone": "not-a-number", "name": "Typo"},
                ]
            },
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"added": 2, "malformed": 1, "duplicate": 1}

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "SELECT phone_e164, name FROM campaign_contacts WHERE campaign_id = :c "
                    "ORDER BY phone_e164"
                ),
                {"c": campaign_id},
            )
        ).all()
    assert [r[1] for r in stored] == ["Asha", "Bhanu"]
    assert all(str(r[0]).startswith("+91") for r in stored), "stored E.164, never as typed"


async def test_an_unknown_campaign_is_not_reported_as_one_that_has_already_launched() -> None:
    """THE DEFECT THIS FILE FOUND. `add_contacts` read the campaign's status with
    `.scalar()` and refused anything that was not `draft`/`scheduled` — so a null,
    meaning "no campaign of yours has this id", came back as 422 `campaign_not_draft`:
    "Contacts can only be added before a campaign is launched."

    Two things were wrong with that. The client was handed a remediation they cannot
    perform — there is nothing to un-launch — and the sentence asserts that the id names
    a campaign, which for an id RLS is hiding is a statement about somebody else's
    account. `kb/service.approve_source` carries the same correction for the same
    mistake, and the other three readers of this column already distinguished the two.

    Both halves are pinned: absent is 404, and a genuinely launched campaign still gets
    the business-rule refusal, so the fix cannot be "always 404".
    """
    tenant_id, agent_id, slug = await _tenant()
    running = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET status = 'running' WHERE id = :c"), {"c": running}
        )
    async with _client() as http:
        headers = await _headers(tenant_id, slug)
        payload = {"contacts": [{"phone": "9876510055"}]}
        absent = await http.post(
            CONTACTS.format(campaign_id=uuid.uuid4()), headers=headers, json=payload
        )
        launched = await http.post(
            CONTACTS.format(campaign_id=running), headers=headers, json=payload
        )

    assert absent.status_code == 404, absent.text
    body = absent.json()
    assert body["type"].endswith("/not_found"), body
    assert "launch" not in body["detail"].lower(), (
        "an id that names nothing must not be described as a campaign that has launched"
    )

    assert launched.status_code == 422, launched.text
    assert launched.json()["type"].endswith("/campaign_not_draft"), launched.text


async def test_staff_cannot_load_a_dialing_list() -> None:
    """`leads:dispatch`, which `staff` does not hold. Loading the list is the act that
    decides who gets called, so it sits with the permission to place calls rather than
    with `leads:write`."""
    tenant_id, agent_id, slug = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with _client() as http:
        headers = await _headers(tenant_id, slug, role="staff")
        # The control: `staff` can read the campaign list on the same session.
        control = await http.get(CAMPAIGNS, headers=headers)
        refused = await http.post(
            CONTACTS.format(campaign_id=campaign_id),
            headers=headers,
            json={"contacts": [{"phone": "9876510009"}]},
        )
    assert control.status_code == 200, control.text
    assert refused.status_code == 403, refused.text
    assert "leads:dispatch" in refused.json()["detail"], refused.text

    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    assert count == 0


# --- recurrence -----------------------------------------------------------------------


async def test_setting_a_repeat_returns_the_rule_and_the_next_occurrence_and_audits_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A repeat is not one launch with a delay — it is every launch until somebody stops
    it, so "who told this campaign to dial every Tuesday, and when" is exactly the
    question `audit_log` exists to answer (`campaigns/routes.py::set_recurrence`).

    The response is read in full: the rule as stored, the next occurrence, and
    `first_dial_not_before`, which differs from the occurrence whenever the campaign
    narrowed its own calling hours — a screen showing only the occurrence would promise
    a 10:00 dial on a campaign that only dials from noon.
    """
    tenant_id, agent_id, slug = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    until = datetime.now(UTC) + timedelta(days=60)
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await http.post(
                RECURRENCE.format(campaign_id=campaign_id),
                headers=await _headers(tenant_id, slug),
                json={"days": [2, 4], "at": "10:00", "until": until.isoformat()},
            )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == [2, 4], "ISO weekday numbers, one numbering across the wire"
    assert body["at"] == "10:00"
    assert body["until"] is not None
    next_occurrence = datetime.fromisoformat(body["next_occurrence_at"])
    first_dial = datetime.fromisoformat(body["first_dial_not_before"])
    assert next_occurrence > datetime.now(UTC), "a repeat's next occurrence is in the future"
    assert next_occurrence.isoweekday() in (2, 4), "the next occurrence is on a named day"
    assert first_dial >= next_occurrence

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT status, schedule FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).one()
    assert stored[0] == "scheduled"
    assert stored[1]["kind"] == "recurring"

    assert await _audit(tenant_id, "campaign.recurrence_set") == [
        ("campaign", str(campaign_id), "127.0.0.1")
    ]
    summary = [r for r in caplog.records if r.getMessage() == "audit"][-1]
    assert summary.at_ist == "10:00"  # type: ignore[attr-defined]
    assert summary.next_occurrence  # type: ignore[attr-defined]
    # `days` reaches the ledger as `"[2 items]"`: `redact_mapping` collapses every list
    # to its length before the summary leaves the process (`core/logging.py:103`). The
    # COUNT is asserted rather than the numbers, because asserting the numbers would be
    # asserting that the sanitizer had been loosened.
    assert summary.days == "[2 items]"  # type: ignore[attr-defined]


async def test_staff_cannot_arm_a_repeat() -> None:
    """Stronger than the contacts case and for the same reason `set_recurrence`'s
    docstring gives: this is every launch from now until somebody stops it."""
    tenant_id, agent_id, slug = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with _client() as http:
        response = await http.post(
            RECURRENCE.format(campaign_id=campaign_id),
            headers=await _headers(tenant_id, slug, role="staff"),
            json={"days": [2], "at": "10:00"},
        )
    assert response.status_code == 403, response.text

    async with tenant_session(tenant_id) as session:
        schedule = (
            await session.execute(
                text("SELECT schedule FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert schedule is None
    assert await _audit(tenant_id, "campaign.recurrence_set") == []


async def test_a_neighbours_campaign_id_arms_nothing() -> None:
    """The campaign id is in the PATH and the tenant comes from the session. Both
    mutations resolve the campaign under the caller's own RLS scope, so a foreign id is
    a 404 rather than a repeat armed on somebody else's dialer."""
    tenant_id, _agent_id, slug = await _tenant()
    other_id, other_agent, _other_slug = await _tenant()
    stranger = await _campaign(other_id, other_agent)
    async with _client() as http:
        headers = await _headers(tenant_id, slug)
        contacts = await http.post(
            CONTACTS.format(campaign_id=stranger),
            headers=headers,
            json={"contacts": [{"phone": "9876510077"}]},
        )
        recurrence = await http.post(
            RECURRENCE.format(campaign_id=stranger),
            headers=headers,
            json={"days": [2], "at": "10:00"},
        )
    assert contacts.status_code == 404, contacts.text
    assert recurrence.status_code == 404, recurrence.text

    async with tenant_session(other_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT schedule, (SELECT count(*) FROM campaign_contacts "
                    "WHERE campaign_id = :c) FROM campaigns WHERE id = :c"
                ),
                {"c": stranger},
            )
        ).one()
    assert row[0] is None and row[1] == 0, "the neighbour's campaign was untouched"
