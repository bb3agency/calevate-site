"""The last four routes with no HTTP-layer test (PLAN part 8).

`GET /v1/admin/tenants/{tenant_id}/erasure/{request_id}`,
`DELETE /v1/admin/tenants/{tenant_id}/invitations/{invitation_id}`,
`GET /v1/billing/topups/capability` and
`POST /v1/lead-sources/{webhook_id}/meta/redrive`.

They have nothing in common except the gap, so this file is organised by route rather
than by theme. Each is the wrapper over machinery another suite already exercises —
`tenant_erasure_test` files erasures, `member_invitations_test` drives the CLIENT-realm
revoke, `payments_provider_seam_test` drives the capability selector, and
`meta_redrive_test` calls `_absorb_leadgen` — so what is asserted here is only what
the ROUTE adds: the permission, the tenancy, the response model and the audit row.

Two of the four carry a specific claim that had nothing behind it:

* the erasure READ is "still answerable once the tenant is erased", which is the point
  of the whole surface — a screen that 404s the moment the erasure succeeds makes the
  certificate unreachable at exactly the moment somebody needs it;
* the invitation revoke is a CAS on `used_at IS NULL`, so an invitation accepted
  between the click and the request answers 404 rather than deleting a membership's
  paper trail — and the audit row is the ONLY record that the key ever existed, because
  the row is deleted rather than flagged.

D-22 is not re-asserted for the two mutating routes (`admin:tenants`, `org:manage`):
`realm_boundary_test::test_no_route_declaring_a_mutating_permission_is_reachable_while_impersonating`
already drives every mutating-permission route under a real minted grant.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import payment_routes
from apps.api.billing.payments import PaymentCapability
from apps.api.compliance import tenant_erasure
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers.retention import execute_tenant_erasure
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

ERASURES = "/v1/admin/tenants/{tenant_id}/erasure"
ERASURE = ERASURES + "/{request_id}"
INVITATIONS = "/v1/admin/tenants/{tenant_id}/invitations"
INVITATION = INVITATIONS + "/{invitation_id}"
CAPABILITY = "/v1/billing/topups/capability"
REDRIVE = "/v1/lead-sources/{webhook_id}/meta/redrive"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
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


async def _make_member(tenant_id: UUID, role: str = "owner") -> str:
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


async def _tenant() -> tuple[UUID, str]:
    created = await admin_service.create_organization(
        name="Wrapper Clinic",
        slug=f"wrap-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), str(created["slug"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _audit_actions(tenant_id: UUID, object_id: str) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t AND object_id = :o "
                    "ORDER BY at, id"
                ),
                {"t": tenant_id, "o": object_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


# --- GET …/erasure/{request_id} -------------------------------------------------------


async def _filed_erasure(tenant_id: UUID, token: str) -> str:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :t"), {"t": tenant_id}
        )
    async with _client() as http:
        filed = await http.post(
            ERASURES.format(tenant_id=tenant_id),
            headers={
                **_auth(token),
                "X-Confirm-Action": tenant_erasure.tenant_erasure_confirmation(tenant_id),
            },
            json={"reason": "The client closed their account and asked us to erase it."},
        )
    assert filed.status_code == 201, filed.text
    return str(filed.json()["request_id"])


async def test_one_erasure_record_reads_back_with_its_certificate_after_the_erasure() -> None:
    """The claim this route exists for: the certificate stays reachable AFTER the
    tenant is gone. `list_tenant_erasures` carries that promise in a docstring and
    `tenant_erasure_test` proves it for the LIST; the single-record read — which is what
    a certificate link opens — had nothing behind it.

    The proof block is read field by field, because a `proof: null` after a completed
    erasure is precisely the failure this endpoint would show and a status assertion
    would not.
    """
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    request_id = await _filed_erasure(tenant_id, token)

    async with _client() as http:
        before = await http.get(
            ERASURE.format(tenant_id=tenant_id, request_id=request_id), headers=_auth(token)
        )
    assert before.status_code == 200, before.text
    pending = before.json()
    assert pending["request_id"] == request_id
    assert pending["status"] == "pending"
    assert pending["proof"] is None, "there is no certificate until the erasure has run"
    assert pending["limitations"], "the register rides every response on this surface"

    result = await execute_tenant_erasure(
        {}, {"tenant_id": str(tenant_id), "request_id": request_id}
    )
    assert "tenant erased" in result

    async with _client() as http:
        after = await http.get(
            ERASURE.format(tenant_id=tenant_id, request_id=request_id), headers=_auth(token)
        )
    assert after.status_code == 200, (
        "the certificate became unreachable the moment it was earned — the read must "
        "outlive the tenant (`tenant_erasure.list_tenant_erasures` docstring)"
    )
    body = after.json()
    assert body["status"] == "completed"
    proof = body["proof"]
    assert proof, "a completed erasure with no proof is an unevidenced deletion claim"
    assert proof["tenant_id"] == str(tenant_id)
    assert proof["executed_at"], proof
    assert proof["actions"], "the certificate names what was done to each store"
    assert proof["limitations_version"], proof


async def test_a_neighbours_erasure_request_id_is_not_found() -> None:
    """RLS scopes the lookup, so another tenant's record answers exactly as a
    nonexistent id does. Driven because both ids are in the PATH: nothing but the
    session's scope makes `tenant_id` and `request_id` agree."""
    tenant_id, _slug = await _tenant()
    other_id, _other_slug = await _tenant()
    token = await _make_admin()
    stranger = await _filed_erasure(other_id, token)

    async with _client() as http:
        crossed = await http.get(
            ERASURE.format(tenant_id=tenant_id, request_id=stranger), headers=_auth(token)
        )
        absent = await http.get(
            ERASURE.format(tenant_id=tenant_id, request_id=uuid.uuid4()), headers=_auth(token)
        )
    assert crossed.status_code == 404, crossed.text
    assert absent.status_code == 404, absent.text
    assert crossed.json()["detail"] == absent.json()["detail"], (
        "another tenant's id and an id that never existed must be indistinguishable"
    )


async def test_a_client_cannot_read_its_own_erasure_record_through_the_admin_route() -> None:
    """`org:read` in the ADMIN realm. The client-facing erasure surface is
    `/v1/compliance/deletion-requests`, which is about a data SUBJECT; this one is about
    the whole account and is ops-only."""
    tenant_id, slug = await _tenant()
    admin_token = await _make_admin()
    request_id = await _filed_erasure(tenant_id, admin_token)
    member = await _make_member(tenant_id, role="owner")

    async with _client() as http:
        response = await http.get(
            ERASURE.format(tenant_id=tenant_id, request_id=request_id),
            headers={"Authorization": f"Bearer {member}", "X-Org-Slug": slug},
        )
    assert response.status_code == 401, response.text
    assert response.json()["kind"] == "auth", response.text


# --- DELETE …/invitations/{invitation_id} ---------------------------------------------


async def _invite(tenant_id: UUID, token: str) -> str:
    async with _client() as http:
        invited = await http.post(
            INVITATIONS.format(tenant_id=tenant_id),
            headers=_auth(token),
            json={"email": f"owner-{uuid.uuid4().hex[:8]}@example.com", "role": "owner"},
        )
    assert invited.status_code == 201, invited.text
    return str(invited.json()["id"])


async def test_revoking_an_unused_invitation_is_204_and_the_audit_row_is_all_that_is_left() -> None:
    """The row is DELETED rather than flagged, so `audit_log` is the only record that
    this key ever existed — which is why the delete and its audit share one transaction
    (`revoke_tenant_invitation` docstring). Both halves are asserted: the row is gone
    AND the ledger remembers it, with the invited role in the action name.
    """
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    invitation_id = await _invite(tenant_id, token)

    async with _client() as http:
        revoked = await http.delete(
            INVITATION.format(tenant_id=tenant_id, invitation_id=invitation_id),
            headers=_auth(token),
        )
        remaining = await http.get(INVITATIONS.format(tenant_id=tenant_id), headers=_auth(token))
    assert revoked.status_code == 204, revoked.text
    assert revoked.content == b"", "204 carries no body"
    assert [i["id"] for i in remaining.json()] == []

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM invitations WHERE id = :i"), {"i": invitation_id}
            )
        ).scalar_one()
    assert rows == 0, "the invitation is deleted, not flagged"
    assert await _audit_actions(tenant_id, invitation_id) == [
        "admin.invitation_created",
        # The invited ROLE rides the action name, so "what authority was handed out and
        # then withdrawn" is answerable from the ledger alone — which is all that is
        # left once the row is gone.
        "admin.invitation_revoked:owner",
    ], "the ledger is the only surviving record of the key"


async def test_an_invitation_already_accepted_is_404_and_the_membership_survives() -> None:
    """The CAS is on `used_at IS NULL`. An invitation accepted between the click and the
    request is NOT deleted — the person is a member now, and removing them is a
    different act on a different surface."""
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    invitation_id = await _invite(tenant_id, token)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE invitations SET used_at = now() WHERE id = :i"), {"i": invitation_id}
        )

    async with _client() as http:
        response = await http.delete(
            INVITATION.format(tenant_id=tenant_id, invitation_id=invitation_id),
            headers=_auth(token),
        )
    assert response.status_code == 404, response.text
    async with tenant_session(tenant_id) as session:
        still_there = (
            await session.execute(
                text("SELECT count(*) FROM invitations WHERE id = :i"), {"i": invitation_id}
            )
        ).scalar_one()
    assert still_there == 1, "an accepted invitation is the paper trail of a membership"
    assert "admin.invitation_revoked:owner" not in await _audit_actions(tenant_id, invitation_id)


async def test_a_neighbours_invitation_cannot_be_revoked() -> None:
    """`revoke_invitation` runs in the tenant's own RLS scope, so an id belonging to
    another tenant is invisible and answers 404 rather than confirming it exists
    (D-65) — and, crucially, rather than revoking it."""
    tenant_id, _slug = await _tenant()
    other_id, _other_slug = await _tenant()
    token = await _make_admin()
    stranger = await _invite(other_id, token)

    async with _client() as http:
        response = await http.delete(
            INVITATION.format(tenant_id=tenant_id, invitation_id=stranger), headers=_auth(token)
        )
    assert response.status_code == 404, response.text
    async with tenant_session(other_id) as session:
        survives = (
            await session.execute(
                text("SELECT count(*) FROM invitations WHERE id = :i"), {"i": stranger}
            )
        ).scalar_one()
    assert survives == 1, "the neighbour's invitation was revoked across a tenant boundary"


# --- GET /v1/billing/topups/capability ------------------------------------------------


async def test_the_topup_capability_reports_this_deployments_two_booleans() -> None:
    """A RENDERING HINT, never the check (D-75) — but a hint that disagreed with the
    intent route would put a Pay button in front of a refusal.

    Both booleans are read, and the DEFAULT deployment is asserted as it actually is:
    no payment provider is configured, so both are false and the reason is logged
    rather than returned. A `reason` on the wire would be an internals leak — a client
    cannot act on "no_webhook_secret".
    """
    tenant_id, slug = await _tenant()
    member = await _make_member(tenant_id, role="owner")
    async with _client() as http:
        response = await http.get(
            CAPABILITY, headers={"Authorization": f"Bearer {member}", "X-Org-Slug": slug}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"online_payments_available", "provider_orders_available"}, (
        "the response names OUR configuration state and must carry no reason code"
    )
    assert body["online_payments_available"] is False
    assert body["provider_orders_available"] is False


async def test_the_capability_answers_off_the_same_selector_every_other_surface_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam is the whole point: no settings are read in the handler. Moving the
    SELECTOR must move this response, or the route has grown its own opinion and a
    screen can offer what the intent route refuses.

    Asserted with the two halves independent — `available` without `creates_orders` is
    the coherent deployment `payment_capability` documents (it credits payments taken
    elsewhere), so a handler collapsing them into one boolean fails here.
    """
    tenant_id, slug = await _tenant()
    member = await _make_member(tenant_id, role="owner")
    # Patched on `payment_routes`, not on `billing.payments`: the route imports the
    # selector by name, so patching the definition module would leave the handler
    # holding the original reference and this test would pass by not testing anything.
    monkeypatch.setattr(
        payment_routes,
        "payment_capability",
        lambda: PaymentCapability(available=True, provider="razorpay", creates_orders=False),
    )
    async with _client() as http:
        response = await http.get(
            CAPABILITY, headers={"Authorization": f"Bearer {member}", "X-Org-Slug": slug}
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "online_payments_available": True,
        "provider_orders_available": False,
    }


async def test_staff_cannot_read_the_payment_capability() -> None:
    """`billing:read`, which `staff` does not hold — the role table's "no billing" line,
    driven. The control proves the session itself works."""
    tenant_id, slug = await _tenant()
    staff = await _make_member(tenant_id, role="staff")
    headers = {"Authorization": f"Bearer {staff}", "X-Org-Slug": slug}
    async with _client() as http:
        control = await http.get("/v1/agents", headers=headers)
        refused = await http.get(CAPABILITY, headers=headers)
    assert control.status_code == 200, control.text
    assert refused.status_code == 403, refused.text
    assert "billing:read" in refused.json()["detail"], refused.text


# --- POST /v1/lead-sources/{webhook_id}/meta/redrive ----------------------------------


async def _lead_source(tenant_id: UUID, slug: str, source: str = "meta_lead_ads") -> str:
    token = await _make_member(tenant_id, role="owner")
    async with _client() as http:
        created = await http.post(
            "/v1/lead-sources",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
            # A Meta source carries the client's own App Secret; every other kind has
            # one minted for it, and supplying one is refused (`app_secret_not_accepted`).
            json=(
                {"source": source, "mapping": {}, "app_secret": "a-real-app-secret-value"}
                if source == "meta_lead_ads"
                else {"source": source, "mapping": {}}
            ),
        )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_a_redrive_with_nothing_to_recover_accounts_for_zero_of_everything() -> None:
    """`candidates != accepted + duplicate + refused + deferred` is the arithmetic that
    says a row went missing (`MetaRedriveOut` docstring). The empty case is the one that
    makes the arithmetic checkable at all, and it is the state a client's screen is in
    the first time they press the button.

    Counts only, `extra="forbid"`: this handler holds retrieved leads in scope — names
    and phone numbers — and an untyped return is one careless line from shipping them.
    """
    tenant_id, slug = await _tenant()
    webhook_id = await _lead_source(tenant_id, slug)
    owner = await _make_member(tenant_id, role="owner")
    async with _client() as http:
        response = await http.post(
            REDRIVE.format(webhook_id=webhook_id),
            headers={"Authorization": f"Bearer {owner}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "candidates": 0,
        "accepted": 0,
        "duplicate": 0,
        "refused": 0,
        "deferred": 0,
    }
    assert body["candidates"] == (
        body["accepted"] + body["duplicate"] + body["refused"] + body["deferred"]
    ), "the arithmetic that would show a recorded lead going missing"


async def test_a_redrive_is_audited_as_somebody_asking_for_one() -> None:
    """ "The act is recorded even if the run dies halfway: an audit of a re-drive is an
    audit of somebody asking for one" (`meta_redrive` docstring). That is a claim about
    ordering — the row commits BEFORE any Graph call — and nothing held the route to
    writing the row at all."""
    tenant_id, slug = await _tenant()
    webhook_id = await _lead_source(tenant_id, slug)
    owner = await _make_member(tenant_id, role="owner")
    async with _client() as http:
        await http.post(
            REDRIVE.format(webhook_id=webhook_id),
            headers={"Authorization": f"Bearer {owner}", "X-Org-Slug": slug},
        )
    assert "lead_source.meta_redriven" in await _audit_actions(tenant_id, webhook_id)


async def test_a_non_meta_lead_source_cannot_be_redriven() -> None:
    """The route reads Meta's inbox keyspace. A website-form source has no `leadgen_id`
    to recover, and answering 200 with zeros would tell a client the button had worked."""
    tenant_id, slug = await _tenant()
    webhook_id = await _lead_source(tenant_id, slug, source="website_form")
    owner = await _make_member(tenant_id, role="owner")
    async with _client() as http:
        response = await http.post(
            REDRIVE.format(webhook_id=webhook_id),
            headers={"Authorization": f"Bearer {owner}", "X-Org-Slug": slug},
        )
    assert response.status_code == 404, response.text


async def test_staff_cannot_redrive_and_a_neighbours_source_is_invisible() -> None:
    """`org:manage`, matching every other write on this router: `staff` is out.

    The cross-tenant half matters more than usual here — `webhook_inbox_events` has no
    `tenant_id` at all (it is keyspaced by provider), so what makes those rows this
    tenant's is only that `load_config` resolved `webhook_id` under RLS.
    """
    tenant_id, slug = await _tenant()
    other_id, other_slug = await _tenant()
    webhook_id = await _lead_source(tenant_id, slug)
    stranger = await _lead_source(other_id, other_slug)
    staff = await _make_member(tenant_id, role="staff")
    owner = await _make_member(tenant_id, role="owner")

    async with _client() as http:
        by_staff = await http.post(
            REDRIVE.format(webhook_id=webhook_id),
            headers={"Authorization": f"Bearer {staff}", "X-Org-Slug": slug},
        )
        crossed = await http.post(
            REDRIVE.format(webhook_id=stranger),
            headers={"Authorization": f"Bearer {owner}", "X-Org-Slug": slug},
        )
    assert by_staff.status_code == 403, by_staff.text
    assert "org:manage" in by_staff.json()["detail"], by_staff.text
    assert crossed.status_code == 404, crossed.text
    neighbour_actions = await _audit_actions(other_id, stranger)
    assert neighbour_actions, "non-vacuity: the neighbour's source has a create row"
    assert "lead_source.meta_redriven" not in neighbour_actions, (
        "a neighbour's source was re-driven across a tenant boundary"
    )
