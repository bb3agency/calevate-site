"""The first-campaign hold — R-11's last outstanding mitigation (D-34, FLOWS §2, BRD §245).

Three documents said the same thing and no code did it: "the first campaign of every
self-serve account is held for manual review". There was no flag, no queue and no
blocker; `tenancy/signup.py` named the requirement in prose. These tests pin the
properties that make it a control rather than a sentence.

1. **The gap itself.** A self-serve tenant's first campaign does not dial until a human
   releases it — proved through the client's own launch route, on a campaign that is
   green on every OTHER gate, so the hold is the only thing standing in the way.
2. **"First" is a property of the ACCOUNT, not of a campaign row.** Launching a second
   campaign while the first is held does not skip it, and deleting the held campaign
   does not clear it. Both are the ways a campaign-scoped flag would be trivially
   defeated.
3. **Released once, released for good.** After a human releases the account, the second
   campaign launches with no review blocker — the mitigation is "the FIRST campaign is
   reviewed", not "every campaign needs a signature forever".
4. **Self-serve only.** Same tier line as the wallet and the KYC dial gate
   (`SELF_SERVE_TIERS`), because R-11's risk is an anonymous signup dialling India's
   network — not a managed client we contracted with.
5. **A human, from the admin realm, audited** — and a rejection tells the client why.
   Reversing a rejection is a new decision with its own audit row (hard rule 4's spirit:
   the ledger that carries this history is `audit_log`, and it is append-only).
6. **Hard rule 1.** Cross-tenant zero rows, through the route and on the raw session.

There is no bypass and no `for_testing` flag anywhere in the path: every test that wants
a released account SUPPLIES the release through the audited ops route, the way
`tests/kyc_gate_test.py` supplies a verification.

Run: uv run pytest -q tests/first_campaign_review_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import service as billing
from apps.api.campaigns import service as campaigns
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = [pytest.mark.rls]

CLIENT_PATH = "/v1/compliance/first-campaign-review"
PENDING_RULE = "first_campaign_review_pending"
REJECTED_RULE = "first_campaign_review_rejected"
# A CIN is 21 characters — the KYC record this fixture files needs a real registry shape.
CIN = "U74999TG2026PTC123456"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST. The calling-hours rule is not what this suite measures, and a suite
    that only passes between 09:00 and 21:00 IST is a flake with a schedule."""
    monkeypatch.setattr(
        "apps.api.compliance.service.ist_now",
        lambda: datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30),
    )


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
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


async def _tenant(plan_tier: str = "self_serve") -> dict[str, Any]:
    """A tenant on the given motion, with a live outbound agent and an active PE
    registration — everything the launch gate asks for EXCEPT the review."""
    created = await admin_service.create_organization(
        name="Hold Motors",
        slug=f"hold-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        if plan_tier != "managed":
            # Inside the tenant's own session: `organizations` is RLS'd on
            # `app.tenant_id`, so an untenanted UPDATE matches zero rows silently.
            result = await session.execute(
                text("UPDATE organizations SET plan_tier = :tier WHERE id = :tid"),
                {"tier": plan_tier, "tid": tenant_id},
            )
            assert result.rowcount == 1, "plan_tier must actually change for this fixture"
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :aid"),
            {"aid": created["agent_id"]},
        )
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Hold Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
        # A self-serve tenant with an empty wallet is refused by `no_credits` long
        # before the review is consulted, and this suite is not about the wallet.
        await billing.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500.00"), reason="topup"
        )
    return created


async def _headers(org: dict[str, Any], role: str = "owner") -> dict[str, str]:
    token = await _make_member(uuid.UUID(str(org["id"])), role=role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


async def _verify_kyc(org: dict[str, Any]) -> None:
    """Through the audited ops route, never by writing the row — the KYC dial gate is a
    separate R-11 mitigation and it would otherwise mask this one."""
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
                "signatory_name": "A Signatory",
                "evidence_ref": "ops-ticket-4471",
            },
        )
    assert response.status_code == 200, response.text


async def _decide(
    org: dict[str, Any],
    *,
    decision: str,
    note: str = "Reviewed the list, the script and the disclosure line. Clean.",
    campaign_id: uuid.UUID | None = None,
    token: str | None = None,
) -> Any:
    """Release (or refuse) the account the way ops does: admin realm, audited."""
    token = token or await _make_admin()
    payload: dict[str, Any] = {"decision": decision, "note": note}
    if campaign_id is not None:
        payload["reviewed_campaign_id"] = str(campaign_id)
    async with _client() as http:
        return await http.post(
            f"/v1/admin/tenants/{org['id']}/first-campaign-review",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )


async def _campaign(
    org: dict[str, Any], *, name: str = "Diwali offers", phones: tuple[str, ...] = ("9876500001",)
) -> uuid.UUID:
    """A campaign that is green on every gate except the one under test."""
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": f"+9180{uuid.uuid4().int % 10**8:08d}"},
        )
        template_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {
                "id": template_id,
                "tid": tenant_id,
                "body": "Hello from {#var#}, this is an AI assistant calling about your enquiry.",
            },
        )
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=uuid.UUID(str(org["agent_id"])),
            name=name,
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=2,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await campaigns.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
        )
    return campaign_id


async def _ready(plan_tier: str = "self_serve") -> tuple[dict[str, Any], uuid.UUID]:
    org = await _tenant(plan_tier)
    await _verify_kyc(org)
    return org, await _campaign(org)


async def _launch(org: dict[str, Any], campaign_id: uuid.UUID) -> Any:
    async with _client() as http:
        return await http.post(f"/v1/campaigns/{campaign_id}/launch", headers=await _headers(org))


def _rules(response: Any) -> set[str]:
    """The blocker rule names inside a `campaign_launch_blocked` problem+json."""
    return {field["rule"] for field in response.json().get("fields", [])}


# ------------------------------------------------------------------- the gap itself


async def test_a_self_serve_accounts_first_campaign_does_not_dial_until_a_human_releases_it() -> (
    None
):
    """THE test. Everything else on this campaign is green: verified business, funded
    wallet, active PE registration and TM link, approved template of the right
    classification, a registered 140 number, contacts with a consent provenance. The
    only thing between it and India's phone network is a human, and that is the whole
    point of R-11's last mitigation.
    """
    org, campaign_id = await _ready()

    blocked = await _launch(org, campaign_id)
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["type"].rsplit("/", 1)[-1] == "campaign_launch_blocked"
    assert _rules(blocked) == {PENDING_RULE}, "the hold must be the ONLY thing blocking"

    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
            )
        ).scalar()
    assert status == "draft", "a held campaign never reaches running"

    released = await _decide(org, decision="approved", campaign_id=campaign_id)
    assert released.status_code == 200, released.text

    launched = await _launch(org, campaign_id)
    assert launched.status_code == 200, launched.text
    assert launched.json()["status"] == "running"


async def test_the_client_can_read_the_blocker_before_they_hit_it() -> None:
    """SURFACES §2b: a blocked feature is visibly explained, not silently missing. The
    launch preview names the hold, and the reason says what happens next."""
    org, campaign_id = await _ready()
    async with _client() as http:
        preview = await http.get(
            f"/v1/campaigns/{campaign_id}/launch-check", headers=await _headers(org)
        )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["ready"] is False
    blockers = {b["rule"]: b["reason"] for b in body["blockers"]}
    assert PENDING_RULE in blockers
    assert "review" in blockers[PENDING_RULE].lower()


async def test_the_account_can_see_its_own_hold_and_what_it_means() -> None:
    """The page somebody opens exactly when they are already blocked."""
    org, campaign_id = await _ready()
    async with _client() as http:
        held = await http.get(CLIENT_PATH, headers=await _headers(org))
    assert held.status_code == 200, held.text
    assert held.json()["held"] is True
    assert held.json()["status"] is None, "never reviewed is an absence, not a status"

    await _decide(org, decision="approved", campaign_id=campaign_id)
    async with _client() as http:
        released = await http.get(CLIENT_PATH, headers=await _headers(org))
    assert released.json()["held"] is False
    assert released.json()["status"] == "approved"
    assert released.json()["decided_at"] is not None


# ------------------------------------------------- "first" is the ACCOUNT's, not a row's


async def test_launching_a_second_campaign_does_not_skip_the_hold() -> None:
    """The obvious defeat of a campaign-scoped flag: flag campaign #1, launch #2. The
    hold is a property of the ACCOUNT, so both are refused by the same rule."""
    org, first = await _ready()
    second = await _campaign(org, name="Second try", phones=("9876500002",))

    for campaign_id in (first, second):
        response = await _launch(org, campaign_id)
        assert response.status_code == 422, response.text
        assert PENDING_RULE in _rules(response), campaign_id


async def test_deleting_the_reviewed_campaign_does_not_clear_the_hold() -> None:
    """The other defeat: throw away the campaign under review and build a fresh one.
    Nothing about the hold is anchored to a campaign row, so there is nothing to
    throw away."""
    org, first = await _ready()
    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        await session.execute(
            text("DELETE FROM campaign_contacts WHERE campaign_id = :cid"), {"cid": first}
        )
        await session.execute(text("DELETE FROM campaigns WHERE id = :cid"), {"cid": first})

    replacement = await _campaign(org, name="Fresh start", phones=("9876500003",))
    response = await _launch(org, replacement)
    assert response.status_code == 422, response.text
    assert PENDING_RULE in _rules(response)


async def test_a_released_account_launches_its_second_campaign_unheld() -> None:
    """ "The FIRST campaign is reviewed" — not "every campaign needs a signature". One
    review per account, and everything after it is on the ordinary gates."""
    org, first = await _ready()
    await _decide(org, decision="approved", campaign_id=first)
    assert (await _launch(org, first)).status_code == 200

    second = await _campaign(org, name="Second campaign", phones=("9876500004",))
    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        blockers = await campaigns.launch_blockers(
            session, tenant_id=uuid.UUID(str(org["id"])), campaign_id=second
        )
    assert {b.rule for b in blockers} == set(), [b.rule for b in blockers]

    launched = await _launch(org, second)
    assert launched.status_code == 200, launched.text


# ------------------------------------------------------------------ the tier line


async def test_a_managed_tenant_is_never_held() -> None:
    """Same line as the wallet and the KYC dial gate (`SELF_SERVE_TIERS`). R-11's risk
    is an anonymous signup; a managed client was onboarded by a human already, and
    holding them would halt existing clients on a control aimed at strangers."""
    org, campaign_id = await _ready("managed")
    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        blockers = await campaigns.launch_blockers(
            session, tenant_id=uuid.UUID(str(org["id"])), campaign_id=campaign_id
        )
    assert PENDING_RULE not in {b.rule for b in blockers}
    assert (await _launch(org, campaign_id)).status_code == 200


async def test_a_trial_tenant_is_held_like_a_self_serve_one() -> None:
    """`SELF_SERVE_TIERS` has two members and both signed up unattended."""
    org, campaign_id = await _ready("trial")
    response = await _launch(org, campaign_id)
    assert response.status_code == 422, response.text
    assert PENDING_RULE in _rules(response)


# ------------------------------------------------------- dial time, not only launch time


async def test_a_revoked_release_stops_a_running_campaign_at_the_next_tick() -> None:
    """The launch gate is a photograph; a campaign runs for days. `dispatch_blockers`
    re-asks the paperwork every tick, and an account whose release is withdrawn after a
    problem surfaces must stop dialling — not finish the list first."""
    org, campaign_id = await _ready()
    tenant_id = uuid.UUID(str(org["id"]))
    await _decide(org, decision="approved", campaign_id=campaign_id)
    assert (await _launch(org, campaign_id)).status_code == 200

    async with tenant_session(tenant_id) as session:
        assert not await campaigns.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

    revoked = await _decide(
        org, decision="rejected", note="Complaints from three called numbers; list is bought."
    )
    assert revoked.status_code == 200, revoked.text

    async with tenant_session(tenant_id) as session:
        blockers = await campaigns.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert REJECTED_RULE in {b.rule for b in blockers}


# ---------------------------------------------------------- the decision, and reversing it


async def test_a_refusal_tells_the_client_why() -> None:
    """ "Rejected, no reason given" is the support ticket nobody can close — the same
    argument `kyc_records.rejection_reason` is built on."""
    org, campaign_id = await _ready()
    await _decide(org, decision="rejected", note="The contact list has no traceable consent.")

    response = await _launch(org, campaign_id)
    assert response.status_code == 422, response.text
    reasons = {f["rule"]: f["message"] for f in response.json()["fields"]}
    assert REJECTED_RULE in reasons
    assert "traceable consent" in reasons[REJECTED_RULE]

    async with _client() as http:
        view = await http.get(CLIENT_PATH, headers=await _headers(org))
    assert view.json()["status"] == "rejected"
    assert "traceable consent" in view.json()["decision_note"]


async def test_reversing_a_refusal_is_a_new_decision_and_a_new_audit_row() -> None:
    """Hard rule 4's spirit: the ledger carrying this history is `audit_log`, which is
    INSERT-only, so a reversal adds a row rather than editing one. The review record
    itself is the CURRENT state, the way `kyc_records` and `dlt_registrations` are."""
    org, campaign_id = await _ready()
    await _decide(org, decision="rejected", note="Script did not disclose the AI agent.")
    await _decide(org, decision="approved", note="Disclosure fixed and re-read; released.")

    assert (await _launch(org, campaign_id)).status_code == 200

    async with untenanted_session() as session:
        entries = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :tid "
                    "AND action = 'first_campaign_review.decided'"
                ),
                {"tid": org["id"]},
            )
        ).scalar()
    # Two decisions, two entries. `audit_log` has no summary column (the decision detail
    # goes to the JSONL stream keyed by entry id, BACKEND-PATTERNS §7), so what is
    # asserted here is the property hard rule 4 is about: the second decision did not
    # replace the first one's record of itself.
    assert entries == 2

    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        current = (
            await session.execute(
                text(
                    "SELECT status, decision_note FROM first_campaign_reviews "
                    "WHERE tenant_id = :tid"
                ),
                {"tid": org["id"]},
            )
        ).first()
    assert current is not None
    assert current[0] == "approved", "the row is the CURRENT state, not the history"
    assert "Disclosure fixed" in current[1]


async def test_the_decision_names_the_operator_who_made_it() -> None:
    """An auditor asks WHO. A row that cannot resolve to a person is not an answer,
    which is why `decided_by_admin_id` is an `admin_users.id` and not a typed name."""
    org, _ = await _ready()
    await _decide(org, decision="approved")

    async with tenant_session(uuid.UUID(str(org["id"]))) as session:
        row = (
            await session.execute(
                text(
                    "SELECT r.decision_source, a.name FROM first_campaign_reviews r "
                    "JOIN admin_users a ON a.id = r.decided_by_admin_id WHERE r.tenant_id = :tid"
                ),
                {"tid": org["id"]},
            )
        ).first()
    assert row is not None, "an operator decision must name its operator"
    assert row[0] == "operator"


async def test_the_database_refuses_an_operator_decision_with_no_operator() -> None:
    """The route validates so an operator gets a named field; the DATABASE is the
    enforcement, so a writer that skipped the route cannot store an anonymous release."""
    org = await _tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(uuid.UUID(str(org["id"]))) as session:
            await session.execute(
                text(
                    "INSERT INTO first_campaign_reviews (id, tenant_id, status, decision_note, "
                    "  decision_source, decided_at, created_at, updated_at) "
                    "VALUES (:id, :tid, 'approved', 'released', 'operator', now(), now(), now())"
                ),
                {"id": uuid7(), "tid": org["id"]},
            )


async def test_a_decision_must_say_what_was_reviewed() -> None:
    """An empty note is a release nobody can account for later."""
    org = await _tenant()
    response = await _decide(org, decision="approved", note="   ")
    assert response.status_code == 422, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "first_campaign_review_note_required"


async def test_a_client_cannot_release_its_own_account() -> None:
    """The whole control is that a HUMAN AT CALEVATE looked. A client-realm token on the
    ops route is refused by the realm, not by a permission that could be granted."""
    org, _ = await _ready()
    headers = await _headers(org)
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/first-campaign-review",
            headers=headers,
            json={"decision": "approved", "note": "please"},
        )
    assert response.status_code in (401, 403), response.text


# ------------------------------------------------------------------------- hard rule 1


async def test_tenant_b_cannot_see_tenant_as_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cross-tenant zero rows, through the route AND on the raw RLS-scoped session — so
    an endpoint that filtered in Python would still fail this."""
    del monkeypatch
    org_a = await _tenant()
    org_b = await _tenant()
    await _decide(org_a, decision="approved")

    async with _client() as http:
        response = await http.get(CLIENT_PATH, headers=await _headers(org_b))
    assert response.status_code == 200, response.text
    assert response.json()["status"] is None, "tenant B must not see tenant A's decision"

    async with tenant_session(uuid.UUID(str(org_b["id"]))) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM first_campaign_reviews WHERE tenant_id = :tid"),
                {"tid": org_a["id"]},
            )
        ).scalar()
    assert rows == 0


# --------------------------------------------------------------------- no bypass exists


async def test_the_gate_has_no_test_shaped_escape_hatch() -> None:
    """Hard rule 5, as an assertion: the predicate takes a session and a tenant, and
    nothing else. A `for_testing` or `skip_review` parameter is the single most likely
    cause of a self-serve account dialling unreviewed in production."""
    import inspect

    from apps.api.compliance.service import first_campaign_hold_blocker

    parameters = set(inspect.signature(first_campaign_hold_blocker).parameters)
    assert parameters == {"session", "tenant_id"}, parameters


async def test_launch_campaign_raises_the_hold_rather_than_logging_it() -> None:
    """The service, not just the route: `launch_campaign` is what the dispatcher's
    upstream callers use, and it must refuse rather than warn."""
    org, campaign_id = await _ready()
    tenant_id = uuid.UUID(str(org["id"]))
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert raised.value.code == "campaign_launch_blocked"


async def test_a_release_cannot_cite_another_tenants_campaign_as_the_thing_reviewed() -> None:
    """`reviewed_campaign_id` must name a campaign of the tenant being released, or the
    decision is refused as not-found.

    The evidence field is the whole point of the review: it records WHICH list, script
    and disclosure line a human actually read before letting a self-serve account dial
    strangers. A pointer at another tenant's campaign records that a human reviewed
    something they were never shown — and the foreign key alone would have accepted it,
    because `campaigns.id` is globally unique and says nothing about whose it is. RLS
    inside the operator's scoped session is what turns that into a 404.

    404 rather than 422 is also the tenancy answer: under RLS "no such campaign" and
    "another tenant's campaign" are deliberately the same sentence.
    """
    org, campaign_id = await _ready()
    neighbour, neighbours_campaign = await _ready()
    assert str(org["id"]) != str(neighbour["id"])

    refused = await _decide(org, decision="approved", campaign_id=neighbours_campaign)

    assert refused.status_code == 404, refused.text
    assert "campaign" in refused.json()["title"].lower()

    # Nothing was recorded, so the account is still held and still cannot dial.
    blocked = await _launch(org, campaign_id)
    assert blocked.status_code == 422, blocked.text
    assert "first_campaign_review_pending" in _rules(blocked)
