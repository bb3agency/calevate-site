"""The Leads grid joins `memberships`, and that table is not scoped the way it reads.

`memberships` is the one FORCE-RLS'd table in this repo whose visible rows are not
confined to the scoped tenant. Migration `8c31d0f4ab27` widened its policy to
`tenant_id = app.tenant_id OR user_id = app.user_id` on purpose — a session has to be
able to ask "which tenants may I enter" before it has a tenant — so wherever
`app.user_id` is set, the requesting user's OWN membership rows in every account they
belong to are visible.

`crm.service._LEAD_OWNER_JOIN` reads that table to name a lead's owner. A `LEFT JOIN` on
`m.user_id = l.assigned_to` alone multiplies against those extra rows: a lead assigned to
the person reading the page comes back once per account that person holds, the page's
`LIMIT` is spent on duplicates while `total` (counted without the join) goes on reporting
the honest number, and `GET /v1/leads/export.csv` — which shares the join — writes the
same contact into the file that many times.

**WHAT IS AND IS NOT TRUE TODAY, stated rather than implied.** It is NOT reachable over
HTTP: `app.user_id` has exactly one writer, `db.session.user_session`, and a request's
`tenant_session` does not set it, so the second arm evaluates against NULL. That is a
fact about the session plumbing, not about this query, and it is what the first test
below pins by setting the GUC by hand — the shape a `tenant_session` that carried the
caller's identity would hand this SQL on day one. The two HTTP tests hold the ordinary
path to the same answer from the outside.

Every test mints its own organizations and asserts only on rows it created.
"""

from __future__ import annotations

import uuid

from apps.api.crm.service import _LEAD_COLUMNS, _LEAD_OWNER_JOIN
from apps.api.db.session import tenant_session
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant


def _client() -> AsyncClient:
    from apps.api.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _also_a_member_of(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'staff', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )


async def _assign_the_lead(tenant_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        lead_id = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).scalar()
        await session.execute(
            text("UPDATE leads SET assigned_to = :u WHERE id = :l"),
            {"u": user_id, "l": lead_id},
        )
    return uuid.UUID(str(lead_id))


async def _staged() -> tuple[uuid.UUID, str, str, uuid.UUID, uuid.UUID]:
    """(tenant A, its slug, a bearer for a user who is in A *and* B, that user, the lead)."""
    tenant_a, slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    user_id = uuid.UUID(token_a.removeprefix("dev:client:"))
    await _also_a_member_of(tenant_b, user_id)
    return tenant_a, slug_a, token_a, user_id, await _assign_the_lead(tenant_a, user_id)


async def test_the_owner_join_does_not_multiply_when_the_reader_is_identified() -> None:
    """The join itself, under a session that carries BOTH GUCs.

    This is the only test here that can fail: it drives the real select list and the real
    join with `app.user_id` set, which is what makes the policy's second arm live. Without
    `m.tenant_id = l.tenant_id` the one lead comes back twice — once per account its owner
    belongs to — and no amount of RLS says otherwise, because both membership rows are
    rows the policy means this session to see.
    """
    tenant_id, _slug, _token, user_id, lead_id = await _staged()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
        )
        # The GUC is live: this session really can see the OTHER tenant's membership row,
        # so the multiplication is available and the join is what refuses it.
        visible = (
            await session.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar()
        assert int(str(visible)) == 2

        rows = (
            await session.execute(
                text(f"SELECT {_LEAD_COLUMNS} FROM leads l {_LEAD_OWNER_JOIN} WHERE l.id = :lid"),
                {"lid": lead_id},
            )
        ).all()
    assert len(rows) == 1


async def test_a_lead_assigned_to_a_multi_account_reader_appears_once_on_the_grid() -> None:
    """The ordinary HTTP path, from the outside."""
    _tenant, slug, token, _user, lead_id = await _staged()
    async with _client() as http:
        response = await http.get(
            "/v1/leads", headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )
    assert response.status_code == 200
    body = response.json()
    assert [i["id"] for i in body["items"]].count(str(lead_id)) == 1
    # And the grid agrees with the count rendered beside it, which is computed WITHOUT
    # the join and so cannot be the thing that is wrong.
    assert len(body["items"]) == body["total"]


async def test_the_export_writes_that_lead_once() -> None:
    """The CSV shares the join, and it is the surface that leaves the building."""
    tenant_id, slug, token, _user, lead_id = await _staged()
    # Keyed on the lead's phone: it is unique per `_make_tenant` and it is a column of
    # the file, so counting it counts the row without depending on the column order.
    async with tenant_session(tenant_id) as session:
        phone = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE id = :l"), {"l": lead_id}
            )
        ).scalar()
    async with _client() as http:
        response = await http.get(
            "/v1/leads/export.csv",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200
    assert response.text.count(str(phone)) == 1
