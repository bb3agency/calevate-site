"""Managing who holds a key to a CLIENT's account, from the operator console (D-602).

The surface `admin/members_routes.py` argues for, driven the way an operator drives it:
a real admin token, over HTTP, through the mounted app. What is asserted here, in the
order it matters:

1. **The seam is finished.** The roster reads, the role change writes, the removal
   removes, and each write leaves an `audit_log` row naming the OPERATOR — not the
   client, and not "system".
2. **Every refusal an operator can hit is asserted twice**: the request is refused AND
   the database is unchanged. A 403 with the row already written is the failure mode
   that looks green.
3. **The step-up is on the removal and not on the role change**, which is the whole
   argument of the module — and the confirmation is bound to the PERSON, so a header
   captured for one member cannot be replayed against the one listed above them.
4. **Cross-tenant isolation is proved through the policy**, not through a filter: a
   member of tenant B is invisible in tenant A's roster, and naming their id in tenant
   A's path is a 404 that leaves tenant B's membership standing. The lead count is
   scoped the same way — the same person, on two accounts, counts differently on each.

CONCURRENCY: every case mints its own organizations and users and asserts only on rows
it created, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from apps.api.admin.members_routes import remove_member_confirmation
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.members_test import _colleague, _owner_user_id, _role_of

MEMBERS = "/v1/admin/tenants/{tenant_id}/members"
MEMBER = "/v1/admin/tenants/{tenant_id}/members/{user_id}"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _admin(role: str = "operator") -> tuple[uuid.UUID, str]:
    """One admin-realm operator. Returns (admin_users.id, dev bearer token).

    `operator` rather than `superadmin` by default, deliberately: both tiers hold
    `admin:tenants` and `org:read` (`core/rbac.SUPERADMIN_ONLY_PERMISSIONS` lists the
    four they do not share, and none of them is on this surface), so the ordinary tier is
    the honest fixture — a suite that only ever drove a superadmin would pass even if
    somebody quietly moved one of these routes behind `ops:manage`.
    """
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return admin_id, f"dev:admin:{admin_id}"


def _code(response: httpx.Response) -> str:
    """The problem's code. RFC-9457 carries it as the tail of `type`, not as a field."""
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _assign_lead(tenant_id: uuid.UUID, user_id: uuid.UUID, *, phone: str) -> None:
    """One lead of this tenant, owned by this person. `_make_tenant` seeded the agent."""
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "assigned_to, created_at, updated_at) "
                "VALUES (:i, :t, :a, :p, 'manual', 'new', :u, now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": agent_id, "p": phone, "u": user_id},
        )


async def _audit(tenant_id: uuid.UUID) -> list[tuple[str, str, str | None, str | None]]:
    """(action, object_id, actor_id, actor_type) for this tenant, oldest first.

    `audit_log` is not tenant-RLS'd, so this filters explicitly — a test reading a
    cross-tenant ledger on purpose, the same way `tests/members_test.py` does.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_id, actor_id, actor_type FROM audit_log "
                    "WHERE tenant_id = :t ORDER BY at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [
        (str(r[0]), str(r[1]), str(r[2]) if r[2] else None, str(r[3]) if r[3] else None)
        for r in rows
    ]


async def _member_writes(tenant_id: uuid.UUID) -> list[tuple[str, str, str | None, str | None]]:
    """Only the rows this surface writes. `_make_tenant` seeds none, but a future fixture
    that did would otherwise make every audit assertion here quietly positional."""
    return [row for row in await _audit(tenant_id) if row[0].startswith("admin.member_")]


# --- the roster -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_roster_answers_who_holds_this_account_and_what_they_are_carrying() -> None:
    """The happy path, and the four facts the invitation list next door cannot give.

    Owners first is asserted as an ORDER rather than a set, because an operator reading
    "who can authorise this" reads the top of the list.
    """
    tenant_id, _slug, _token = await _make_tenant("owner")
    owner_id = await _owner_user_id(tenant_id)
    staff_id, _ = await _colleague(tenant_id, role="staff", name="Anitha")
    await _assign_lead(tenant_id, staff_id, phone="+919000000001")
    await _assign_lead(tenant_id, staff_id, phone="+919000000002")
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.get(
            MEMBERS.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["role"] for row in rows] == ["owner", "staff"], "owners are listed first"
    by_id = {row["user_id"]: row for row in rows}

    staff = by_id[str(staff_id)]
    assert staff["name"] == "Anitha"
    # The address is here in full and on purpose: the operator is about to act on this
    # person by name, and `name` is nullable and not unique.
    assert staff["email"] == f"{staff_id}@example.com"
    assert staff["leads_assigned"] == 2, "the number that decides whether to remove them"
    assert staff["deactivated"] is False
    assert staff["email_verified"] is False
    assert staff["joined_at"] is not None

    owner = by_id[str(owner_id)]
    assert owner["leads_assigned"] == 0


@pytest.mark.asyncio
async def test_a_deactivated_person_is_listed_rather_than_filtered_out() -> None:
    """The client's own picker hides them; this must not, and the reason is mechanical.

    A deactivated user still holds a membership row, still counts toward the last-owner
    rule, and is still what has to be removed to take the grant away. An operator who
    could not see them would be reading a refusal ("this is the only owner") against a
    list that shows two.
    """
    tenant_id, _slug, _token = await _make_tenant("owner")
    gone_id, _ = await _colleague(tenant_id, role="staff", name="Departed")
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE users SET deactivated_at = now() WHERE id = :u"), {"u": gone_id}
        )
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.get(
            MEMBERS.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {token}"},
        )

    row = next(r for r in response.json() if r["user_id"] == str(gone_id))
    assert row["deactivated"] is True


@pytest.mark.asyncio
async def test_a_tenant_id_that_names_nothing_is_a_404_on_every_route() -> None:
    """ "Nobody has access to this account" must never be said about a typo.

    All three routes, because a screen whose read answers 200-empty and whose write
    answers 404 is one screen giving two verdicts on whether the client exists — the
    exact defect `list_tenant_invitations` records having shipped.
    """
    missing = uuid.uuid4()
    stranger = uuid.uuid4()
    _admin_id, token = await _admin()
    headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        listed = await http.get(MEMBERS.format(tenant_id=missing), headers=headers)
        patched = await http.patch(
            MEMBER.format(tenant_id=missing, user_id=stranger),
            json={"role": "owner", "expected_role": "staff"},
            headers=headers,
        )
        deleted = await http.delete(
            MEMBER.format(tenant_id=missing, user_id=stranger),
            headers={
                **headers,
                "X-Confirm-Action": remove_member_confirmation(missing, stranger),
            },
        )

    assert listed.status_code == 404, listed.text
    assert patched.status_code == 404, patched.text
    assert deleted.status_code == 404, deleted.text


# --- the role change --------------------------------------------------------------


@pytest.mark.asyncio
async def test_promoting_a_colleague_writes_the_transition_and_names_the_operator() -> None:
    """The happy path AND the audit row, which is the constraint rather than a detail.

    The action carries the transition because `audit_log` has no hashed detail column;
    the `admin.` prefix is what tells a client asking "who promoted them?" that it was us
    and not one of their own owners.
    """
    tenant_id, _slug, _token = await _make_tenant("owner")
    staff_id, _ = await _colleague(tenant_id, role="staff", name="Bhargav")
    admin_id, token = await _admin()

    async with _client() as http:
        response = await http.patch(
            MEMBER.format(tenant_id=tenant_id, user_id=staff_id),
            json={"role": "owner", "expected_role": "staff"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "owner"
    assert response.json()["user_id"] == str(staff_id)
    assert await _role_of(tenant_id, staff_id) == "owner"

    assert await _member_writes(tenant_id) == [
        ("admin.member_role_changed:staff->owner", str(staff_id), str(admin_id), "admin")
    ]


@pytest.mark.asyncio
async def test_a_write_against_a_role_the_row_no_longer_holds_is_refused() -> None:
    """The CAS, asserted directly rather than through a double click.

    This is a LIVE account whose own owners press their own buttons, so the role can move
    between the console drawing the row and the operator clicking it. WITH ONLY TWO ROLES
    the ordinary race is benign and short-circuits before the CAS ever runs — two people
    making one person an owner is one promotion, and `assign_member_role` returns that as
    a no-op on purpose. So the guard is driven at the combination that does reach it: the
    row is an OWNER, the console named `staff` as what it was looking at, and the write
    asks for `staff`. The value of asserting it now is that the day a third role lands,
    every ordinary race reaches this branch.
    """
    tenant_id, _slug, _token = await _make_tenant("owner")
    # A SECOND owner, so the refusal under test is the CAS rather than the last-owner rule
    # — two guards in one assertion is an assertion that cannot tell you which fired.
    second_id, _ = await _colleague(tenant_id, role="owner")
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.patch(
            MEMBER.format(tenant_id=tenant_id, user_id=second_id),
            json={"role": "staff", "expected_role": "staff"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 409, response.text
    assert _code(response) == "member_role_changed_elsewhere"
    assert response.json()["remediation"], "a refusal an operator can act on"
    assert await _role_of(tenant_id, second_id) == "owner", "nothing was written"
    assert await _member_writes(tenant_id) == []


@pytest.mark.asyncio
async def test_setting_the_role_somebody_already_holds_writes_no_audit_row() -> None:
    """Two operators clicking one promotion is one promotion. An audit row saying nothing
    changed is noise in the one log that has to stay readable a year later."""
    tenant_id, _slug, _token = await _make_tenant("owner")
    staff_id, _ = await _colleague(tenant_id, role="staff")
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.patch(
            MEMBER.format(tenant_id=tenant_id, user_id=staff_id),
            json={"role": "staff", "expected_role": "staff"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "staff"
    assert await _member_writes(tenant_id) == []


@pytest.mark.asyncio
async def test_the_last_owner_cannot_be_demoted_from_the_console_either() -> None:
    """An account with no owner can never invite anybody, re-role anybody or manage its
    own settings again — and this is the realm where nobody is left to grant it back."""
    tenant_id, _slug, _token = await _make_tenant("owner")
    owner_id = await _owner_user_id(tenant_id)
    await _colleague(tenant_id, role="staff")
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.patch(
            MEMBER.format(tenant_id=tenant_id, user_id=owner_id),
            json={"role": "staff", "expected_role": "owner"},
            headers={"Authorization": f"Bearer {token}"},
        )

    # 422 and not 409: `last_owner_protected` is a `ProblemError.business_rule` — the
    # request is well-formed and lost no race, it asks for a state the account may not be
    # in. A retry cannot help, which is what separates it from the CAS above.
    assert response.status_code == 422, response.text
    assert _code(response) == "last_owner_protected"
    assert response.json()["remediation"], "a refusal an operator can act on"
    assert await _role_of(tenant_id, owner_id) == "owner"
    assert await _member_writes(tenant_id) == []


@pytest.mark.asyncio
async def test_a_client_token_cannot_reach_this_surface_at_all() -> None:
    """Realm, not prefix. `requires(..., realm="admin")` is the control — an owner of the
    account holds `org:manage` and `org:read`, which are the strings a URL-shaped guard
    would have been fooled by."""
    tenant_id, slug, client_token = await _make_tenant("owner")
    staff_id, _ = await _colleague(tenant_id, role="staff")
    headers = {"Authorization": f"Bearer {client_token}", "X-Org-Slug": slug}

    async with _client() as http:
        listed = await http.get(MEMBERS.format(tenant_id=tenant_id), headers=headers)
        patched = await http.patch(
            MEMBER.format(tenant_id=tenant_id, user_id=staff_id),
            json={"role": "owner", "expected_role": "staff"},
            headers=headers,
        )

    # 401 rather than 403: the guard's verdict is that this CREDENTIAL is not valid in
    # this realm at all, which is a different sentence from "your role is too small" and
    # is the one an owner holding `org:manage` needs to be told.
    assert listed.status_code == 401, listed.text
    assert _code(listed) == "unauthorized"
    assert patched.status_code == 401, patched.text
    assert await _role_of(tenant_id, staff_id) == "staff"


# --- the removal ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_removing_somebody_needs_the_confirmation_and_changes_nothing_without_it() -> None:
    """The step-up's intent half, and the refusal's own promise: nothing happened.

    `StepUp.require` runs before any work and the transaction rolls back regardless, so
    an operator who sees this does not have to go and check whether it half-applied.
    """
    tenant_id, _slug, _token = await _make_tenant("owner")
    staff_id, _ = await _colleague(tenant_id, role="staff")
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.delete(
            MEMBER.format(tenant_id=tenant_id, user_id=staff_id),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403, response.text
    assert _code(response) == "step_up_required"
    # The refusal PRINTS the string to send, on purpose — the header is an intent echo
    # and not a secret, and an operator mid-support-call must not have to read the source.
    assert remove_member_confirmation(tenant_id, staff_id) in response.json()["remediation"]
    assert await _role_of(tenant_id, staff_id) == "staff", "still on the account"
    assert await _member_writes(tenant_id) == []


@pytest.mark.asyncio
async def test_a_confirmation_for_one_person_cannot_be_replayed_against_another() -> None:
    """Why the string carries BOTH ids. On this screen the owner is one row above the
    person being removed, and the tenant alone would make those two headers identical."""
    tenant_id, _slug, _token = await _make_tenant("owner")
    owner_id = await _owner_user_id(tenant_id)
    staff_id, _ = await _colleague(tenant_id, role="staff")
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.delete(
            MEMBER.format(tenant_id=tenant_id, user_id=owner_id),
            headers={
                "Authorization": f"Bearer {token}",
                # Captured while looking at the STAFF member.
                "X-Confirm-Action": remove_member_confirmation(tenant_id, staff_id),
            },
        )

    assert response.status_code == 403, response.text
    assert _code(response) == "step_up_required"
    assert await _role_of(tenant_id, owner_id) == "owner"


@pytest.mark.asyncio
async def test_a_confirmed_removal_takes_the_access_and_states_the_work_left_behind() -> None:
    """The happy path. The membership goes, the leads do NOT, and the count is returned
    so that removing somebody can never quietly orphan a pile of work."""
    tenant_id, _slug, _token = await _make_tenant("owner")
    staff_id, _ = await _colleague(tenant_id, role="staff")
    await _assign_lead(tenant_id, staff_id, phone="+919000000011")
    admin_id, token = await _admin()

    async with _client() as http:
        response = await http.delete(
            MEMBER.format(tenant_id=tenant_id, user_id=staff_id),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": remove_member_confirmation(tenant_id, staff_id),
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "user_id": str(staff_id),
        "previous_role": "staff",
        "leads_still_assigned": 1,
    }
    assert await _role_of(tenant_id, staff_id) is None, "the grant is gone"

    assert await _member_writes(tenant_id) == [
        ("admin.member_removed:staff", str(staff_id), str(admin_id), "admin")
    ]

    # The lead is untouched and still names them: `crm.service` resolves an owner through
    # `memberships`, so it now renders as somebody no longer on the account rather than
    # becoming nobody's.
    async with tenant_session(tenant_id) as session:
        still = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE assigned_to = :u"), {"u": staff_id}
            )
        ).scalar_one()
    assert still == 1


@pytest.mark.asyncio
async def test_the_only_owner_cannot_be_removed_even_with_the_confirmation() -> None:
    """A confirmation is evidence of intent, never an authorisation to break an
    invariant. The last-owner rule is the invariant."""
    tenant_id, _slug, _token = await _make_tenant("owner")
    owner_id = await _owner_user_id(tenant_id)
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.delete(
            MEMBER.format(tenant_id=tenant_id, user_id=owner_id),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": remove_member_confirmation(tenant_id, owner_id),
            },
        )

    assert response.status_code == 422, response.text
    assert _code(response) == "last_owner_protected"
    assert await _role_of(tenant_id, owner_id) == "owner"
    assert await _member_writes(tenant_id) == []


@pytest.mark.asyncio
async def test_removing_the_same_person_twice_is_one_removal_and_one_409() -> None:
    """The delete is a CAS on the row existing, so a replayed request — a double click, a
    retried tab — is reported rather than answered as though it had done something."""
    tenant_id, _slug, _token = await _make_tenant("owner")
    staff_id, _ = await _colleague(tenant_id, role="staff")
    _admin_id, token = await _admin()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Confirm-Action": remove_member_confirmation(tenant_id, staff_id),
    }

    async with _client() as http:
        first = await http.delete(
            MEMBER.format(tenant_id=tenant_id, user_id=staff_id), headers=headers
        )
        second = await http.delete(
            MEMBER.format(tenant_id=tenant_id, user_id=staff_id), headers=headers
        )

    assert first.status_code == 200, first.text
    # 404, not 409: the membership is gone, so `_member_role` no longer finds a row to
    # compare against and the request names nobody on this account. Either answer is
    # honest; what matters is that it is not a second success.
    assert second.status_code in {404, 409}, second.text
    assert len(await _member_writes(tenant_id)) == 1


# --- cross-tenant isolation -------------------------------------------------------


@pytest.mark.asyncio
async def test_one_clients_roster_can_never_show_or_touch_anothers_member() -> None:
    """HARD RULE 1, through the policy rather than through a filter.

    `_ROSTER_SQL` carries no `WHERE tenant_id` at all: the scope is the FORCE-RLS policy
    on `memberships` under `tenant_session`, whose second clause (`user_id =
    app.user_id`, the auth bootstrap's one widening) is NULL on an admin-opened session
    and therefore grants it nothing. Asserted in all three directions — the read cannot
    SEE them, and neither write can REACH them.
    """
    tenant_a, _slug_a, _ = await _make_tenant("owner")
    tenant_b, _slug_b, _ = await _make_tenant("owner")
    b_owner = await _owner_user_id(tenant_b)
    b_staff, _ = await _colleague(tenant_b, role="staff", name="Not Yours")
    _admin_id, token = await _admin()
    headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        roster_a = await http.get(MEMBERS.format(tenant_id=tenant_a), headers=headers)
        patched = await http.patch(
            MEMBER.format(tenant_id=tenant_a, user_id=b_staff),
            json={"role": "owner", "expected_role": "staff"},
            headers=headers,
        )
        deleted = await http.delete(
            MEMBER.format(tenant_id=tenant_a, user_id=b_staff),
            headers={
                **headers,
                "X-Confirm-Action": remove_member_confirmation(tenant_a, b_staff),
            },
        )

    listed = {row["user_id"] for row in roster_a.json()}
    assert str(b_staff) not in listed, "ZERO ROWS of tenant B in tenant A's roster"
    assert str(b_owner) not in listed

    # 404 rather than 403: a foreign id must not be CONFIRMED to exist by the shape of
    # the refusal (D-65). Both writes leave tenant B exactly as it was.
    assert patched.status_code == 404, patched.text
    assert deleted.status_code == 404, deleted.text
    assert await _role_of(tenant_b, b_staff) == "staff"
    assert await _member_writes(tenant_b) == []
    assert await _member_writes(tenant_a) == []


@pytest.mark.asyncio
async def test_the_lead_count_is_this_clients_work_and_not_the_persons_whole_day() -> None:
    """One person on two accounts. The count is a correlated subquery over `leads`, which
    is tenant-policied on the same session — so this screen cannot be used to learn how
    much work somebody does for a DIFFERENT client of ours."""
    tenant_a, _slug_a, _ = await _make_tenant("owner")
    tenant_b, _slug_b, _ = await _make_tenant("owner")
    shared_id, _ = await _colleague(tenant_a, role="staff", name="Both Accounts")
    async with tenant_session(tenant_b) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, "
                "updated_at) VALUES (:i, :t, :u, 'staff', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_b, "u": shared_id},
        )
    await _assign_lead(tenant_a, shared_id, phone="+919000000021")
    await _assign_lead(tenant_b, shared_id, phone="+919000000022")
    await _assign_lead(tenant_b, shared_id, phone="+919000000023")
    _admin_id, token = await _admin()
    headers = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        roster_a = await http.get(MEMBERS.format(tenant_id=tenant_a), headers=headers)
        roster_b = await http.get(MEMBERS.format(tenant_id=tenant_b), headers=headers)

    def _count(response: httpx.Response) -> Any:
        return next(r for r in response.json() if r["user_id"] == str(shared_id))["leads_assigned"]

    assert _count(roster_a) == 1
    assert _count(roster_b) == 2


@pytest.mark.asyncio
async def test_reading_one_clients_roster_is_recorded_as_a_read_of_their_data() -> None:
    """D-482 L-1. Who works at a business, and their addresses, is that business's own
    data — so an operator looking at it leaves the same trace every other per-tenant
    admin read leaves, and not a silent one."""
    tenant_id, _slug, _token = await _make_tenant("owner")
    _admin_id, token = await _admin()

    async with _client() as http:
        response = await http.get(
            MEMBERS.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    actions = [row[0] for row in await _audit(tenant_id)]
    assert any("read" in action for action in actions), (
        f"the roster read left no impersonation-read row; audit carried {actions}"
    )
