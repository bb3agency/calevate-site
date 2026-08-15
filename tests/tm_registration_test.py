"""Calevate's OWN telemarketer registration, and the admin surface for the client's.

SEC-COMP §3's first bullet is one sentence with two subjects: "Calevate TM registration
exists AND this client's PE registration + TM-link are active". The client half landed
with `dlt_registrations` (migration c5a930e6b1d4). This file covers the two gaps that
work left behind:

1. **The company half was unmodelled.** It is ONE fact for the whole platform — true or
   false for every tenant at the same instant — so it lives beside the load-shed mode
   and the big red switch in `platform_state` (migration d7f2a3c9b410), not copied into
   N tenant rows that eventually disagree. The load-bearing assertion below is that
   while it is not live, NO tenant can launch a campaign, however complete their own PE
   registration is: `test_no_tenant_can_launch_while_the_platform_tm_registration_is_not_live`.
2. **`record_dlt_registration` had no caller.** Deliberately no CLIENT route — a client
   who could mark their own PE `active` would be marking the launch gate green on a
   registration that does not exist — but no ops route either, which left a compliance
   fact settable only by hand-written SQL against production. The endpoint tests below
   assert what this repo has now got wrong twice: that an admin-realm principal can
   actually CALL it, with no impersonation header.

**Concurrency — the shared single row.** Other pytest processes run against this same
Postgres, and `platform_state` is one global row that also carries the big red switch.
So the direction matters:

- The refusal tests (platform NOT registered) run inside a transaction that is ROLLED
  BACK. Nothing is ever committed, so no concurrent run can observe a platform that
  cannot dial, and the row lock is held for two statements. `SET LOCAL lock_timeout`
  makes the pathological case fail fast rather than queue behind us.
- The endpoint tests only ever drive the row in the PERMISSIVE direction (`active`) and
  do not restore a previous non-live value afterwards — restoring "not registered"
  would halt another suite's launches for real. `tests/conftest.py` establishes the
  same permissive baseline once per session.
- The step-up refusals below use the withdrawal direction, which is exactly why they
  are written as refusals: they assert a 403 and prove the row did not move.

Run: uv run pytest -q tests/tm_registration_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import PUBLIC_PREFIXES, iter_api_routes
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.ops.service import read_tm_registration, set_tm_registration
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.impersonation_grant_test import view_as_headers
from tests.national_dnd_test import record_test_scrub

pytestmark = [pytest.mark.rls]

LIVE_TM_ID = "TM-TEST-0000000001"


# ------------------------------------------------------------------ shared plumbing


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """Same idiom as `route_shape_test._make_admin` — a real admin_users row and the
    dev token shape `verify_token` accepts for the admin realm."""
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


async def _tenant() -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="Telemarketer Motors",
        slug=f"tm-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": created["agent_id"]},
        )
    return created


async def _perfect_campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    """A campaign with EVERY client-side condition of SEC-COMP §3 satisfied.

    Live outbound agent with a disclosure line, registered 140 number, approved
    promotional template, consent provenance, one dialable contact, and an active PE
    registration with an active TM link. Its launch preview is green — which is what
    makes the platform-level refusal below unambiguous: the only thing that can be
    wrong is us.
    """
    async with tenant_session(tenant_id) as session:
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, "
                "created_at, updated_at) VALUES (:id, :tid, :e, '140', 'registered', "
                "now(), now())"
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
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
        campaign_id = await service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Diwali offers",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=3,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876590001", "name": "Ravi"}],
        )
        # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
        # A promotional campaign is launch-ready only once an access provider has
        # preference-scrubbed its list, so this fixture supplies the fact through the
        # production writer — `tests/national_dnd_test.py` proves the refusal is real.
        await record_test_scrub(session, campaign_id)
        await service.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Telemarketer Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    return campaign_id


class _RollbackError(Exception):
    """Sentinel: leaving the `tenant_session` block by raising rolls its transaction
    back, which is the ONLY way this suite is allowed to make the platform unregistered
    (see the module docstring)."""


async def _with_platform_tm(
    tenant_id: uuid.UUID, status: str, work: Any, *, tm_id: str | None = None
) -> Any:
    """Run `work(session)` with the platform's TM registration set to `status`, then
    ROLL BACK — the change is never committed and no other connection ever sees it.

    Uncommitted is the whole trick: MVCC means concurrent readers keep seeing the
    committed `active` row, so a second pytest process dialling right now is untouched.
    The one cost is a row lock for the duration, which is two statements; `lock_timeout`
    turns the pathological overlap into a fast failure instead of a queue.
    """
    captured: dict[str, Any] = {}
    try:
        async with tenant_session(tenant_id) as session:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await session.execute(
                text(
                    "UPDATE platform_state SET tm_registration_status = :st, tm_id = :tm, "
                    "tm_registered_at = :reg WHERE id = 1"
                ),
                {
                    "st": status,
                    "tm": tm_id,
                    "reg": datetime.now(UTC) if status == "active" else None,
                },
            )
            captured["value"] = await work(session)
            raise _RollbackError
    except _RollbackError:
        pass
    return captured["value"]


# ------------------------------------------------- the load-bearing pair (the gate)


async def test_no_tenant_can_launch_while_the_platform_tm_registration_is_not_live() -> None:
    """A client with PERFECT paperwork still cannot launch while WE are unregistered.

    Every other §3 condition is satisfied for this tenant — the preview is green with
    the registration in place — so the single blocker returned here is the company-level
    one, and it is returned for a tenant that has done nothing wrong. That asymmetry is
    the point: `pe_registration_missing` is a to-do item for the client,
    `tm_registration_missing` is an outage notice about us, and collapsing them into one
    "not compliant" would send the client to a registrar who would tell them their
    registration is fine.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    campaign_id = await _perfect_campaign(tenant_id, uuid.UUID(str(org["agent_id"])))

    async def _rules(session: Any) -> set[str]:
        blockers = await service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        return {blocker.rule for blocker in blockers}

    green = await _with_platform_tm(tenant_id, "active", _rules, tm_id=LIVE_TM_ID)
    assert green == set(), f"the fixture campaign is not otherwise launchable: {green}"

    for status in ("not_registered", "submitted", "suspended", "revoked"):
        rules = await _with_platform_tm(tenant_id, status, _rules)
        assert rules == {"tm_registration_missing"}, (
            f"platform TM status {status!r} must block every launch by name, got {rules}"
        )


async def test_the_launch_itself_is_refused_not_only_the_preview() -> None:
    """The preview is UX; `launch_campaign` is the gate (hard rule 5).

    A blocker that only ever reached `launch_blockers` would leave the actual launch
    path open, so this asserts on the function that flips the campaign to `running` —
    and on the campaign's status afterwards, because "raised and launched anyway" is
    the failure a returns-only assertion would miss.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    campaign_id = await _perfect_campaign(tenant_id, uuid.UUID(str(org["agent_id"])))

    async def _attempt(session: Any) -> tuple[list[str], str]:
        with pytest.raises(ProblemError) as caught:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
            )
        ).scalar()
        return [str(field["rule"]) for field in caught.value.fields or []], str(status)

    rules, status = await _with_platform_tm(tenant_id, "not_registered", _attempt)

    assert rules == ["tm_registration_missing"]
    assert status == "draft", "a blocked launch must not move the campaign"


async def test_recording_the_registration_live_lets_the_same_campaign_launch() -> None:
    """The mirror, through the real writer rather than a hand-written UPDATE.

    One transaction: unregistered ⇒ blocked, `set_tm_registration(active)` ⇒ the same
    campaign launches. Same session, same campaign, nothing else touched, and rolled
    back at the end — so what changed between the two answers is exactly the one fact.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    campaign_id = await _perfect_campaign(tenant_id, uuid.UUID(str(org["agent_id"])))

    async def _before_and_after(session: Any) -> tuple[set[str], dict[str, Any]]:
        blocked = {
            blocker.rule
            for blocker in await service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }
        registration = await set_tm_registration(
            session, status="active", tm_id="TM-9900112233", registered_at=None
        )
        assert registration.is_live
        assert registration.verified_at is not None, "a write records when WE last looked"
        launched = await service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        return blocked, launched

    blocked, launched = await _with_platform_tm(tenant_id, "not_registered", _before_and_after)

    assert blocked == {"tm_registration_missing"}
    assert launched["status"] == "running"
    assert launched["dialable"] == 1


async def test_the_platform_registration_is_one_row_not_a_per_tenant_copy() -> None:
    """Two unrelated tenants read the IDENTICAL fact, on their own RLS-scoped sessions.

    The reason the TM half is not a column on `dlt_registrations`: N copies of one fact
    drift, and the first time two of them disagreed there would be no way to say which
    one was the platform. There is no tenant argument to `read_tm_registration` at all —
    this asserts the consequence, that a tenant's session cannot see a different answer
    from anyone else's.
    """
    first = uuid.UUID(str((await _tenant())["id"]))
    second = uuid.UUID(str((await _tenant())["id"]))

    async with tenant_session(first) as session:
        mine = await read_tm_registration(session)
    async with tenant_session(second) as session:
        theirs = await read_tm_registration(session)
    async with untenanted_session() as session:
        platform = await read_tm_registration(session)

    assert mine == theirs == platform
    # And the row it comes from is the singleton `platform_state` — one row, enforced
    # by `ck_platform_state_singleton`, not a table that could grow a second opinion.
    async with untenanted_session() as session:
        assert (await session.execute(text("SELECT count(*) FROM platform_state"))).scalar() == 1


async def test_the_uncommitted_refusal_never_escapes_this_suite() -> None:
    """The concurrency contract of this file, asserted rather than asserted-in-prose.

    Every test above makes the platform unregistered. If one of them leaked, every
    other pytest process on this database would stop launching campaigns — so a
    separate connection must still see a live registration once they are done.
    """
    async with untenanted_session() as session:
        registration = await read_tm_registration(session)
    assert registration.is_live, (
        "a rolled-back test transaction left the platform unregistered for everyone"
    )


# ------------------------------------------------------ the ops surface (company half)


async def test_ops_can_read_and_record_the_platform_tm_registration() -> None:
    """The endpoint an operator uses instead of writing SQL against production.

    Only the permissive direction is exercised over the committed path, on purpose:
    recording the registration as live is safe for every concurrent run, while
    withdrawing it through a committed request would halt other suites' launches for
    real. The withdrawal direction is covered by the step-up refusals below, which
    assert that it does NOT happen.
    """
    token = await _make_admin()
    registered_at = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

    async with _client() as http:
        before = await http.get("/v1/ops/platform", headers={"Authorization": f"Bearer {token}"})
        recorded = await http.post(
            "/v1/ops/platform/tm-registration",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": "record_tm_registration",
            },
            json={
                "status": "active",
                "tm_id": LIVE_TM_ID,
                "registered_at": registered_at.isoformat(),
                "reason": "Registrar confirmed the TM registration (ticket OPS-411).",
            },
        )
        after = await http.get("/v1/ops/platform", headers={"Authorization": f"Bearer {token}"})

    assert before.status_code == 200, before.text
    # The switchboard read carries every global fact, so one request answers "may this
    # platform work right now" completely — and, since the halt is one of them, WHY not
    # (`halt_reason`, null unless outbound is halted; `platform_halt_test.py`).
    #
    # An EXACT set rather than a subset, deliberately, and it is the assertion that
    # caught `outbox_dead_letters` arriving from another slice in the same wave: this
    # route is the admin console's one round trip and the only GET on a router whose
    # permission is MUTATING, so a field appearing on it is a decision (D-58) and not a
    # detail. A subset check would have let it land unread.
    assert set(before.json()) == {
        "load_shed_mode",
        "outbound_halted",
        "halt_reason",
        "tm_registration",
        "outbox_dead_letters",
        # D-123. The second MEASUREMENT on a payload of switches, and it arrives by the
        # same argument `outbox_dead_letters` did: the ops screen makes one read, gates
        # the whole page on it, and `ops:manage` is in `MUTATING_PERMISSIONS` — so a field
        # here costs no new entry in `ADMIN_CONSOLE_GETS` while a second GET would. This
        # guard caught it too, which is the point of an exact set.
        "engine_drift",
    }

    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert body["status"] == "active"
    assert body["tm_id"] == LIVE_TM_ID
    assert body["is_live"] is True

    assert after.json()["tm_registration"]["is_live"] is True
    assert after.json()["tm_registration"]["verified_at"] is not None


async def test_recording_the_platform_registration_is_audited() -> None:
    """A platform-wide compliance fact is mutable by design, so `audit_log` is the only
    history of who changed it and why. The `reason` is required at the boundary for
    exactly this row."""
    token = await _make_admin()

    async with _client() as http:
        response = await http.post(
            "/v1/ops/platform/tm-registration",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": "record_tm_registration",
            },
            json={
                "status": "active",
                "tm_id": LIVE_TM_ID,
                "reason": "Annual re-verification with the registrar.",
            },
        )
    assert response.status_code == 200, response.text

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type, object_id, entry_hash FROM audit_log "
                    "WHERE action = 'ops.record_tm_registration' ORDER BY at DESC LIMIT 1"
                )
            )
        ).first()
    assert row is not None, "recording the platform's TM registration must be audited"
    # `audit_log` has no summary column by design — the reason and the status ride the
    # redacted log stream keyed by the same entry (compliance/audit.py), and the ROW
    # carries the chain-hashed facts: who, what, and which object.
    assert (row[0], row[1], row[2]) == ("admin", "platform_state", "1")
    assert row[3], "the entry is linked into the hash chain"


@pytest.mark.parametrize(
    ("confirm", "status"),
    [
        (None, "revoked"),
        # The header from the OTHER direction: an operator confirming that they meant
        # to RECORD a registration must not thereby withdraw one.
        ("record_tm_registration", "suspended"),
        (None, "active"),
    ],
)
async def test_the_registration_switch_needs_its_own_step_up(
    confirm: str | None, status: str
) -> None:
    """Step-up bound to the specific action, in both directions (BACKEND-PATTERNS §7).

    Withdrawing the registration halts every tenant's launches — the big red switch by
    another route — and recording it turns the platform-wide gate green on our word
    alone. Neither belongs behind a single unconfirmed POST, and the confirmation for
    one must not authorise the other.

    Safe to run concurrently BECAUSE these are refusals: each asserts the row did not
    move, so a regression here shows up as a failed assertion in this suite rather than
    as a stopped campaign in somebody else's.
    """
    token = await _make_admin()
    async with untenanted_session() as session:
        before = await read_tm_registration(session)

    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    async with _client() as http:
        response = await http.post(
            "/v1/ops/platform/tm-registration",
            headers=headers,
            json={"status": status, "tm_id": LIVE_TM_ID, "reason": "Registrar notice."},
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/step_up_required")

    async with untenanted_session() as session:
        after = await read_tm_registration(session)
    assert after == before, "a refused step-up must change nothing"


async def test_an_active_registration_must_name_itself() -> None:
    """`active` with no TM id is a claim, not a fact — refused at the service, and by a
    DB CHECK behind it. Asserted through the endpoint because that is where an operator
    with a half-filled form actually meets it: a validation problem+json, not a 500 out
    of an IntegrityError."""
    token = await _make_admin()
    async with untenanted_session() as session:
        before = await read_tm_registration(session)

    async with _client() as http:
        response = await http.post(
            "/v1/ops/platform/tm-registration",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": "record_tm_registration",
            },
            json={"status": "active", "reason": "Registrar said yes, number to follow."},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/tm_registration_id_required")

    async with untenanted_session() as session:
        assert await read_tm_registration(session) == before


async def test_a_client_token_cannot_reach_the_ops_registration_switch() -> None:
    """`ops:manage`, `realm="admin"`: an owner cannot record the platform's compliance
    state by discovering the path."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    token = await _make_member(tenant_id, role="owner")

    async with _client() as http:
        response = await http.post(
            "/v1/ops/platform/tm-registration",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Org-Slug": str(org["slug"]),
                "X-Confirm-Action": "record_tm_registration",
            },
            json={"status": "active", "tm_id": LIVE_TM_ID, "reason": "nope"},
        )

    assert response.status_code == 401, response.text


# ------------------------------------------------- the admin surface (client half)


async def test_an_admin_records_a_clients_pe_registration_on_the_tenant_path() -> None:
    """Gap 2, from the outside: a plain admin token, no impersonation header, tenant in
    the URL — the request `record_dlt_registration` never had.

    This is the failure mode `tests/route_shape_test.py` pins structurally: an
    admin-realm mutation that infers its tenant from the session is 401 without the
    impersonation header and 403 with it (D-22), so it can never be called at all. A
    200 here is the whole point.
    """
    token = await _make_admin()
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    pe_id = f"1102{uuid.uuid4().int % 10**9:09d}"

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/dlt-registration",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "status": "active",
                "tm_link_status": "active",
                "pe_id": pe_id,
                "entity_name": "Telemarketer Motors Pvt Ltd",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "tenant_id": str(tenant_id),
        "status": "active",
        "tm_link_status": "active",
        "pe_id": pe_id,
    }

    # The fact landed in the tenant's own row, under RLS, and the launch gate reads it.
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, tm_link_status, pe_id, registered_at, verified_at "
                    "FROM dlt_registrations WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).first()
    assert row is not None
    assert (row[0], row[1], row[2]) == ("active", "active", pe_id)
    assert row[3] is not None, "an active registration carries the registrar's date"
    assert row[4] is not None, "and when we last verified it"

    async with untenanted_session() as session:
        audit = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type, object_id FROM audit_log "
                    "WHERE action = 'dlt_registration.recorded' AND tenant_id = :tid "
                    "ORDER BY at DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
        ).first()
    assert audit is not None, "recording a client's registration must be audited"
    assert (audit[0], audit[1], audit[2]) == ("admin", "dlt_registration", str(tenant_id))


async def test_recording_a_pe_registration_unblocks_that_tenant_only() -> None:
    """End to end through the endpoint: a tenant blocked by `pe_registration_missing`
    launches after ops files their registration, and a second tenant stays blocked.

    The per-tenant mirror of the platform test above, and the reason the two halves are
    modelled in different places.
    """
    token = await _make_admin()
    filed = await _tenant()
    unfiled = await _tenant()
    filed_id = uuid.UUID(str(filed["id"]))
    unfiled_id = uuid.UUID(str(unfiled["id"]))

    async def _rules(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> set[str]:
        async with tenant_session(tenant_id) as session:
            return {
                blocker.rule
                for blocker in await service.launch_blockers(
                    session, tenant_id=tenant_id, campaign_id=campaign_id
                )
            }

    # `_perfect_campaign` files the registration; take it away again so this test
    # starts from a tenant that genuinely has none.
    filed_campaign = await _perfect_campaign(filed_id, uuid.UUID(str(filed["agent_id"])))
    unfiled_campaign = await _perfect_campaign(unfiled_id, uuid.UUID(str(unfiled["agent_id"])))
    for tenant_id in (filed_id, unfiled_id):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("DELETE FROM dlt_registrations WHERE tenant_id = :tid"), {"tid": tenant_id}
            )

    assert await _rules(filed_id, filed_campaign) == {"pe_registration_missing"}

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{filed_id}/dlt-registration",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "status": "active",
                "tm_link_status": "active",
                "pe_id": f"1102{uuid.uuid4().int % 10**9:09d}",
            },
        )
    assert response.status_code == 200, response.text

    assert await _rules(filed_id, filed_campaign) == set()
    assert await _rules(unfiled_id, unfiled_campaign) == {"pe_registration_missing"}


async def test_a_pe_registration_recorded_active_must_name_itself() -> None:
    """The client-side twin of the TM id rule: `active` with no PE id is refused with a
    validation problem+json rather than reaching the DB CHECK as a 500."""
    token = await _make_admin()
    org = await _tenant()

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/dlt-registration",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "active", "tm_link_status": "active"},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/pe_registration_id_required")


async def test_a_client_cannot_record_their_own_pe_registration() -> None:
    """The reason `record_dlt_registration` has no client route: a client who could
    mark their own registration `active` would be marking the launch gate green on a
    registration that does not exist. An owner token is refused on the admin path, and
    there is no other."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    token = await _make_member(tenant_id, role="owner")

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/dlt-registration",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
            json={"status": "active", "tm_link_status": "active", "pe_id": "110200000000000001"},
        )

    assert response.status_code == 401, response.text
    assert not any(
        route.path.startswith("/v1/campaigns") and route.path.endswith("dlt-registration")
        for route in iter_api_routes(app)
    ), "there must be no client-realm route recording a DLT registration"


async def test_the_admin_registration_route_is_refused_while_impersonating() -> None:
    """D-22 is not what made the endpoint callable: an admin inside a "view as client"
    session is still refused every mutation, this one included."""
    token = await _make_admin()
    org = await _tenant()

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/dlt-registration",
            # A REAL grant, so the 403 is the read-only rule rather than a missing one.
            headers=await view_as_headers(http, token, str(org["slug"])),
            json={"status": "submitted", "tm_link_status": "pending"},
        )

    assert response.status_code == 403, response.text
    assert response.json()["kind"] == "permission"
    assert "read-only" in response.json()["detail"].lower(), response.text


async def test_both_new_routes_sit_where_the_house_pattern_puts_them() -> None:
    """The structural half, so the shape is pinned and not just the behaviour: the
    client-scoped mutation names its tenant in the path under `/v1/admin/tenants/`, and
    the platform-scoped one names no tenant at all because its subject is Calevate."""
    paths = {route.path for route in iter_api_routes(app)}
    assert "/v1/admin/tenants/{tenant_id}/dlt-registration" in paths
    assert "/v1/ops/platform/tm-registration" in paths
    # Neither is reachable without a token: both live behind an authenticated prefix.
    assert not any(
        path.startswith(prefix)
        for prefix in PUBLIC_PREFIXES
        for path in ("/v1/admin/tenants/{tenant_id}/dlt-registration", "/v1/ops/platform")
    )

    registration = next(
        route
        for route in iter_api_routes(app)
        if route.path == "/v1/admin/tenants/{tenant_id}/dlt-registration"
    )
    assert "tenant_id" in {param.name for param in registration.dependant.path_params}
