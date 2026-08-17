"""Saved views: private per user, isolated per tenant, and graceful when a schema moves.

`lead_saved_views` is a NEW tenant table (migration a7e2c40d9b53), so hard rule 1's
cross-tenant zero-rows proof is mandatory and is the first test below — asserted twice,
once through the client route and once on the raw RLS-scoped session, so a handler that
filtered in Python rather than relying on the policy would still fail.

The second property is the one the policy CANNOT give: a view is private to one PERSON,
and `users` is a global table with no RLS (DATA-MODEL §2). Privacy is therefore an
explicit `user_id` predicate in every statement, and `test_a_colleague_on_the_same_account
_cannot_see_or_edit_my_view` is what stops that predicate being dropped as redundant.

The third is the degradation: a view pinned to an extraction field an admin later removed
must come back pruned and LABELLED, never 500 and never silently applied as nothing.
"""

from __future__ import annotations

import json
import uuid

import pytest
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.lead_columns_test import SCHEMA, Tenant, _tenant

VIEWS = "/v1/leads/views"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _second_member(t: Tenant, role: str = "owner") -> str:
    """Another real person on the SAME account, with their own dev token."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": t.tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


# ------------------------------------------------------------------ hard rule 1


async def test_tenant_b_cannot_see_tenant_as_saved_view() -> None:
    """The cross-tenant zero-rows proof this table ships with (hard rule 1).

    Both halves matter. The ROUTE half proves the shipped surface; the raw-session half
    proves it is the POLICY doing the work — a handler that had filtered in Python would
    pass the first assertion and fail the second.
    """
    a = await _tenant()
    b = await _tenant()

    async with _client() as http:
        created = await http.post(
            VIEWS, json={"name": "Hot this week", "filters": {"status": "hot"}}, headers=a.headers
        )
        assert created.status_code == 201, created.text
        seen_by_b = await http.get(VIEWS, headers=b.headers)
        seen_by_a = await http.get(VIEWS, headers=a.headers)

    assert seen_by_b.status_code == 200
    assert seen_by_b.json()["items"] == [], "tenant B must see ZERO of tenant A's views"
    assert [v["name"] for v in seen_by_a.json()["items"]] == ["Hot this week"]

    async with tenant_session(b.tenant_id) as session:
        rows = (await session.execute(text("SELECT count(*) FROM lead_saved_views"))).scalar()
    assert rows == 0, "the POLICY, not the handler, is what hides tenant A's row"

    async with untenanted_session() as session:
        rows = (await session.execute(text("SELECT count(*) FROM lead_saved_views"))).scalar()
    assert rows == 0, "no GUC ⇒ zero rows (fail closed)"


async def test_a_colleague_on_the_same_account_cannot_see_or_edit_my_view() -> None:
    """RLS answers "which tenant" and never "which person". This is the other half."""
    a = await _tenant()
    colleague = await _second_member(a)
    colleague_headers = {"Authorization": f"Bearer {colleague}", "X-Org-Slug": a.slug}

    async with _client() as http:
        created = await http.post(VIEWS, json={"name": "Mine"}, headers=a.headers)
        view_id = created.json()["id"]
        listed = await http.get(VIEWS, headers=colleague_headers)
        patched = await http.patch(
            f"{VIEWS}/{view_id}", json={"name": "Theirs"}, headers=colleague_headers
        )
        deleted = await http.delete(f"{VIEWS}/{view_id}", headers=colleague_headers)

    assert listed.json()["items"] == []
    assert patched.status_code == 404, patched.text
    assert deleted.status_code == 404

    async with _client() as http:
        mine = await http.get(VIEWS, headers=a.headers)
    assert [v["name"] for v in mine.json()["items"]] == ["Mine"], "untouched by the colleague"


# ------------------------------------------------------------------------ CRUD


async def test_a_view_round_trips_its_filters_and_columns() -> None:
    a = await _tenant()
    payload = {
        "name": "Big budgets",
        "filters": {"status": "hot", "fields": {"budget_band": ["over_50l"]}},
        "columns": ["name", "budget_band"],
    }
    async with _client() as http:
        created = await http.post(VIEWS, json=payload, headers=a.headers)
        listed = await http.get(VIEWS, headers=a.headers)

    assert created.status_code == 201, created.text
    view = listed.json()["items"][0]
    assert view["filters"]["status"] == "hot"
    assert view["filters"]["fields"] == {"budget_band": ["over_50l"]}
    assert view["columns"] == ["name", "budget_band"]
    assert view["stale_filter_keys"] == [] and view["stale_column_keys"] == []


async def test_two_views_cannot_share_a_name_and_the_refusal_says_so() -> None:
    a = await _tenant()
    async with _client() as http:
        first = await http.post(VIEWS, json={"name": "Hot"}, headers=a.headers)
        second = await http.post(VIEWS, json={"name": "Hot"}, headers=a.headers)
    assert first.status_code == 201
    assert second.status_code == 409, second.text
    assert second.json()["type"].endswith("/saved_view_name_taken")


async def test_clearing_the_column_choice_is_an_empty_list_and_stores_as_null() -> None:
    """`null` means "leave it alone" on a PATCH, so `[]` is the clear. One spelling of
    "no choice made" reaches the column, which the CHECK constraint also insists on."""
    a = await _tenant()
    async with _client() as http:
        created = await http.post(VIEWS, json={"name": "V", "columns": ["name"]}, headers=a.headers)
        view_id = created.json()["id"]
        cleared = await http.patch(f"{VIEWS}/{view_id}", json={"columns": []}, headers=a.headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["columns"] is None

    async with tenant_session(a.tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT columns FROM lead_saved_views WHERE id = :i"), {"i": view_id}
            )
        ).scalar()
    assert stored is None


async def test_deleting_a_view_removes_it() -> None:
    a = await _tenant()
    async with _client() as http:
        created = await http.post(VIEWS, json={"name": "Temp"}, headers=a.headers)
        gone = await http.delete(f"{VIEWS}/{created.json()['id']}", headers=a.headers)
        listed = await http.get(VIEWS, headers=a.headers)
    assert gone.status_code == 204
    assert listed.json()["items"] == []


async def test_a_staff_member_may_read_views_but_a_view_is_a_write() -> None:
    """`leads:write` gates the mutations — chosen over a new permission because it is
    already the "may change the Leads table" answer, and it is in MUTATING_PERMISSIONS
    so a D-22 impersonating operator is refused it for free."""
    a = await _tenant()
    async with _client() as http:
        assert (await http.get(VIEWS, headers=a.headers)).status_code == 200
        assert (await http.post(VIEWS, json={"name": "X"}, headers=a.headers)).status_code == 201


# ------------------------------------------------------------- degradation


async def test_a_view_pinned_to_a_removed_field_degrades_and_names_what_it_lost() -> None:
    """The industry answer to this event is a broken filter and a repair job
    (crm/saved_views.py cites Jira's). Ours is a pruned view and a sentence.

    Both halves are asserted: the dead FILTER is removed from `filters` AND reported, so
    the screen cannot silently apply a wider query than the client asked for; the dead
    COLUMN is removed from `columns` and reported the same way.
    """
    a = await _tenant()
    async with _client() as http:
        created = await http.post(
            VIEWS,
            json={
                "name": "Big budgets",
                "filters": {"fields": {"budget_band": ["over_50l"]}},
                "columns": ["name", "budget_band"],
            },
            headers=a.headers,
        )
        assert created.status_code == 201, created.text

    # An admin edits the capture list out from under the view (D-21: admin-only, so the
    # client never sees it coming). `budget_band` is gone.
    async with tenant_session(a.tenant_id) as session:
        await session.execute(
            text("UPDATE extraction_schemas SET fields = CAST(:f AS jsonb) WHERE agent_id = :a"),
            {"a": a.agent_id, "f": json.dumps([SCHEMA[1]])},
        )

    async with _client() as http:
        listed = await http.get(VIEWS, headers=a.headers)

    assert listed.status_code == 200, "a stale reference is not a 500"
    view = listed.json()["items"][0]
    assert view["filters"]["fields"] == {}, "the dead filter is REMOVED, not applied as nothing"
    assert view["stale_filter_keys"] == ["budget_band"], "and named, because it widened the set"
    assert view["columns"] == ["name"]
    assert view["stale_column_keys"] == ["budget_band"]


async def test_the_row_is_not_rewritten_so_restoring_the_field_restores_the_view() -> None:
    """Pruning happens on READ. A destructive cleanup could not undo an admin's mistake;
    this can."""
    a = await _tenant()
    async with _client() as http:
        await http.post(
            VIEWS,
            json={"name": "Big budgets", "filters": {"fields": {"budget_band": ["over_50l"]}}},
            headers=a.headers,
        )
    async with tenant_session(a.tenant_id) as session:
        await session.execute(
            text("UPDATE extraction_schemas SET fields = CAST(:f AS jsonb) WHERE agent_id = :a"),
            {"a": a.agent_id, "f": json.dumps([SCHEMA[1]])},
        )
    async with _client() as http:
        assert (await http.get(VIEWS, headers=a.headers)).json()["items"][0][
            "stale_filter_keys"
        ] == ["budget_band"]
    async with tenant_session(a.tenant_id) as session:
        await session.execute(
            text("UPDATE extraction_schemas SET fields = CAST(:f AS jsonb) WHERE agent_id = :a"),
            {"a": a.agent_id, "f": json.dumps(SCHEMA)},
        )
    async with _client() as http:
        restored = (await http.get(VIEWS, headers=a.headers)).json()["items"][0]
    assert restored["filters"]["fields"] == {"budget_band": ["over_50l"]}
    assert restored["stale_filter_keys"] == []


async def test_a_view_that_selects_no_values_under_a_key_is_refused_at_the_boundary() -> None:
    """An empty value list is a filter that means nothing, and a stored one would be a
    row whose meaning depends on which reader interprets it."""
    a = await _tenant()
    async with _client() as http:
        response = await http.post(
            VIEWS,
            json={"name": "Broken", "filters": {"fields": {"budget_band": []}}},
            headers=a.headers,
        )
    assert response.status_code == 422, response.text


async def test_a_session_with_no_signed_in_user_owns_no_views_and_is_told_so() -> None:
    """`_view_owner`'s refusal — the branch that decides WHOSE views a request is about.

    A saved view is private, keyed on `user_id`, so a principal without one has no
    coherent answer to "which views are mine". The dangerous reading is the permissive
    one: treat a missing `user_id` as "no filter" and the list endpoint returns every
    view on the account, and the delete endpoint deletes a colleague's. Refusing is the
    only safe reading, and it is the one the code takes.

    Tested against the function rather than through a route because there is no dev-token
    shape that mints a client principal with `user_id=None` — which is precisely why the
    branch was uncovered when the coverage ratchet flagged it (dial-path, +2 units). A
    branch that today's callers cannot reach is still a branch a future caller can, and
    a token type that carries no user is an ordinary thing for an API to grow.
    """
    from apps.api.crm.routes import _view_owner

    anonymous = Principal(
        realm="client",
        user_id=None,
        clerk_user_id=None,
        tenant_id=uuid.uuid4(),
        role="owner",
    )
    with pytest.raises(ProblemError) as raised:
        _view_owner(anonymous)
    assert raised.value.status == 403
    # The message has to name the reason; "forbidden" alone sends a client to support.
    assert "signed-in user" in str(raised.value.detail)

    # And the positive half, so this pins a DISCRIMINATION rather than a blanket refusal.
    signed_in_user = uuid.uuid4()
    assert (
        _view_owner(
            Principal(
                realm="client",
                user_id=signed_in_user,
                clerk_user_id="user_x",
                tenant_id=uuid.uuid4(),
                role="owner",
            )
        )
        == signed_in_user
    )
