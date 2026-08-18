"""The hold queue — the half of two R-11 mitigations that was missing: DISCOVERY.

Two gates shipped without a way for the human they depend on to find their work:

* `kyc_records` — a self-serve tenant cannot dial until ops records a verification;
* `first_campaign_reviews` — a self-serve tenant's campaigns are all refused until ops
  releases the account.

Both hold an account until a person acts, and neither told the person. An operator
learned an account was waiting when the client emailed, which makes the mitigation
depend on the client complaining — a support queue, not a control. These tests pin the
properties that turn it back into one.

1. **The gap itself.** An operator can list every account waiting on a human, and see
   WHICH gate each is waiting on, without knowing the tenant's id in advance.
2. **Hard rule 1 is the design, not an afterthought.** The queue is a cross-tenant read
   from the admin realm and it widens NOTHING: `app.admin` still cannot see a row of
   `kyc_records` or `first_campaign_reviews`, and a client-realm session still sees
   exactly zero rows of another tenant. The isolation is the per-tenant
   `tenant_session` the queue opens, exactly as `admin.service.tenant_overview` counts
   calls (migration b57e2f9c4a13's scope, kept).
3. **Hard rule 6.** The queue lists ACCOUNTS, not people: no phone number, no document
   reference, no signatory, and no reviewer's free-text note — any of which could carry
   a person into an ops list that has no reason to hold one.
4. **One predicate.** "Is this tenant waiting?" is answered by the same
   `kyc_blocker` / `first_campaign_hold_blocker` the dial gate and the launch preview
   ask, so the queue can never disagree with the refusal the client is seeing.
5. **D-22.** It is a read, so it is readable with a read permission.

Run: uv run pytest -q tests/ops_hold_queue_test.py
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.rbac import MUTATING_PERMISSIONS
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

QUEUE_PATH = "/v1/admin/compliance/holds"
# A CIN is 21 characters — a KYC record needs a real registry shape.
CIN = "U74999TG2026PTC123456"
SIGNATORY = "Padmavathi Rao"
REVIEW_NOTE = "Read the list, the script and the disclosure line. Bought list — refused."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


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


async def _tenant(plan_tier: str = "self_serve") -> dict[str, Any]:
    """A tenant on the given motion. Nothing else: the queue asks two questions and
    neither needs an agent, a number or a campaign."""
    created = await admin_service.create_organization(
        name="Queue Motors",
        slug=f"queue-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    if plan_tier != "managed":
        async with tenant_session(tenant_id) as session:
            # Inside the tenant's own session: `organizations` is RLS'd on
            # `app.tenant_id`, so an untenanted UPDATE matches zero rows silently.
            result = await session.execute(
                text("UPDATE organizations SET plan_tier = :tier WHERE id = :tid"),
                {"tier": plan_tier, "tid": tenant_id},
            )
            assert result.rowcount == 1, "plan_tier must actually change for this fixture"
    return created


async def _verify_kyc(org: dict[str, Any]) -> None:
    """Through the audited ops route, never by writing the row."""
    token = await _make_admin("superadmin")
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/kyc",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "status": "verified",
                "entity_type": "private_limited",
                "document_kind": "cin",
                "document_ref": CIN,
                "signatory_name": SIGNATORY,
                "evidence_ref": "ops-ticket-4471",
            },
        )
    assert response.status_code == 200, response.text


async def _decide(org: dict[str, Any], *, decision: str, note: str = REVIEW_NOTE) -> None:
    """Release (or refuse) the account the way ops does: admin realm, audited."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/first-campaign-review",
            headers={"Authorization": f"Bearer {token}"},
            json={"decision": decision, "note": note},
        )
    assert response.status_code == 200, response.text


async def _queue(token: str | None = None) -> Any:
    token = token or await _make_admin()
    async with _client() as http:
        return await http.get(QUEUE_PATH, headers={"Authorization": f"Bearer {token}"})


def _row(response: Any, org: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (row for row in response.json() if row["tenant_id"] == str(org["id"])),
        None,
    )


# ------------------------------------------------------------------ the gap it closes


async def test_an_operator_can_find_the_accounts_waiting_on_a_human() -> None:
    """The whole slice in one assertion: a held account is DISCOVERABLE.

    Before this endpoint the only way to learn that an account was held was to be told
    the tenant id and ask about it — which is to say, to be emailed by the client.
    """
    nothing_filed = await _tenant("self_serve")
    kyc_done = await _tenant("self_serve")
    await _verify_kyc(kyc_done)
    managed = await _tenant("managed")

    response = await _queue()
    assert response.status_code == 200, response.text

    waiting_on_both = _row(response, nothing_filed)
    assert waiting_on_both is not None, "a brand-new self-serve account is held twice over"
    assert set(waiting_on_both["holds"]) == {"kyc_missing", "first_campaign_review_pending"}

    waiting_on_review = _row(response, kyc_done)
    assert waiting_on_review is not None
    assert waiting_on_review["holds"] == ["first_campaign_review_pending"], (
        "a verified account still waits for the first-campaign release, and only for it"
    )

    assert _row(response, managed) is None, (
        "neither gate applies to a managed tenant (SELF_SERVE_TIERS), so a queue that "
        "listed one would send an operator to do work that does not exist"
    )


async def test_a_refusal_keeps_the_account_in_the_queue_and_names_the_refusal() -> None:
    """A rejected account is still waiting on a human — the client owes us something and
    somebody has to chase it. It is a different rule from "nobody has looked yet", and
    the queue says which."""
    org = await _tenant("self_serve")
    await _verify_kyc(org)
    await _decide(org, decision="rejected")

    row = _row(await _queue(), org)
    assert row is not None, "a refused account is not a finished account"
    assert row["holds"] == ["first_campaign_review_rejected"]


async def test_clearing_both_gates_takes_the_account_off_the_queue() -> None:
    """The queue empties itself. A work list that keeps finished work is one an operator
    stops reading."""
    org = await _tenant("self_serve")
    assert _row(await _queue(), org) is not None

    await _verify_kyc(org)
    await _decide(org, decision="approved")

    assert _row(await _queue(), org) is None


async def test_the_queue_says_how_long_the_account_has_been_waiting() -> None:
    """Signup time, ascending: the oldest untouched account is the one at the top.

    Not a `waiting_since` derived per gate — an account is waiting from the moment it
    signed up, and the two gates are both "since you arrived, nobody has looked".
    """
    older = await _tenant("self_serve")
    newer = await _tenant("self_serve")

    rows = (await _queue()).json()
    positions = {row["tenant_id"]: index for index, row in enumerate(rows)}
    assert positions[str(older["id"])] < positions[str(newer["id"])]

    row = _row(await _queue(), older)
    assert row is not None and row["signed_up_at"] is not None


# ------------------------------------------------------------------------ hard rule 6


async def test_the_queue_lists_accounts_and_never_a_person() -> None:
    """Hard rule 6, asserted against the WHOLE response body rather than a field list.

    Everything a person could be identified by lives one click away, on the account's
    own screen, behind the permission that opens it: the document reference, the
    signatory, the reviewer's prose. A work queue needs none of them to say who is
    waiting and on what, and an ops list that carried them would be the widest-read
    surface in the console holding the narrowest data.
    """
    org = await _tenant("self_serve")
    await _verify_kyc(org)
    await _decide(org, decision="rejected")

    response = await _queue()
    body = response.text
    assert CIN not in body, "a business-registry document reference is not queue data"
    assert SIGNATORY not in body, "the signatory is a person"
    assert REVIEW_NOTE not in body, "a reviewer's free text can carry anything into a list"

    row = _row(response, org)
    assert row is not None
    assert set(row) == {"tenant_id", "name", "slug", "plan_tier", "signed_up_at", "holds"}


# ------------------------------------------------------------------------ hard rule 1


async def test_the_admin_guc_still_cannot_read_either_compliance_table() -> None:
    """The claim the design rests on: nothing was widened.

    The queue is a cross-tenant READ built out of per-tenant RLS sessions, so
    `app.admin` opens exactly what migration b57e2f9c4a13 said it opens — the
    directory — and a future query on an admin session cannot drift into reading a KYC
    record because the policy never let it.
    """
    org = await _tenant("self_serve")
    await _verify_kyc(org)
    await _decide(org, decision="approved")

    async with admin_session() as session:
        kyc = (await session.execute(text("SELECT count(*) FROM kyc_records"))).scalar()
        reviews = (
            await session.execute(text("SELECT count(*) FROM first_campaign_reviews"))
        ).scalar()
        orgs = (await session.execute(text("SELECT count(*) FROM organizations"))).scalar()

    assert orgs and orgs >= 1, "the directory is what app.admin is for"
    assert kyc == 0, "app.admin must NOT unlock KYC records"
    assert reviews == 0, "app.admin must NOT unlock first-campaign reviews"


async def test_a_client_realm_session_sees_zero_rows_of_another_tenant() -> None:
    """Cross-tenant zero rows, on the raw session AND through the API.

    The raw halves prove the POLICY: a tenant B session counting tenant A's rows gets
    zero whatever predicate it writes. The route half proves the SURFACE: a client
    token cannot reach the ops queue at all, so the cross-tenant view exists only
    behind a verified admin-realm principal.
    """
    org_a = await _tenant("self_serve")
    org_b = await _tenant("self_serve")
    await _verify_kyc(org_a)
    await _decide(org_a, decision="approved")

    async with tenant_session(uuid.UUID(str(org_b["id"]))) as session:
        kyc = (
            await session.execute(
                text("SELECT count(*) FROM kyc_records WHERE tenant_id = :tid"),
                {"tid": org_a["id"]},
            )
        ).scalar()
        reviews = (
            await session.execute(
                text("SELECT count(*) FROM first_campaign_reviews WHERE tenant_id = :tid"),
                {"tid": org_a["id"]},
            )
        ).scalar()
        orgs = (
            await session.execute(
                text("SELECT count(*) FROM organizations WHERE id = :tid"),
                {"tid": org_a["id"]},
            )
        ).scalar()
    assert (kyc, reviews, orgs) == (0, 0, 0), "tenant B sees nothing of tenant A"

    token = await _make_member(uuid.UUID(str(org_b["id"])))
    async with _client() as http:
        response = await http.get(
            QUEUE_PATH,
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org_b["slug"])},
        )
    assert response.status_code in (401, 403), response.text


# ----------------------------------------------------------------------------- D-22


async def test_the_queue_is_readable_with_a_read_permission() -> None:
    """D-22: no GET may require a permission read-only impersonation refuses.

    `tests/impersonation_reads_test.py` asserts the rule over the whole route table;
    this pins it for the queue by name, because "the ops list of held accounts" is
    exactly the kind of surface that gets reflexively gated on `admin:tenants`.
    """
    from apps.api.core.rbac import iter_api_routes

    declared = {
        route.path: (route.openapi_extra or {}).get("x-calevate-permission")
        for route in iter_api_routes(app)
    }
    assert QUEUE_PATH in declared, f"{QUEUE_PATH} is not mounted"
    assert declared[QUEUE_PATH] not in MUTATING_PERMISSIONS, (
        "a work queue is a read; gating it on a mutating permission hides it from the "
        "read-only console session"
    )


async def test_the_queue_refuses_a_client_realm_token_even_with_the_permission() -> None:
    """`org:read` is held by client roles too. The realm is what separates the two
    surfaces, so the check that matters is the one on the REALM — asserted here rather
    than assumed from `requires(..., realm="admin")`."""
    org = await _tenant("self_serve")
    token = await _make_member(uuid.UUID(str(org["id"])), role="owner")
    async with _client() as http:
        response = await http.get(
            QUEUE_PATH,
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
        )
    assert response.status_code in (401, 403), response.text


# ------------------------------------------------------------- one predicate, not two


async def test_the_queue_asks_the_same_predicate_the_dial_gate_does() -> None:
    """One implementation. The queue's rule names ARE the blockers' rule names, so a
    change to either gate's condition moves the queue with it — and a queue built from
    its own SQL, which is the shape that drifts, would fail this."""
    from apps.api.admin.holds import read_tenant_holds
    from apps.api.compliance.service import first_campaign_hold_blocker, kyc_blocker

    org = await _tenant("self_serve")
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        holds = await read_tenant_holds(session, tenant_id=tenant_id)
        kyc = await kyc_blocker(session, tenant_id=tenant_id)
        review = await first_campaign_hold_blocker(session, tenant_id=tenant_id)

    assert kyc is not None and review is not None
    assert holds.rules == (kyc[0], review[0])
    assert holds.held is True


async def test_the_tenant_directory_carries_the_same_flag() -> None:
    """The queue is the triage view; the DIRECTORY is where an operator already is.

    Both read `read_tenant_holds` on the tenant's own session, so a client cannot be
    flagged on one screen and clear on the other — which is the failure mode a second
    'is this tenant waiting' query, written in SQL for the list, would eventually have.
    """
    org = await _tenant("self_serve")
    await _verify_kyc(org)
    token = await _make_admin()

    async with _client() as http:
        record = await http.get(
            f"/v1/admin/tenants/{org['id']}", headers={"Authorization": f"Bearer {token}"}
        )
    assert record.status_code == 200, record.text
    assert record.json()["holds"] == ["first_campaign_review_pending"]

    row = _row(await _queue(token), org)
    assert row is not None and row["holds"] == record.json()["holds"]
