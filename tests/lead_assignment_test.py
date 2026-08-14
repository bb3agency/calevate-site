"""Lead ownership: who may be given a lead, and what the record says afterwards.

ROADMAP M3's "lead assignment". `leads.assigned_to` existed from the core migration and
nothing read or wrote it — it was one of `check_wiring.UNWIRED_BASELINE`'s dated
deferrals. What this file pins is the part of closing it that a reviewer cannot see by
reading the diff:

1. **The tenancy gate is real, and it is the RLS on `memberships`.** `assigned_to` is a
   foreign key to `users`, which is a GLOBAL table with no RLS (DATA-MODEL §2), so the
   constraint itself would happily accept another tenant's user. The refusal below uses
   a REAL user id from a REAL second tenant — not a random UUID, which the FK would
   reject for the wrong reason and would prove nothing about isolation.
2. **Unassignment is expressible and is an event.** `"assigned_to": null` on the PATCH
   means "no owner"; an ABSENT key means "leave the owner alone". Both arrive as `None`
   on the Pydantic model, so a test that only exercised one of them would pass against
   an implementation that could not tell them apart.
3. **`staff` may assign.** Assignment is how a team divides work; gating it on an
   owner-only permission would put the daily job on the one person least likely to do it
   (the argument `/v1/attention` already makes for itself).

CONCURRENCY: every test mints its own organization and asserts only through
tenant-scoped reads, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid

import httpx
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.impersonation_grant_test import view_as_headers


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _the_lead(tenant_id: uuid.UUID) -> uuid.UUID:
    """The one lead `_make_tenant` seeds."""
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _the_member(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT user_id FROM memberships LIMIT 1"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _events(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> list[tuple[str, dict, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT type, payload, actor FROM lead_events WHERE lead_id = :l "
                    "ORDER BY created_at, id"
                ),
                {"l": lead_id},
            )
        ).all()
    return [(str(r[0]), r[1] or {}, str(r[2])) for r in rows]


async def _name_the_member(user_id: uuid.UUID, name: str) -> None:
    """`users` is global, so this needs no tenant context — and says why."""
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE users SET name = :n WHERE id = :u"), {"n": name, "u": user_id}
        )


async def _colleague(tenant_id: uuid.UUID, name: str, *, deactivated: bool = False) -> uuid.UUID:
    """A SECOND member of the same tenant.

    Needed because `_make_tenant` seeds one user who is also the bearer of the token —
    deactivating that one logs the test out with a 401 and proves nothing about
    assignment. Every "this person cannot be given work" case therefore acts on somebody
    other than the caller, which is also the only shape the product has.
    """
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, name, created_at, updated_at) "
                "VALUES (:i, :c, :e, :n, now(), now())"
            ),
            {
                "i": user_id,
                "c": f"user_{uuid.uuid4().hex[:12]}",
                "e": f"{user_id}@example.com",
                "n": name,
            },
        )
        if deactivated:
            await session.execute(
                text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": user_id}
            )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'staff', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return user_id


# --- the happy path ------------------------------------------------------------


async def test_assigning_a_lead_records_the_owner_and_names_them_on_the_row() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)
    await _name_the_member(member, "Priya Nair")

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(member)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_to"] == str(member)
    # The NAME travels with the row, resolved through `memberships` — the list has to
    # print an owner column and must not hold a second id it cannot render.
    assert body["assigned_to_name"] == "Priya Nair"

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT assigned_to FROM leads WHERE id = :l"), {"l": lead_id}
            )
        ).scalar()
    assert uuid.UUID(str(stored)) == member


async def test_the_assignment_writes_a_timeline_row_carrying_the_id_and_no_name() -> None:
    """The event is the point of the column: "who gave this to me, and when".

    The payload holds the ID. A name copied in would go stale the day the person changes
    it and would stay readable after they left the account — the read resolves the name
    through `memberships` instead, so the tenant's own policy decides who can be named.
    """
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)
    await _name_the_member(member, "Priya Nair")

    async with _client() as http:
        await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(member)},
        )

    events = await _events(tenant_id, lead_id)
    assert [e[0] for e in events] == ["assignment"]
    _type, payload, actor = events[0]
    assert payload == {"assigned_to": str(member)}
    assert "Priya Nair" not in str(payload), "a name in the payload is a name that goes stale"
    # The ACTOR is the person who did it, which is what makes "who gave me this?"
    # answerable at all.
    assert uuid.UUID(actor) == member


async def test_assignment_and_a_status_change_in_one_patch_write_one_event_each() -> None:
    """One route edits the lead, so one request may legitimately do both — and the
    timeline must not merge them into a single ambiguous row."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"status": "hot", "assigned_to": str(member)},
        )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "hot"
    assert sorted(e[0] for e in await _events(tenant_id, lead_id)) == [
        "assignment",
        "status_change",
    ]


# --- the refusal ---------------------------------------------------------------


async def test_a_user_from_another_tenant_is_refused_in_problem_json() -> None:
    """THE cross-tenant test, with a REAL foreign user id.

    A random UUID would be refused by the foreign key — which proves nothing about
    isolation, because the FK is a constraint on `users` and `users` has no RLS. This
    one exists, is a legitimate member of a different organization, and satisfies the FK
    perfectly; the only thing standing between it and `leads.assigned_to` is the RLS on
    `memberships` that `crm.service._assert_assignable` reads through.
    """
    tenant_id, slug, token = await _make_tenant()
    _other_tenant, _other_slug, _other_token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    stranger = await _the_member(_other_tenant)

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(stranger)},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].endswith("/lead_assignee_not_a_member")
    assert body["kind"] == "business_rule"
    # Actionable, and in the client's words — errors are part of the interface.
    assert "team" in body["detail"]
    assert "invite" in body["remediation"]
    # Nothing about the other account leaks through the refusal.
    assert _other_slug not in response.text

    # And nothing was written: not the column, not an event.
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT assigned_to FROM leads WHERE id = :l"), {"l": lead_id}
            )
        ).scalar()
    assert stored is None
    assert await _events(tenant_id, lead_id) == []


async def test_a_refused_assignee_rolls_back_the_status_in_the_same_body() -> None:
    """A body carrying a good status and a bad owner must move NEITHER.

    The validation runs before the UPDATE for exactly this: a half-applied edit is the
    version of this bug that is invisible, because the client sees a 422 and the status
    moved anyway.
    """
    tenant_id, slug, token = await _make_tenant()
    _other_tenant, _, _ = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    stranger = await _the_member(_other_tenant)

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"status": "won", "assigned_to": str(stranger)},
        )
    assert response.status_code == 422

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(text("SELECT status FROM leads WHERE id = :l"), {"l": lead_id})
        ).scalar()
    assert status == "new", "the status moved on a request the server refused"


async def test_a_deactivated_colleague_may_not_be_given_work() -> None:
    """A membership outlives a deactivation — the auth guard re-checks the USER on every
    request (BACKEND-PATTERNS §7) — so "still a member" is not "can still open the
    account", and assigning to one would look like an owner who is not there."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    gone = await _colleague(tenant_id, "Gone Away", deactivated=True)

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(gone)},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/lead_assignee_not_a_member")


# --- unassignment --------------------------------------------------------------


async def test_an_explicit_null_removes_the_owner_and_says_so_on_the_timeline() -> None:
    """An owner who leaves is a real event, so it is RECORDED rather than inferred from
    the absence of a later assignment."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)

    async with _client() as http:
        await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(member)},
        )
        response = await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"assigned_to": None}
        )

    assert response.status_code == 200, response.text
    assert response.json()["assigned_to"] is None
    assert response.json()["assigned_to_name"] is None

    events = await _events(tenant_id, lead_id)
    assert [e[0] for e in events] == ["assignment", "assignment"]
    assert events[1][1] == {"assigned_to": None}


async def test_an_absent_key_leaves_the_owner_alone() -> None:
    """The other half of the null, and the one an implementation that reads
    `payload.assigned_to is None` gets wrong: a PATCH that only renames the lead must
    not quietly unassign it."""
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)

    async with _client() as http:
        await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(member)},
        )
        response = await http.patch(
            f"/v1/leads/{lead_id}", headers=_headers(slug, token), json={"name": "Ravi Teja"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Ravi Teja"
    assert body["assigned_to"] == str(member), "an omitted key is not an unassignment"
    # …and no assignment event was invented for a change nobody asked for.
    assert [e[0] for e in await _events(tenant_id, lead_id)] == ["assignment"]


# --- who may do it -------------------------------------------------------------


async def test_staff_may_assign_because_dividing_work_is_the_daily_job() -> None:
    tenant_id, slug, token = await _make_tenant(role="staff")
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)

    async with _client() as http:
        response = await http.patch(
            f"/v1/leads/{lead_id}",
            headers=_headers(slug, token),
            json={"assigned_to": str(member)},
        )
    assert response.status_code == 200, response.text


async def test_a_read_only_impersonating_admin_cannot_assign(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """D-22: "view as client" is read-only. `leads:write` is in MUTATING_PERMISSIONS, so
    the PATCH is refused for an impersonating principal even though the operator's role
    holds the permission."""
    tenant_id, slug, _token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    member = await _the_member(tenant_id)

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
        response = await http.patch(
            f"/v1/leads/{lead_id}",
            headers=await view_as_headers(
                http, f"dev:admin:{admin_clerk}", slug, **{"X-Org-Slug": slug}
            ),
            json={"assigned_to": str(member)},
        )
    assert response.status_code == 403
    assert response.json()["kind"] == "permission"


# --- the "my leads" filter -----------------------------------------------------


async def test_the_assignee_filter_narrows_the_set_and_not_the_page() -> None:
    """SERVER-side, on a real column.

    The assertion that matters is the one on `total` and on the stage counts: both are
    computed over the filtered SET, so an implementation that fetched everything and
    sliced the page would still answer the account's numbers here (BUILD-LOG §52 records
    four separate defects of exactly that shape).
    """
    tenant_id, slug, token = await _make_tenant()
    member = await _the_member(tenant_id)
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        for index in range(4):
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, assigned_to, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, "
                    "'manual', 'contacted', :owner, now(), now())"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": tenant_id,
                    "a": agent_id,
                    "p": f"+9197{uuid.uuid4().int % 100000000:08d}",
                    "n": f"Mine {index}",
                    # Two of the four are mine; the rest of the account is not.
                    "owner": member if index < 2 else None,
                },
            )

    async with _client() as http:
        mine = await http.get(f"/v1/leads?assigned_to={member}", headers=_headers(slug, token))
        everything = await http.get("/v1/leads", headers=_headers(slug, token))

    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["total"] == 2
    assert {item["name"] for item in body["items"]} == {"Mine 0", "Mine 1"}
    # The stage tally follows the same scope as the rows — otherwise the badge row under
    # a "my leads" chip would describe somebody else's pipeline.
    assert body["status_counts_matching_search"]["contacted"] == 2
    assert body["status_counts_matching_search"]["new"] == 0
    assert everything.json()["total"] == 5


async def test_the_export_honours_the_assignee_filter_the_screen_applied() -> None:
    """The one route that emits FULL phone numbers must not widen a narrowed request.

    `_lead_scope` is shared for exactly this reason, and the export's own docstring
    records the release where `status` and `search` were on the list and not on the file:
    a client narrows the table to their own leads, presses Export, and mails a supplier
    the whole contact book.
    """
    tenant_id, slug, token = await _make_tenant()
    member = await _the_member(tenant_id)
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "assigned_to, created_at, updated_at) VALUES (:i, :t, :a, '+919812345678', "
                "'Mine', 'manual', 'new', :owner, now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": agent_id, "owner": member},
        )

    async with _client() as http:
        response = await http.get(
            f"/v1/leads/export.csv?assigned_to={member}", headers=_headers(slug, token)
        )
    assert response.status_code == 200, response.text
    lines = [line for line in response.text.splitlines() if line.strip()]
    assert len(lines) == 2, "header plus the one assigned lead, not the whole account"
    assert "+919812345678" in lines[1]
    # The seeded lead of `_make_tenant` is unassigned and must not be in the file.
    assert "Ravi" not in response.text


async def test_a_garbage_assignee_filter_is_a_validation_error_not_a_wide_read() -> None:
    """Failing OPEN here would hand back the whole account for a malformed request."""
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        response = await http.get("/v1/leads?assigned_to=not-a-uuid", headers=_headers(slug, token))
    assert response.status_code == 422
    assert response.json()["kind"] == "validation"


# --- the team list the picker renders ------------------------------------------


async def test_the_member_list_is_this_tenants_team_and_carries_no_email() -> None:
    tenant_id, slug, token = await _make_tenant()
    member = await _the_member(tenant_id)
    await _name_the_member(member, "Priya Nair")
    other_tenant, _other_slug, _ = await _make_tenant()
    stranger = await _the_member(other_tenant)
    await _name_the_member(stranger, "Somebody Else")

    async with _client() as http:
        response = await http.get("/v1/members", headers=_headers(slug, token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["id"] for m in body] == [str(member)]
    assert body[0]["name"] == "Priya Nair"
    assert body[0]["role"] == "owner"
    # `email` is in `check_redaction_exposure.RAW_PII_FIELDS`; the picker prints a name
    # and writes an id, and needs no address to do it.
    assert "email" not in body[0]
    assert "@" not in response.text
    assert "Somebody Else" not in response.text


async def test_a_deactivated_colleague_is_not_offered_as_an_assignee() -> None:
    """The picker and the assignment refuse the same person, so no option in the list
    is one the server would reject."""
    tenant_id, slug, token = await _make_tenant()
    member = await _the_member(tenant_id)
    await _name_the_member(member, "Still Here")
    await _colleague(tenant_id, "Gone Away", deactivated=True)
    await _colleague(tenant_id, "Also Here")

    async with _client() as http:
        response = await http.get("/v1/members", headers=_headers(slug, token))
    assert response.status_code == 200
    names = [m["name"] for m in response.json()]
    assert "Gone Away" not in names
    # Named people, alphabetically — a picker whose order moves between renders is a
    # picker people mis-click.
    assert names == ["Also Here", "Still Here"]
