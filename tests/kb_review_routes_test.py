"""The knowledge-review ROUTES, at the HTTP layer (PLAN part 8).

`kb_approval_gate_test`, `kb_workflow_test` and `kb_publish_atomicity_test` are
thorough about `kb/service.py` — they call `approve_source`, `reject_source` and
`publish_source` directly. **Nothing called the four endpoints that wrap them**, and
the wrapper is where a different set of things can be wrong: the permission
dependency, the realm, D-22's read-only rule, the audit row, and the response model
the console renders. A service-level suite cannot fail when a route loses its
`Depends(requires(...))`.

What is asserted here, in the order it matters:

1. **The realm boundary.** `POST …/kb/{source_id}/approve|reject|publish` are
   `realm="admin"` routes. A client `owner` — who holds `kb:write` and submitted the
   source in the first place — is refused. The client does not approve their own
   knowledge; that is the whole point of a review queue (`admin/routes.py:878`).
2. **D-22 is NOT re-asserted here.** All three mutate, and
   `realm_boundary_test::test_no_route_declaring_a_mutating_permission_is_reachable_while_impersonating`
   already DRIVES every route in the live table that declares a mutating permission
   under a real minted grant and requires a refusal — these three included. A
   per-route copy would be a second way to answer one question, which this repo counts
   as a defect even when both ways pass. Named here so the next reader does not add it.
3. **The happy path, with the response model's fields READ.** `publish` returns
   `PublishOut`, and the assertion is on `version` and `source_id`, not on `200`: a
   handler that returned an empty body would satisfy a status check.
4. **The audit row.** `kb.approved`/`kb.rejected`/`kb.published` land with the tenant,
   the object id and the reviewer's ip — and the idempotent repeat writes NO second
   row, which is the convention `approve_kb`'s docstring states and which no test held
   it to.
5. **`GET /v1/kb/sources/{source_id}/preview` is a CLIENT read** gated on
   `agents:read` — the D-22 lesson from `impersonation_reads_test`, pinned as
   behaviour rather than as a route-table property: `staff`, who cannot write
   knowledge at all, can still see what the agent would learn, and another tenant's
   source id previews nothing rather than leaking chunks.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so
this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.kb import service as kb_service
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

APPROVE = "/v1/admin/tenants/{tenant_id}/kb/{source_id}/approve"
REJECT = "/v1/admin/tenants/{tenant_id}/kb/{source_id}/reject"
PUBLISH = "/v1/admin/tenants/{tenant_id}/kb/{source_id}/publish"
PREVIEW = "/v1/kb/sources/{source_id}/preview"

BODY = "A consultation costs 500 rupees.\n\nWe are open 9am to 8pm, Monday to Saturday."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
    """A real `admin_users` row plus the dev-token spelling of its realm — the idiom
    `commercial_terms_test` and `authz_audit_test` both use."""
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}"


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{clerk_id}"


async def _slug(tenant_id: uuid.UUID) -> str:
    # `organizations` is RLS'd on the tenant's own id, so the untenanted session sees
    # no row — the same reason `kb_workflow_test._slug_of` reaches for `admin_session`.
    async with admin_session() as session:
        return str(
            (
                await session.execute(
                    text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
        )


async def _submit(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str = "Fees") -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=BODY
        )
    return uuid.UUID(str(submitted["id"]))


async def _audit(tenant_id: uuid.UUID, action: str) -> list[tuple[str, str, str | None]]:
    """`audit_log` rows for one action, oldest first.

    `audit_log` is not tenant-RLS'd (the hash chain is global), so this reads under the
    untenanted session and filters by tenant itself — the idiom
    `impersonation_grant_test._started_rows` uses. There is deliberately no `summary`
    column (`compliance/audit.py:326`: hashing a field the row does not carry would
    make the chain unverifiable), so the summary is asserted off the log stream where
    the tests below need it.
    """
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


def _last_audit_summary(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    """The last `summary=` payload `write_audit` emitted — the idiom
    `egress_guard_test` uses, and the only place a summary is observable."""
    records = [r for r in caplog.records if r.getMessage() == "audit"]
    assert records, "write_audit emitted no summary at all"
    return records[-1]


def _admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- realm: the client who submitted it does not approve it -------------------------


async def test_a_client_owner_cannot_approve_their_own_knowledge() -> None:
    """`kb:write` is the permission to SUBMIT. Approval is `agents:write` in the ADMIN
    realm, and an owner holds neither — so the refusal is the realm's, and it is the
    reason the review queue exists at all (`admin/routes.py:878`).

    401 with `kind: auth`, not 403, and `realm_boundary_test:132` argues why: a 403
    would send a support person looking for a role to grant, when the truth is that a
    client credential is not an admin credential at all. Driven per route here because
    that file drives two named paths, not the table.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit(tenant_id, agent_id)
    token = await _make_member(tenant_id, role="owner")
    slug = await _slug(tenant_id)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        # The control: the same token submits knowledge on its own realm, so a refusal
        # below cannot be a token that was simply broken.
        control = await http.get(PREVIEW.format(source_id=source_id), headers=headers)
        refusals = {
            "approve": await http.post(
                APPROVE.format(tenant_id=tenant_id, source_id=source_id), headers=headers
            ),
            "publish": await http.post(
                PUBLISH.format(tenant_id=tenant_id, source_id=source_id), headers=headers
            ),
            "reject": await http.post(
                REJECT.format(tenant_id=tenant_id, source_id=source_id),
                headers=headers,
                json={"reason": "I changed my mind about my own text."},
            ),
        }
    assert control.status_code == 200, control.text
    for name, response in refusals.items():
        assert response.status_code == 401, f"{name}: {response.text}"
        assert response.json()["kind"] == "auth", f"{name}: {response.text}"

    # And nothing moved: the source is still awaiting a reviewer.
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM kb_sources WHERE id = :i"), {"i": source_id}
            )
        ).scalar_one()
    assert status == "pending_approval"


# --- the happy path, and the audit row -----------------------------------------------


async def test_approve_then_publish_returns_the_version_and_audits_both(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The response model is READ, not merely counted: `PublishOut.version` is what the
    console shows as "v1 is live", and an empty body would satisfy a status assertion."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit(tenant_id, agent_id)
    token = await _make_admin()

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            approved = await http.post(
                APPROVE.format(tenant_id=tenant_id, source_id=source_id),
                headers=_admin_headers(token),
            )
            published = await http.post(
                PUBLISH.format(tenant_id=tenant_id, source_id=source_id),
                headers=_admin_headers(token),
            )
    assert approved.status_code == 200, approved.text
    assert approved.json() == {"status": "approved"}

    assert published.status_code == 200, published.text
    body = published.json()
    assert body["source_id"] == str(source_id)
    assert body["version"] == 1
    assert body["status"] == "live"

    assert await _audit(tenant_id, "kb.approved") == [("kb_source", str(source_id), "127.0.0.1")]
    assert await _audit(tenant_id, "kb.published") == [("kb_source", str(source_id), "127.0.0.1")]
    # The VERSION is the audited fact — never the knowledge body (hard rule 6).
    assert _last_audit_summary(caplog).version == 1  # type: ignore[attr-defined]


async def test_approving_twice_is_a_success_with_one_audit_row() -> None:
    """`approve_kb`'s docstring says a repeat is 200 and NOT a second `kb.approved` row,
    because the ledger answers "who let this text reach the agent" and a row per button
    press makes that harder. Nothing held it to that until now."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit(tenant_id, agent_id)
    token = await _make_admin()
    async with _client() as http:
        first = await http.post(
            APPROVE.format(tenant_id=tenant_id, source_id=source_id),
            headers=_admin_headers(token),
        )
        second = await http.post(
            APPROVE.format(tenant_id=tenant_id, source_id=source_id),
            headers=_admin_headers(token),
        )
    assert (first.status_code, second.status_code) == (200, 200), second.text
    assert len(await _audit(tenant_id, "kb.approved")) == 1

    # The first reviewer stays the recorded approver.
    async with tenant_session(tenant_id) as session:
        approvals = (
            await session.execute(
                text("SELECT count(*) FROM kb_sources WHERE id = :i AND approved_at IS NOT NULL"),
                {"i": source_id},
            )
        ).scalar_one()
    assert approvals == 1


async def test_rejection_records_the_reason_and_refuses_a_later_publish(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reason is the client-facing half — it is what the submitter reads — and it is
    the one field of this route's body that reaches the audit log."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit(tenant_id, agent_id)
    token = await _make_admin()
    reason = "The prices are out of date; resubmit with the 2026 fee schedule."
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            rejected = await http.post(
                REJECT.format(tenant_id=tenant_id, source_id=source_id),
                headers=_admin_headers(token),
                json={"reason": reason},
            )
            published = await http.post(
                PUBLISH.format(tenant_id=tenant_id, source_id=source_id),
                headers=_admin_headers(token),
            )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json() == {"status": "rejected"}
    assert await _audit(tenant_id, "kb.rejected") == [("kb_source", str(source_id), "127.0.0.1")]
    assert _last_audit_summary(caplog).reason == reason  # type: ignore[attr-defined]

    # Rejection never wrote `approved_at`, so the gate still holds at the ROUTE.
    assert published.status_code == 422, published.text
    assert published.json()["type"].endswith("/kb_not_approved"), published.text

    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT rejection_reason FROM kb_sources WHERE id = :i"), {"i": source_id}
            )
        ).scalar_one()
    assert stored == reason


async def test_another_tenants_source_id_is_a_404_not_a_409() -> None:
    """RLS makes the row invisible, so the honest answer is "no such source" — and an
    operator holding `agents:write` for every tenant is exactly who would otherwise
    learn that another client has a source with that id."""
    tenant_id, _agent_id = await _tenant_with_published_agent()
    other_id, other_agent = await _tenant_with_published_agent()
    stranger = await _submit(other_id, other_agent, name="Neighbour fees")
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            APPROVE.format(tenant_id=tenant_id, source_id=stranger),
            headers=_admin_headers(token),
        )
    assert response.status_code == 404, response.text
    # And the neighbour's source did not move.
    async with tenant_session(other_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM kb_sources WHERE id = :i"), {"i": stranger}
            )
        ).scalar_one()
    assert status == "pending_approval"
    assert await _audit(tenant_id, "kb.approved") == []


# --- the client-side preview ---------------------------------------------------------


async def test_staff_can_preview_exactly_what_the_agent_would_learn() -> None:
    """`agents:read`, deliberately not `kb:write`: this is the view that explains what a
    submission became, and `staff` — who cannot submit knowledge at all — must be able
    to look (D-22, `impersonation_reads_test`).

    The chunks are read, not counted: a handler returning `[]` would pass a status
    assertion while the side-by-side preview rendered empty.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit(tenant_id, agent_id)
    token = await _make_member(tenant_id, role="staff")
    slug = await _slug(tenant_id)
    async with _client() as http:
        response = await http.get(
            PREVIEW.format(source_id=source_id),
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200, response.text
    chunks = response.json()
    assert chunks, "the preview is the submitted text — an empty list is a broken screen"
    assert [c["idx"] for c in chunks] == list(range(len(chunks))), "reading order"
    assert all(c["chars"] == len(c["content"]) for c in chunks)
    assert "".join(c["content"] for c in chunks).replace("\n", " ").startswith("A consultation")


async def test_a_neighbours_source_previews_nothing() -> None:
    """The chunk table is RLS'd, so a foreign id is an empty preview rather than another
    client's price list. Asserted through the ROUTE because the tenant here comes from
    the session, and a handler that took it from the path would leak."""
    tenant_id, _ = await _tenant_with_published_agent()
    other_id, other_agent = await _tenant_with_published_agent()
    stranger = await _submit(other_id, other_agent, name="Neighbour fees")
    token = await _make_member(tenant_id, role="owner")
    slug = await _slug(tenant_id)
    async with _client() as http:
        response = await http.get(
            PREVIEW.format(source_id=stranger),
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200, response.text
    assert response.json() == []
