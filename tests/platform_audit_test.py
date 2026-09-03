"""Platform audit: onboarding, invitations, the KB workflow, the ops switches.

Every test here started as a reproduction. The properties under test are the ones a
half-finished tenant, a resurrected identity, an un-rollback-able knowledge base or an
escaped outbound halt would each break in a way no other suite notices.

Harnesses are borrowed from the suites that already own these surfaces
(`admin_security_test`, `kb_workflow_test`) rather than re-invented — a second definition
of "make me an admin" is a second thing to keep true.

Concurrency note: other suites run against the same database, so everything here is
scoped to its own run-unique tenant/slug. Exactly ONE test moves the global
`platform_state` row, for as few statements as possible, and restores it in `finally`
(the pattern `campaigns_test` established); the step-up test asserts only refusals, so
it never moves the switch at all.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session, tenant_session
from apps.api.kb import service as kb_service
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.conftest import accept_agreements
from tests.kb_workflow_test import _tenant_with_published_agent


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _run_slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _org_exists(slug: str) -> bool:
    async with admin_session() as session:
        row = (
            await session.execute(text("SELECT 1 FROM organizations WHERE slug = :s"), {"s": slug})
        ).first()
    return row is not None


# --------------------------------------------------------------------------------
# 1. Onboarding: a complete tenant or nothing
# --------------------------------------------------------------------------------


async def test_a_wizard_failure_after_the_agent_leaves_no_tenant_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline property of FLOWS §1: org created + agent created + extraction
    schema NOT created must roll back to nothing.

    A tenant with an agent and no schema produces leads with no columns, and the
    post-call pipeline would happily process calls for it — worse than no tenant.
    The injection point is `_json`, which is evaluated while building the
    `extraction_schemas` INSERT, i.e. after the organization and agent rows exist.
    """
    slug = _run_slug("atomic")

    def _boom(value: object) -> str:
        raise RuntimeError("engine of failure, halfway through the wizard")

    monkeypatch.setattr(admin_service, "_json", _boom)
    with pytest.raises(RuntimeError):
        await admin_service.create_organization(
            name="Atomic Clinic",
            slug=slug,
            vertical_template="clinic",
            billing_email=None,
            language="te-IN",
            created_by=None,
        )

    assert not await _org_exists(slug), "a failed wizard step must leave no organization"

    # And the slug is free again, so the operator can simply retry.
    monkeypatch.undo()
    created = await admin_service.create_organization(
        name="Atomic Clinic",
        slug=slug,
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    assert created["slug"] == slug


async def test_a_created_tenant_is_complete_enough_to_take_a_call() -> None:
    """Every part FLOWS §1 promises exists in the same transaction: retention floor,
    a disclosure line, an extraction schema, and the agent POINTING at that schema.

    The last one is the easy one to lose: an agent whose `extraction_schema_id` is
    NULL looks configured and extracts nothing.
    """
    created = await admin_service.create_organization(
        name="Complete Clinic",
        slug=_run_slug("complete"),
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    async with tenant_session(created["id"]) as session:
        agent = (
            await session.execute(
                text(
                    "SELECT extraction_schema_id, disclosure_line, status FROM agents WHERE id = :a"
                ),
                {"a": created["agent_id"]},
            )
        ).first()
        fields = (
            await session.execute(
                text("SELECT fields FROM extraction_schemas WHERE id = :s"),
                {"s": created["extraction_schema_id"]},
            )
        ).scalar()
    assert agent is not None
    assert agent[0] == created["extraction_schema_id"], "the agent must point at its schema"
    assert agent[1] and agent[1].strip(), "hard rule 5: a non-null disclosure line, always"
    assert agent[2] == "draft", "nothing is client-visible until publish (FLOWS §1)"
    assert fields, "the vertical template seeds the columns the CRM renders"


async def test_a_slug_collision_that_beats_the_probe_is_a_conflict_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two operators creating the same client at once both pass the availability probe
    (it runs in its own transaction, before the insert), and the UNIQUE index decides.

    That must reach the wizard as the same 409 the probe would have produced. As a 500
    it tells the operator nothing, violates the RFC-9457 user-safe-message rule, and
    pages someone.
    """
    slug = _run_slug("race")
    await admin_service.create_organization(
        name="Race Clinic",
        slug=slug,
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )

    async def _lost_the_race(session: object, candidate: str) -> None:
        return None

    # Exactly what a lost race looks like: the probe saw nothing, the index disagrees.
    monkeypatch.setattr(admin_service, "assert_slug_available", _lost_the_race)
    with pytest.raises(ProblemError) as exc:
        await admin_service.create_organization(
            name="Race Clinic Two",
            slug=slug,
            vertical_template="clinic",
            billing_email=None,
            language="te-IN",
            created_by=None,
        )
    assert exc.value.code == "slug_taken"
    assert exc.value.status == 409


async def test_reserved_slugs_are_refused_by_the_api_not_only_the_form() -> None:
    """The reserved-word check is server-side or it is decorative — including when the
    slug is DERIVED from the business name and never typed by anyone."""
    token = await _make_admin()
    async with _client() as http:
        explicit = await http.post(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Totally Fine Clinic", "slug": "admin", "vertical_template": "clinic"},
        )
        derived = await http.post(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Billing", "vertical_template": "clinic"},
        )
    assert explicit.status_code == 409, explicit.text
    assert explicit.json()["type"].endswith("/slug_reserved")
    assert derived.status_code == 409, "a reserved slug derived from the name is still reserved"


async def test_creating_the_same_slug_twice_is_a_clean_conflict() -> None:
    token = await _make_admin()
    slug = _run_slug("retry")
    async with _client() as http:
        first = await http.post(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Retry Clinic", "slug": slug, "vertical_template": "clinic"},
        )
        second = await http.post(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Retry Clinic", "slug": slug, "vertical_template": "clinic"},
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert second.json()["type"].endswith("/slug_taken")


# --------------------------------------------------------------------------------
# 2. THE CLERK MIRROR WAS HERE. IT IS GONE, AND SO IS EVERYTHING IT COULD GET WRONG.
# --------------------------------------------------------------------------------
#
# Five tests stood here (D-177 removed them with their subject): an out-of-order
# `user.updated` must not resurrect a `user.deleted`; an upstream `organization.created`
# must not invent a tenant; a failed mirror write must leave the inbox row re-claimable
# rather than `processing`; a non-UTF-8 body must be a 401 rather than a 500; and the Svix
# signature must be verified over the raw bytes.
#
# What they were protecting is the sentence D-37 wrote and D-177 collected on: **our
# Postgres is the system of record.** It always was — `users`, `memberships`,
# `organizations` and every RLS policy key off OUR ids — but a mirror meant those rows had
# an upstream, and an upstream means ordering, retries, resurrection and a signature to
# check. There is no upstream now. `users` rows are created by
# `apps/api/authn/invitations.py` (invitation redemption) and `admin_users` rows by
# `scripts/bootstrap_admin.py` / `apps/api/authn/bootstrap.py`; `organizations` rows were
# NEVER created here — this endpoint answered `ignored` to every org event, which is the
# property the phantom-row test pinned and which is now structural.
#
# The deletion half is worth naming rather than assuming: `user.deleted` was the only
# producer of `users.deactivated_at`, and its successor is
# `POST /v1/members/{user_id}` removal plus the operator surfaces that set the column
# directly. `tests/api_security_test.py` still drives the property that mattered — a
# deactivated user's live session stops working on the next request — which is the one
# thing the resurrection test existed to protect.


def get_settings_obj() -> object:
    from apps.api.core.settings import get_settings

    return get_settings()


# --------------------------------------------------------------------------------
# 3. Invitations
# --------------------------------------------------------------------------------


async def _org_for(prefix: str) -> dict[str, object]:
    return await admin_service.create_organization(
        name=f"{prefix.title()} Clinic",
        slug=_run_slug(prefix),
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _redeem(token: str) -> object:
    """Redemption as an invitee performs it: one call, no prior account (D-177)."""
    async with _client() as http:
        return await http.post(
            "/v1/auth/client/invitations/accept",
            json={"token": token, "password": "platform-audit-invitee-password"},
        )


async def test_an_expired_invitation_cannot_be_accepted() -> None:
    """72h (DATA-MODEL §2). An invite that outlives its window is a standing key to a
    tenant sitting in an old inbox."""
    created = await _org_for("expiry")
    async with tenant_session(created["id"]) as session:
        _invitation_id, token = await admin_service.create_invitation(
            session,
            tenant_id=created["id"],
            email=f"expired-{uuid.uuid4().hex[:8]}@example.com",
            role="owner",
            created_by=None,
        )
        await session.execute(
            text("UPDATE invitations SET expires_at = now() - interval '1 hour'"),
        )

    response = await _redeem(token)
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert response.json()["type"].endswith("/invitation_invalid")  # type: ignore[attr-defined]

    async with tenant_session(created["id"]) as session:
        members = (await session.execute(text("SELECT count(*) FROM memberships"))).scalar()
    assert members == 0, "an expired invite creates no membership"


async def test_an_invitation_grants_exactly_the_role_it_was_issued_for() -> None:
    """The invite carries the role; the acceptance must not be able to widen it."""
    created = await _org_for("role")
    async with tenant_session(created["id"]) as session:
        _invitation_id, token = await admin_service.create_invitation(
            session,
            tenant_id=created["id"],
            email=f"role-{uuid.uuid4().hex[:8]}@example.com",
            role="staff",
            created_by=None,
        )

    response = await _redeem(token)
    assert response.status_code == 200, response.text  # type: ignore[attr-defined]
    assert response.json()["role"] == "staff"  # type: ignore[attr-defined]

    async with tenant_session(created["id"]) as session:
        roles = (await session.execute(text("SELECT role FROM memberships"))).scalars().all()
    assert roles == ["staff"], "a staff invite must never mint an owner"


# --------------------------------------------------------------------------------
# 4. The knowledge-base workflow (FLOWS §7)
# --------------------------------------------------------------------------------


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=submitted["id"])
    return uuid.UUID(str(submitted["id"]))


async def test_rollback_republishes_the_previous_version() -> None:
    """FLOWS §7's last sentence — "Rollback = reactivate prior version" — and the one
    the publish endpoint advertises in its own description.

    A bad knowledge update is a client's agent telling callers the wrong price. The
    recovery path has to work at the moment it is needed, not be discovered broken.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    v1 = await _publish(tenant_id, agent_id, "Hours", "The clinic is open 9am to 8pm daily.")
    await _publish(tenant_id, agent_id, "Hours", "The clinic is open 10am to 6pm daily.")

    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=v1)
        rows = (
            await session.execute(
                text(
                    "SELECT version, is_active FROM kb_sources WHERE agent_id = :a "
                    "AND name = 'Hours' ORDER BY version"
                ),
                {"a": agent_id},
            )
        ).all()
    assert [bool(r[1]) for r in rows] == [True, False], "rollback makes v1 live and v2 not"


async def test_a_rejected_source_can_never_be_published() -> None:
    """The approval gate, from the other side: rejection is terminal. Re-approval is
    refused by the CAS, and publish must refuse it too — a rejected document reaching
    the agent is the exact failure the gate exists to prevent."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Prices",
            body="Consultation is free of charge, forever, for everyone.",
        )
        await kb_service.reject_source(
            session, source_id=submitted["id"], reason="not what the client agreed"
        )
        with pytest.raises(ProblemError) as reapprove:
            await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        with pytest.raises(ProblemError) as publish:
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=submitted["id"])
    # 409 naming `rejected`, not the old catch-all: the reason the approval is refused
    # is the state the row is actually in, and a reviewer has to be told which.
    assert reapprove.value.code == "invalid_status_transition"
    assert reapprove.value.status == 409
    assert publish.value.code in ("kb_not_approved", "kb_rejected")


async def test_only_one_version_of_a_named_source_is_ever_live() -> None:
    """Superseded knowledge must not resurface by itself. Publishing v2 while v1 is
    live is the only way v1 ever becomes inactive, and it must be atomic with the
    activation."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    for body in ("Parking is free.", "Parking costs 20 rupees.", "Parking is valet only."):
        await _publish(tenant_id, agent_id, "Parking", body)

    async with tenant_session(tenant_id) as session:
        active = (
            await session.execute(
                text(
                    "SELECT count(*) FROM kb_sources WHERE agent_id = :a AND name = 'Parking' "
                    "AND is_active = true"
                ),
                {"a": agent_id},
            )
        ).scalar()
    assert active == 1


async def test_the_engine_kb_matches_what_is_approved_and_active() -> None:
    """What the agent actually says is what the ENGINE holds, not what our table says.

    Publishing v2 archives v1 for us and appends v2 for the engine, so the agent keeps
    answering from the superseded text — the published KB diverging from what was
    approved, which is the one thing the approval gate exists to prevent.
    """
    from apps.api.engine import get_engine

    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _publish(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    attached = "\n".join(s.text for s in getattr(get_engine(), "_kb", {}).get(ref, []))
    assert "500 rupees" not in attached, "the superseded version must not remain live"


# --------------------------------------------------------------------------------
# 5. The ops switches
# --------------------------------------------------------------------------------

# Every module that may place an outbound call, and the gate each one must consult.
# Adding a dispatch path without `check_dispatch`/`assert_dispatch_allowed` is how the
# big red switch quietly stops being global.
_OUTBOUND_MODULES = {
    "apps/api/crm/routes.py",
    "apps/api/ingest/service.py",
    "apps/workers/campaign_dispatch.py",
    # The FOURTH (D-510): the call-back a caller asked for on a call, dialled at the time
    # they were promised. It is the sharpest case this enumeration exists for — the dial is
    # triggered by a CLOCK rather than by anybody pressing anything, so nobody is watching
    # when it goes out, and a path that escaped the halt here would ring people through an
    # incident with no operator in the loop. `dispatch_due_callbacks` calls `check_dispatch`
    # per call-back, at the moment of dialling, which is what the loop below verifies.
    "apps/workers/callbacks.py",
}


def test_every_outbound_path_passes_the_compliance_gate() -> None:
    """The enumeration, asserted rather than remembered.

    `dispatch_call` is the single outbound entry point and `start_outbound_call` is the
    single vendor call underneath it. Both sets are pinned here, so a new dial site
    fails this test instead of silently escaping the halt.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    dialers: set[str] = set()
    vendor_callers: set[str] = set()
    for path in sorted(root.glob("apps/**/*.py")):
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        if "dispatch_call(" in source and "async def dispatch_call(" not in source:
            dialers.add(rel)
        if ".start_outbound_call(" in source:
            vendor_callers.add(rel)

    assert dialers == _OUTBOUND_MODULES, f"an unenumerated dispatch path appeared: {dialers}"
    assert vendor_callers == {"apps/api/agents/service.py"}, (
        "the vendor dial must stay behind the single gated entry point"
    )
    for rel in sorted(dialers):
        source = (root / rel).read_text(encoding="utf-8")
        assert "check_dispatch" in source or "assert_dispatch_allowed" in source, (
            f"{rel} dials without consulting the compliance gate"
        )


async def test_the_halt_beats_every_other_consideration_and_is_read_uncached() -> None:
    """The switch is durable state, and the gate must see it on the very next call —
    a dispatcher reading a cached "open" would keep dialling through an incident.

    Scoped tight and restored in `finally`: `platform_state` is a single global row
    that every other suite shares.
    """
    from apps.api.compliance.service import check_dispatch
    from apps.api.core.loadshed import get_platform_status, set_platform_status

    created = await _org_for("halt")
    await set_platform_status(outbound_halted=True, actor_id=None)
    try:
        cached = await get_platform_status()
        async with tenant_session(created["id"]) as session:
            decision = await check_dispatch(
                session,
                tenant_id=uuid.UUID(str(created["id"])),
                # A nonexistent agent: if any check ran before the halt this would come
                # back `agent_missing`, so the rule name proves the ordering too.
                agent_id=uuid.uuid4(),
                phone_e164="+919876500123",
            )
    finally:
        await set_platform_status(outbound_halted=False, actor_id=None)

    assert cached.outbound_halted, "the cached read must not serve a stale open"
    assert decision.allowed is False
    assert decision.rule == "big_red_switch"


async def test_pulling_the_big_red_switch_needs_its_own_confirmation() -> None:
    """Step-up is enforced, not merely documented (BACKEND-PATTERNS §7).

    Both refusals below mutate nothing, which is deliberate: `platform_state` is one
    global row shared with every other suite, so this test proves the guard without
    ever moving the switch.

    It covers the HALT direction only, which is now one of three: releasing the halt and
    changing the load-shed mode have their own strings, and the generic
    `set_platform_state` this test sends as `mismatched` authorises nothing at all any
    more. `tests/platform_halt_test.py` owns that matrix (and the halt reason); this
    case stays here because it is the one an outbound-safety reader looks for first.
    """
    token = await _make_admin()
    async with _client() as http:
        unconfirmed = await http.post(
            "/v1/ops/platform",
            headers={"Authorization": f"Bearer {token}"},
            json={"outbound_halted": True, "reason": "audit"},
        )
        mismatched = await http.post(
            "/v1/ops/platform",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": "set_platform_state",
            },
            json={"outbound_halted": True, "reason": "audit"},
        )

    assert unconfirmed.status_code == 403, "no confirmation, no switch"
    assert unconfirmed.json()["type"].endswith("/step_up_required")
    assert mismatched.status_code == 403, "a confirmation for another action is not this one"
