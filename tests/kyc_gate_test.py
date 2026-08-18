"""Subscriber KYC — R-11's last mitigation, end to end (SURFACES §2b, FLOWS §2).

"Number purchase + KYC: gated; calling stays disabled until verification clears" was a
sentence in a document with nothing behind it: no table, no blocker, no route. These
tests pin the five properties that make it a control rather than a claim.

1. **The gate is where every outbound path already converges.** Not a new check bolted
   onto one caller — `compliance.service.check_dispatch`, which the "call this lead"
   button, the instant-callback webhook and the campaign dispatcher all pass through,
   plus `campaigns.service.launch_blockers` as the preview a client sees BEFORE they
   hit it.
2. **Inbound is not gated.** `check_dispatch` is outbound-only by construction and an
   inbound agent is refused by `agent_inbound_only` long before KYC is consulted; the
   receptionist D-38 leads with cannot be silenced by a paperwork state.
3. **Managed tenants keep dialling; self-serve tenants do not.** The DIAL gate is
   tier-conditional and the PROVISIONING gate is not — the argument for that split is
   in `apps/api/compliance/kyc.py`, and both halves are asserted here.
4. **The record answers the auditor and the support person.** What was verified,
   against what reference, by whom, when — and why an account was rejected. The
   database refuses a `verified` row that cannot say, and a `rejected` row that cannot
   explain.
5. **Hard rule 1.** Cross-tenant zero rows, through the route and on the raw session.

Run: uv run pytest -q tests/kyc_gate_test.py
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = [pytest.mark.rls]

PATH = "/v1/compliance/kyc"
PURCHASE_PATH = "/v1/numbers/purchase"
# A CIN is 21 characters; nothing in the permitted document set is a bare 12 digits.
CIN = "U74999TG2026PTC123456"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
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


async def _tenant(plan_tier: str = "managed") -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="KYC Motors",
        slug=f"kyc-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    if plan_tier != "managed":
        # Inside the tenant's own session: `organizations` is RLS'd on `app.tenant_id`,
        # so an untenanted UPDATE here silently matches zero rows and the test would
        # quietly assert against a `managed` tenant.
        async with tenant_session(uuid.UUID(str(created["id"]))) as session:
            result = await session.execute(
                text("UPDATE organizations SET plan_tier = :tier WHERE id = :tid"),
                {"tier": plan_tier, "tid": created["id"]},
            )
            assert result.rowcount == 1, "plan_tier must actually change for this fixture"
    return created


async def _headers(org: dict[str, Any], role: str = "owner") -> dict[str, str]:
    token = await _make_member(uuid.UUID(str(org["id"])), role=role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


async def _record(org: dict[str, Any], **payload: Any) -> Any:
    """File the record the way production does — through the audited ops route, never
    by writing the row here. A test that seeds its own row passes against a schema the
    writer no longer produces."""
    token = await _make_admin()
    async with _client() as http:
        return await http.post(
            f"/v1/admin/tenants/{org['id']}/kyc",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )


async def _verify(org: dict[str, Any]) -> None:
    response = await _record(
        org,
        status="verified",
        entity_type="private_limited",
        document_kind="cin",
        document_ref=CIN,
        signatory_name="A Signatory",
        evidence_ref="ops-ticket-4471",
    )
    assert response.status_code == 200, response.text


async def _agent(tenant_id: uuid.UUID, *, direction: str = "outbound") -> uuid.UUID:
    """A live agent with a disclosure line, so the dispatch gate reaches the tenant
    questions instead of stopping at the agent ones."""
    agent_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, created_at, "
                "updated_at) VALUES (:id, :tid, 'Gate agent', :dir, 'live', 'te-IN', 'This is an "
                "AI assistant and this call is recorded.', 'This is an AI assistant and this call "
                "is recorded.', 'This call is being recorded.', now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "dir": direction},
        )
    return agent_id


# ----------------------------------------------------- the gate every path converges on


async def test_a_self_serve_tenant_with_no_kyc_cannot_dial() -> None:
    """`check_dispatch` is the ONE function every outbound path calls (hard rule 5), so
    the gate lands there and every caller inherits it — no new place to forget."""
    from apps.api.compliance.service import check_dispatch

    org = await _tenant("self_serve")
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000001"
        )

    assert decision.allowed is False
    assert decision.rule == "kyc_missing"
    assert "verified" in (decision.reason or "")


async def test_verifying_the_business_lets_it_dial() -> None:
    """The gate opens on the fact it names, and on nothing else."""
    from apps.api.compliance.service import check_dispatch

    org = await _tenant("self_serve")
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    await _verify(org)

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000002"
        )

    # `no_credits` is the NEXT gate for a self-serve tenant with an empty wallet, which
    # is the correct thing to be blocked on once identity is settled. What must not
    # survive is a KYC rule.
    assert decision.rule != "kyc_missing"
    assert decision.rule != "kyc_not_verified"


async def test_a_rejected_verification_names_its_state_not_just_its_absence() -> None:
    """`submitted`, `rejected` and `expired` send a client to three different places, so
    the refusal interpolates the state rather than saying "not verified" three times."""
    from apps.api.compliance.service import check_dispatch

    org = await _tenant("self_serve")
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    response = await _record(
        org, status="rejected", rejection_reason="The GSTIN belongs to a different entity."
    )
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000003"
        )

    assert decision.rule == "kyc_not_verified"
    assert "rejected" in (decision.reason or "")


async def test_the_launch_preview_names_the_same_blocker_before_the_client_hits_it() -> None:
    """SURFACES §2b wants a blocker a client can SEE, not discover on the first dial —
    the shape `tm_registration_missing` and `pe_registration_*` already follow."""
    from apps.api.campaigns import service as campaigns

    org = await _tenant("self_serve")
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "  status, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, 'Gate campaign', 'promotional', 'draft', "
                "  now(), now())"
            ),
            {"id": campaign_id, "tid": tenant_id, "aid": agent_id},
        )
        blockers = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

    assert "kyc_missing" in {blocker.rule for blocker in blockers}


# ----------------------------------------------------------------- inbound is not gated


async def test_an_inbound_agent_is_never_refused_for_kyc() -> None:
    """D-38's headline product cannot be silenced by a paperwork state. The gate is
    outbound-only by construction — inbound calls never enter `check_dispatch` at all —
    and an inbound agent that somehow reaches it stops at `agent_inbound_only`, which
    is a statement about the agent, not a block on answering."""
    from apps.api.compliance.service import check_dispatch

    org = await _tenant("self_serve")
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id, direction="inbound")

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000004"
        )

    assert decision.rule == "agent_inbound_only"
    assert decision.rule not in ("kyc_missing", "kyc_not_verified")


# --------------------------------------------------------------- managed vs self-serve


async def test_a_managed_tenant_with_no_kyc_still_dials() -> None:
    """The dial gate is tier-conditional, exactly like `credits_exhausted`.

    A managed tenant's identity was verified out of band before we bought their number,
    and is already gated at dial time by `pe_registration_*`. Widening this gate would
    not close a risk; it would halt every existing client on a data-entry backlog. The
    reasoning is in `apps/api/compliance/kyc.py`; this test is what fails if someone
    "tidies" the tier test away.
    """
    from apps.api.compliance.service import check_dispatch

    org = await _tenant("managed")
    tenant_id = uuid.UUID(str(org["id"]))
    agent_id = await _agent(tenant_id)

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000005"
        )

    assert decision.rule not in ("kyc_missing", "kyc_not_verified")


async def test_buying_a_number_is_gated_for_a_managed_tenant_too() -> None:
    """The PROVISIONING gate has no tier test at all, and that is the half that closes
    the risk: the DoT business-connection obligation attaches to the connection and has
    no managed-client exemption. Keying it on `plan_tier` — an admin-settable column —
    would put a legal control one support ticket away from being switched off."""
    org = await _tenant("managed")
    async with _client() as http:
        response = await http.post(
            PURCHASE_PATH, headers=await _headers(org), json={"series": "160", "city": "Hyderabad"}
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "kyc_not_verified"


async def test_a_verified_tenant_is_refused_by_the_seam_and_nothing_is_written() -> None:
    """Past the client-side gate, the honest hole: no telephony credentials and no
    provisioning adapter (D-05 is a decision, not a credential). The refusal is
    problem+json and allocates nothing — no number row appears."""
    org = await _tenant("self_serve")
    await _verify(org)

    async with _client() as http:
        response = await http.post(
            PURCHASE_PATH, headers=await _headers(org), json={"series": "140", "city": "Hyderabad"}
        )

    # 502: `kind="dependency"` in the error ladder, the same status the Razorpay seam's
    # `payments_not_configured` answers with — a capability this deployment does not
    # have is an upstream gap, not the client's mistake.
    assert response.status_code == 502, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "number_provisioning_not_configured", (
        response.text
    )

    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        count = (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar()
    assert count == 0, "a refused purchase must write nothing"


async def test_the_unimplemented_claim_is_a_constant_not_a_comment() -> None:
    """`PROVISIONING_IMPLEMENTED` is greppable and testable, the same device
    `ingest.meta.LEAD_RETRIEVAL_IMPLEMENTED` and `payments.PROVIDER_CREATES_ORDERS`
    use. Flipping it is not a config change — it means somebody wrote an adapter, and
    this test is the tripwire that says so."""
    from apps.api.campaigns import provisioning

    assert provisioning.PROVISIONING_IMPLEMENTED is False
    assert provisioning.number_purchase_available() is False
    # ONE selector, and every caller shares it: a second read of settings cannot
    # disagree with the route, because there is no second read.
    assert provisioning.number_provisioning_capability().available is False


# ------------------------------------------------------- what the auditor and support ask


async def test_a_verified_record_must_say_what_was_verified() -> None:
    """The route refuses first so an operator gets a named field..."""
    org = await _tenant()
    response = await _record(org, status="verified", document_kind="cin")
    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "kyc_document_required"


async def test_the_database_refuses_a_verified_record_with_no_evidence() -> None:
    """...and the DATABASE is the enforcement, so a writer that skipped the route
    cannot store a verification nobody performed."""
    org = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(uuid.UUID(str(org["id"]))) as session:
            await session.execute(
                text(
                    "INSERT INTO kyc_records (id, tenant_id, status, created_at, updated_at) "
                    "VALUES (:id, :tid, 'verified', now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": org["id"]},
            )


async def test_a_rejection_must_say_why() -> None:
    """ "Rejected, no reason recorded" is the support ticket nobody can close."""
    org = await _tenant()
    response = await _record(org, status="rejected")
    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "kyc_rejection_reason_required"


async def test_the_document_reference_cannot_be_an_aadhaar() -> None:
    """No permitted registry identifier is twelve bare digits, so a value shaped like
    one is personal data being pasted into a business field. Backstop, not the control —
    the control is that the enum names only entity registries — but it fails at the
    moment of the mistake rather than in a breach report."""
    org = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(uuid.UUID(str(org["id"]))) as session:
            await session.execute(
                text(
                    "INSERT INTO kyc_records (id, tenant_id, status, document_kind, "
                    "  document_ref, created_at, updated_at) "
                    "VALUES (:id, :tid, 'submitted', 'gstin', '123456789012', now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": org["id"]},
            )


async def test_the_record_says_what_by_whom_and_when() -> None:
    """The auditor's four questions. `verified_at` is stamped by the database and
    `verified_by_admin_id` is a resolvable actor, not a typed-in name."""
    org = await _tenant()
    await _verify(org)

    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        row = (
            await session.execute(
                text(
                    "SELECT k.document_kind, k.document_ref, k.verified_at, a.name "
                    "FROM kyc_records k JOIN admin_users a ON a.id = k.verified_by_admin_id "
                    "WHERE k.tenant_id = :tid"
                ),
                {"tid": org["id"]},
            )
        ).first()

    assert row is not None, "a verified record must resolve to the person who verified it"
    assert row[0] == "cin"
    assert row[1] == CIN
    assert row[2] is not None


async def test_dropping_out_of_verified_clears_the_verification() -> None:
    """An expired record must not keep displaying the credentials of a verification
    that no longer holds — and the gate must close again."""
    from apps.api.compliance.kyc import read_kyc

    org = await _tenant("self_serve")
    tenant_id = uuid.UUID(str(org["id"]))
    await _verify(org)
    response = await _record(org, status="expired")
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)

    assert record.is_verified is False
    assert record.verified_at is None
    # The evidence of WHAT we once checked survives, because an auditor asks about the
    # past; only the claim that it is currently good is withdrawn.
    assert record.document_ref == CIN


# --------------------------------------------------------------------- the client read


async def test_a_tenant_with_nothing_on_file_gets_its_absence_as_data() -> None:
    org = await _tenant()
    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recorded"] is False
    assert body["status"] is None
    assert body["is_verified"] is False
    assert body["number_purchase_available"] is False


async def test_staff_may_read_it_too() -> None:
    """`org:read`, not `org:manage`: looking at your own compliance state is not
    changing it, and it must stay visible inside a read-only impersonation (D-22)."""
    org = await _tenant()
    await _verify(org)
    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org, role="staff"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_verified"] is True
    assert body["document_ref"] == CIN
    assert body["rejection_reason"] is None
    # Verified, but there is still no provider — the screen must not offer a button the
    # purchase route refuses, which is why both read the same selector.
    assert body["number_purchase_available"] is False


async def test_the_read_is_not_gated_on_a_permission_impersonation_refuses() -> None:
    declared = {
        route.path: (route.openapi_extra or {}).get("x-calevate-permission")
        for route in iter_api_routes(app)
        if route.methods in ({"GET"}, {"GET", "HEAD"})
    }
    assert declared.get(PATH) == "org:read", declared.get(PATH)
    assert "org:read" not in MUTATING_PERMISSIONS


async def test_there_is_no_client_route_that_writes_a_kyc_record() -> None:
    """A business that could mark its own identity verified would be marking the
    telecom gate green on a check nobody performed — a sharper version of the argument
    that keeps `record_dlt_registration` admin-only, because this gate is what stands
    between an anonymous signup and a phone connection."""
    writers = [
        (sorted(route.methods or []), route.path)
        for route in iter_api_routes(app)
        if route.path.rstrip("/").endswith("kyc")
        and not route.path.startswith("/v1/admin")
        and route.methods not in ({"GET"}, {"GET", "HEAD"})
    ]
    assert writers == [], writers


# ------------------------------------------------------------------------ hard rule 1


async def test_tenant_b_cannot_see_tenant_as_kyc_record() -> None:
    """Cross-tenant zero rows, at BOTH levels: through the endpoint, and on the raw
    RLS-scoped session — an endpoint that filtered in Python would pass the first
    assertion while leaving isolation to a WHERE clause someone can forget."""
    from apps.api.compliance.kyc import read_kyc

    tenant_a = await _tenant()
    tenant_b = await _tenant()
    await _verify(tenant_a)

    async with _client() as http:
        mine = await http.get(PATH, headers=await _headers(tenant_a))
        theirs = await http.get(PATH, headers=await _headers(tenant_b))

    # Ground truth from the owning tenant, so a policy that hid a tenant's OWN row would
    # fail here rather than passing as "isolated".
    assert mine.json()["document_ref"] == CIN
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["recorded"] is False
    assert theirs.json()["document_ref"] is None

    async with tenant_session(uuid.UUID(str(tenant_b["id"]))) as session:
        leaked = await read_kyc(session, tenant_id=uuid.UUID(str(tenant_a["id"])))
    assert leaked.recorded is False, "the RLS session must return zero rows for another tenant"

    async with untenanted_session() as session:
        blind = await read_kyc(session, tenant_id=uuid.UUID(str(tenant_a["id"])))
    assert blind.recorded is False, "no GUC ⇒ zero rows (fail closed)"


async def test_is_verified_is_false_for_a_rejection_which_is_a_filed_record() -> None:
    """`read_kyc(...).is_verified` — the value `provisioning.py` gates on — must be
    False for every state that is not a live verification, INCLUDING a rejection.

    A rejection is the dangerous one: it is a FILED record, so any check shaped like
    "do we have something on file?" reads it as satisfied. Getting that wrong buys a
    phone number for a business nobody cleared, and the DLT registration behind that
    number is one TRAI holds Calevate liable for.

    Written through the real recording route rather than a raw INSERT, because the
    table's CHECKs are the guarantee here — a `verified` row must name what, against
    what, by whom and when — and a test that bypassed them would pin the boolean while
    saying nothing about the evidence behind it.
    """
    from apps.api.compliance.kyc import read_kyc

    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))

    async with tenant_session(tenant_id) as session:
        assert (await read_kyc(session, tenant_id=tenant_id)).is_verified is False, (
            "nothing on file is not verified"
        )

    rejected = await _record(
        org,
        status="rejected",
        rejection_reason="the signatory named is not a director of the entity",
    )
    assert rejected.status_code == 200, rejected.text
    async with tenant_session(tenant_id) as session:
        record = await read_kyc(session, tenant_id=tenant_id)
    assert record.recorded is True, "a rejection IS on file — that is what makes it risky"
    assert record.is_verified is False, "a rejected record is filed, and filed is not cleared"

    await _verify(org)
    async with tenant_session(tenant_id) as session:
        assert (await read_kyc(session, tenant_id=tenant_id)).is_verified is True
