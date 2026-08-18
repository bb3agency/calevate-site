"""Who may change who is on a client account (ROADMAP M3, "client staff roles").

This surface is the one place in the client realm where a request can change what a
future request is allowed to do, so almost every test here is an ESCALATION test rather
than a CRUD test. The vectors, in the order they appear below:

1. a `staff` member promoting themselves to `owner`
2. an owner acting on their own membership (the mis-click / clickjack case)
3. a member of tenant A changing a membership in tenant B
4. an owner removing or demoting the LAST owner — including two owners racing to demote
   each other, which is the case a `count(*) > 1` guard gets wrong
5. a role change racing another role change on the same person (stale screen)
6. an impersonating operator (D-22) reaching a mutating route

Each is asserted twice where it matters: the request is refused AND the database is
unchanged. A 403 with the row already written is the failure mode that looks green.

CONCURRENCY: every test mints its own organization and reads only through tenant-scoped
sessions, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import asyncio
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


async def _colleague(
    tenant_id: uuid.UUID, *, role: str = "staff", name: str | None = None
) -> tuple[uuid.UUID, str]:
    """A second member of the same tenant. Returns (user_id, dev bearer token).

    `_make_tenant` seeds exactly one member who is also the bearer of the token, and
    every rule on this surface is about acting on SOMEBODY ELSE — so a fixture that
    could only produce the caller could not express a single one of them.
    """
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:i, :e, :n, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com", "n": name},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, :r, now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id, "r": role},
        )
    return user_id, f"dev:client:{user_id}"


async def _role_of(tenant_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT role FROM memberships WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar()


async def _owner_user_id(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT user_id FROM memberships WHERE role = 'owner'"))
        ).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _audit_actions(tenant_id: uuid.UUID) -> list[tuple[str, str, str | None]]:
    """(action, object_id, actor_id) for this tenant, oldest first.

    `audit_log` is not tenant-RLS'd, so this reads it from an untenanted session and
    filters explicitly — the one place in this file where a WHERE clause is the scope
    rather than a policy, and it is a test reading a cross-tenant ledger on purpose.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_id, actor_id FROM audit_log WHERE tenant_id = :t "
                    "ORDER BY at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), str(r[1]), str(r[2]) if r[2] else None) for r in rows]


# --- the happy path, and what it writes ---------------------------------------


async def test_an_owner_promotes_and_demotes_a_colleague_and_the_log_says_so() -> None:
    """The transition is IN the audit row, not only in the current state of the table.

    "Why does this person have access?" is a question asked months later, usually about
    somebody whose role has changed twice since. The membership row answers "what are
    they now"; only the log answers "who made them that, and from what".
    """
    tenant_id, slug, token = await _make_tenant("owner")
    actor = await _owner_user_id(tenant_id)
    colleague, _ = await _colleague(tenant_id, name="Priya")

    async with _client() as http:
        promoted = await http.patch(
            f"/v1/members/{colleague}",
            json={"role": "owner", "expected_role": "staff"},
            headers=_headers(slug, token),
        )
        demoted = await http.patch(
            f"/v1/members/{colleague}",
            json={"role": "staff", "expected_role": "owner"},
            headers=_headers(slug, token),
        )

    assert promoted.status_code == 200, promoted.text
    assert promoted.json() == {"id": str(colleague), "name": "Priya", "role": "owner"}
    assert demoted.status_code == 200, demoted.text
    assert await _role_of(tenant_id, colleague) == "staff"

    entries = await _audit_actions(tenant_id)
    assert ("member.role_changed:staff->owner", str(colleague), str(actor)) in entries
    assert ("member.role_changed:owner->staff", str(colleague), str(actor)) in entries


async def test_setting_the_role_someone_already_has_writes_no_audit_row() -> None:
    """Two owners clicking the same promotion is one promotion.

    Worth pinning because the alternative is an audit log that fills with rows saying
    nothing changed — and a log nobody can skim is a log nobody reads.
    """
    tenant_id, slug, token = await _make_tenant("owner")
    colleague, _ = await _colleague(tenant_id, role="staff")

    async with _client() as http:
        response = await http.patch(
            f"/v1/members/{colleague}",
            json={"role": "staff", "expected_role": "staff"},
            headers=_headers(slug, token),
        )

    assert response.status_code == 200, response.text
    assert not [a for a, _, _ in await _audit_actions(tenant_id) if a.startswith("member.")]


# --- escalation 1: staff promoting themselves ---------------------------------


async def test_staff_cannot_promote_themselves_or_anyone_else() -> None:
    """`org:manage` is owner-only, so this is refused at the route guard.

    Asserted anyway, at the HTTP boundary, because the guard is a line in a decorator
    and the thing that would remove it is a refactor that looks harmless.
    """
    tenant_id, slug, _owner_token = await _make_tenant("owner")
    staff_id, staff_token = await _colleague(tenant_id, role="staff")
    other_id, _ = await _colleague(tenant_id, role="staff")

    async with _client() as http:
        himself = await http.patch(
            f"/v1/members/{staff_id}",
            json={"role": "owner", "expected_role": "staff"},
            headers=_headers(slug, staff_token),
        )
        someone_else = await http.patch(
            f"/v1/members/{other_id}",
            json={"role": "owner", "expected_role": "staff"},
            headers=_headers(slug, staff_token),
        )
        invited = await http.post(
            "/v1/invitations",
            json={"email": "outsider@example.com", "role": "owner"},
            headers=_headers(slug, staff_token),
        )

    assert himself.status_code == 403 and himself.json()["kind"] == "permission"
    assert someone_else.status_code == 403
    assert invited.status_code == 403
    assert await _role_of(tenant_id, staff_id) == "staff"
    assert await _role_of(tenant_id, other_id) == "staff"


# --- escalation 2: acting on yourself -----------------------------------------


async def test_an_owner_cannot_change_or_remove_their_own_membership() -> None:
    """Every act on this surface is other-directed (see `_refuse_self`).

    It closes the self-lockout — a sole owner cannot demote themselves into an account
    nobody can govern — and it takes the socially-engineered "click here" out of scope,
    because there is no self-directed change to trick anybody into.
    """
    tenant_id, slug, token = await _make_tenant("owner")
    me = await _owner_user_id(tenant_id)
    await _colleague(tenant_id, role="owner")  # a second owner: not the last-owner rule

    async with _client() as http:
        demote = await http.patch(
            f"/v1/members/{me}",
            json={"role": "staff", "expected_role": "owner"},
            headers=_headers(slug, token),
        )
        remove = await http.delete(f"/v1/members/{me}", headers=_headers(slug, token))

    assert demote.status_code == 422
    assert demote.json()["type"].endswith("/member_self_change_refused")
    assert remove.status_code == 422
    assert await _role_of(tenant_id, me) == "owner", "the caller must still be an owner"


# --- escalation 3: across tenants ---------------------------------------------


async def test_an_owner_cannot_touch_a_membership_in_another_tenant() -> None:
    """The control is the RLS policy on `memberships`, and the target is REAL.

    A random UUID would 404 because no such user exists, which proves nothing about
    isolation. The victim below is an actual owner of an actual second organization, so
    the only thing standing between the request and their row is the tenant policy.
    """
    _tenant_a, slug_a, token_a = await _make_tenant("owner")
    tenant_b, _slug_b, _token_b = await _make_tenant("owner")
    victim = await _owner_user_id(tenant_b)
    await _colleague(tenant_b, role="owner")  # so a demotion would be legal IN tenant B

    async with _client() as http:
        promoted = await http.patch(
            f"/v1/members/{victim}",
            json={"role": "staff", "expected_role": "owner"},
            headers=_headers(slug_a, token_a),
        )
        removed = await http.delete(f"/v1/members/{victim}", headers=_headers(slug_a, token_a))
        listed = await http.get("/v1/members", headers=_headers(slug_a, token_a))

    assert promoted.status_code == 404, promoted.text
    assert removed.status_code == 404
    assert await _role_of(tenant_b, victim) == "owner", "tenant B's owner is untouched"
    assert str(victim) not in {m["id"] for m in listed.json()}


# --- escalation 4: the last owner ---------------------------------------------


async def test_the_last_owner_is_protected_where_the_rule_can_be_reached() -> None:
    """An account with no `org:manage` holder can never again change its own team.

    Asserted against the SERVICE rather than the route, and the reason is worth writing
    down because it looks like a gap. Through today's route table a single request
    cannot reach this rule: only `owner` holds `org:manage`, self-directed changes are
    refused (`_refuse_self`), so an acting owner is by definition a SECOND owner and the
    target is never the last one. The rule is reachable exactly where it matters —
    concurrently, when the second owner is demoted between the caller's authentication
    and the caller's transaction, which is the test below — and it is the guard that has
    to hold the day a third role holds `org:manage`, or an ops path acts on a tenant's
    behalf. A rule that is only correct because of another rule is a rule that breaks
    when the other one is relaxed.

    Both directions are exercised: demotion and removal are two code paths reaching it.
    """
    import pytest
    from apps.api.core.errors import ProblemError
    from apps.api.tenancy import members as members_service

    tenant_id, _slug, _token = await _make_tenant("owner")
    lone_owner = await _owner_user_id(tenant_id)
    bystander, _ = await _colleague(tenant_id, role="staff")

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as demotion:
            await members_service.change_member_role(
                session,
                actor_user_id=bystander,
                actor_role="owner",
                target_user_id=lone_owner,
                new_role="staff",
                expected_role="owner",
            )
        with pytest.raises(ProblemError) as removal:
            await members_service.remove_member(
                session, actor_user_id=bystander, target_user_id=lone_owner
            )

    assert demotion.value.code == "last_owner_protected"
    assert removal.value.code == "last_owner_protected"
    assert await _role_of(tenant_id, lone_owner) == "owner"


async def test_the_last_owner_rule_survives_two_owners_demoting_each_other() -> None:
    """THE RACE, and the reason `lock_owner_ids` is a lock rather than a count.

    Two owners, two concurrent demotions, each targeting the other. Under a
    `SELECT count(*) > 1` guard both transactions read `2`, both proceed, and the tenant
    commits its way to zero owners — recoverable only by us, by hand, in SQL. With the
    row lock the second request blocks, re-evaluates `role = 'owner'` against the
    committed row, and finds one owner left.

    Exactly one of the two must succeed. Asserting "at least one owner remains" would
    also pass if BOTH were refused, which is a different (and also wrong) implementation.
    """
    tenant_id, slug, token_a = await _make_tenant("owner")
    owner_a = await _owner_user_id(tenant_id)
    owner_b, token_b = await _colleague(tenant_id, role="owner")

    async with _client() as http:

        async def demote(target: uuid.UUID, token: str) -> httpx.Response:
            return await http.patch(
                f"/v1/members/{target}",
                json={"role": "staff", "expected_role": "owner"},
                headers=_headers(slug, token),
            )

        first, second = await asyncio.gather(
            demote(owner_b, token_a), demote(owner_a, token_b), return_exceptions=False
        )

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 422], f"{first.status_code}/{second.status_code}: {first.text}"
    loser = first if first.status_code == 422 else second
    assert loser.json()["type"].endswith("/last_owner_protected"), loser.text
    async with tenant_session(tenant_id) as session:
        owners = (
            await session.execute(text("SELECT count(*) FROM memberships WHERE role = 'owner'"))
        ).scalar()
    assert owners == 1, "an account must never be left with nobody who can govern it"


# --- escalation 5: a stale screen ---------------------------------------------


async def test_a_role_change_against_a_stale_screen_is_refused_not_reapplied() -> None:
    """`expected_role` is the CAS (BACKEND-PATTERNS §5).

    The scenario: two owners have the team list open, one demotes a colleague, the other
    clicks "make owner" from a screen that still says `staff`... which is fine. The
    dangerous direction is the opposite — a click made against a role that has since
    changed silently overwriting somebody else's decision. The guard refuses instead.
    """
    tenant_id, slug, token = await _make_tenant("owner")
    colleague, _ = await _colleague(tenant_id, role="staff")

    async with _client() as http:
        await http.patch(
            f"/v1/members/{colleague}",
            json={"role": "owner", "expected_role": "staff"},
            headers=_headers(slug, token),
        )
        stale = await http.patch(
            f"/v1/members/{colleague}",
            json={"role": "staff", "expected_role": "staff"},
            headers=_headers(slug, token),
        )

    assert stale.status_code == 409, stale.text
    assert stale.json()["type"].endswith("/member_role_changed_elsewhere")
    assert await _role_of(tenant_id, colleague) == "owner", "the other owner's change stands"


# --- escalation 6: D-22 -------------------------------------------------------


async def test_an_impersonating_operator_can_see_the_team_and_cannot_change_it() -> None:
    """D-22, both halves, on the surface where getting it wrong is worst.

    A support engineer looking at a client's account must be able to answer "who has
    access here" — and must not be able to grant any. The read is `org:read`, the writes
    are `org:manage`, and `requires()` refuses every mutating permission to an
    impersonating principal.
    """
    tenant_id, slug, _token = await _make_tenant("owner")
    colleague, _ = await _colleague(tenant_id, role="staff")
    admin_token = await _make_operator()

    async with _client() as http:
        # A real D-22 grant: without one every call below would be refused before
        # `requires()` ran, and the three refusals this test exists to pin would be
        # green for the wrong reason.
        headers = await view_as_headers(http, admin_token, slug)
        listed = await http.get("/v1/members", headers=headers)
        invites = await http.get("/v1/invitations", headers=headers)
        promote = await http.patch(
            f"/v1/members/{colleague}",
            json={"role": "owner", "expected_role": "staff"},
            headers=headers,
        )
        remove = await http.delete(f"/v1/members/{colleague}", headers=headers)
        invite = await http.post(
            "/v1/invitations", json={"email": "x@example.com", "role": "owner"}, headers=headers
        )

    assert listed.status_code == 200, listed.text
    assert str(colleague) in {m["id"] for m in listed.json()}
    assert invites.status_code == 200, "support must be able to see who holds a live invite"
    for refused in (promote, remove, invite):
        assert refused.status_code == 403, refused.text
        assert "read-only" in refused.json()["detail"]
    assert await _role_of(tenant_id, colleague) == "staff"


async def _make_operator() -> str:
    """An admin-realm operator (`admin:impersonate`), as a dev bearer token."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:i, 'Support', 'operator', now(), now())"
            ),
            {"i": admin_id},
        )
    return f"dev:admin:{admin_id}"


# --- removal: what happens to the work they were doing -------------------------


async def test_removing_a_member_keeps_their_leads_and_says_how_many() -> None:
    """Removal is not deletion (see `members.remove_member`).

    The membership goes, the lead keeps its `assigned_to`, and the response states the
    count — so an owner cannot remove somebody and be told nothing about the pile of
    work that just stopped having a person attached to it. The lead surfaces already
    render an unresolvable owner as "no longer on this account", which is why nothing
    here has to be nulled to stay honest.
    """
    tenant_id, slug, token = await _make_tenant("owner")
    colleague, _ = await _colleague(tenant_id, role="staff")
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE leads SET assigned_to = :u"), {"u": colleague})

    async with _client() as http:
        removed = await http.delete(f"/v1/members/{colleague}", headers=_headers(slug, token))

    assert removed.status_code == 200, removed.text
    assert removed.json() == {
        "user_id": str(colleague),
        "previous_role": "staff",
        "leads_still_assigned": 1,
    }
    assert await _role_of(tenant_id, colleague) is None

    async with tenant_session(tenant_id) as session:
        assigned = (await session.execute(text("SELECT assigned_to FROM leads LIMIT 1"))).scalar()
        owner_name = (
            await session.execute(
                text(
                    "SELECT owner.name FROM leads l "
                    "LEFT JOIN memberships m ON m.user_id = l.assigned_to "
                    "LEFT JOIN users owner ON owner.id = m.user_id LIMIT 1"
                )
            )
        ).scalar()
    assert uuid.UUID(str(assigned)) == colleague, "the work is not silently unassigned"
    assert owner_name is None, "and the screen resolves it as no longer on this account"

    entries = await _audit_actions(tenant_id)
    assert ("member.removed:staff", str(colleague), str(await _owner_user_id(tenant_id))) in entries


async def test_a_role_cannot_be_granted_by_somebody_who_does_not_hold_it() -> None:
    """`assert_role_is_grantable`, tested directly, and the honesty about why.

    Through today's route table this guard cannot be reached with a failing argument:
    `org:manage` is held only by `owner`, and `owner`'s permission set is a superset of
    `staff`'s, so every caller who gets past the route guard can grant every role that
    exists. A test that drove it through HTTP would therefore be testing the ROUTE guard
    while appearing to test this one — the "sabotage below an earlier guard" mistake, in
    test form.

    It is not decoration: the day a third client role lands (`analyst`, say, or a
    `billing` role holding something `owner` does not), this is the check that stops an
    invitation from being a way around the role table. Its contract is a subset of
    permission sets, and that is what is pinned here.
    """
    import pytest
    from apps.api.core.errors import ProblemError
    from apps.api.tenancy.members import assert_role_is_grantable

    assert_role_is_grantable("owner", "owner")
    assert_role_is_grantable("owner", "staff")

    with pytest.raises(ProblemError) as escalation:
        assert_role_is_grantable("staff", "owner")
    assert escalation.value.status == 403

    with pytest.raises(ProblemError) as unknown:
        assert_role_is_grantable("owner", "superadmin")
    assert unknown.value.code == "member_role_unknown", "roles outside this account's table"
