"""The two admin tiers: what a super admin can do that a normal admin cannot.

The founder's sentence is the specification — "I'm the super admin who has everything
literally everything editable, and then I can add more admins who are NOT super admins" —
and this file is the executable form of it. It is ordered by what each failure costs.

1. **A normal admin cannot reach the surface that edits the role table.** If they could,
   the two tiers would differ only in how many requests an escalation takes. Driven at
   every one of the five routes, not asserted from `ROLE_PERMISSIONS`, because a
   permission held by nobody and a route that forgot its dependency read identically from
   the role table.
2. **Nobody administers their own account.** With (1), that is what makes "at least one
   live superadmin" an invariant rather than a hope — `authn/operators.py` derives it —
   and it is why every row in this part of the ledger names two different people.
3. **Authority is re-read per request.** A demotion and a revocation must bite on the
   target's NEXT call, not when their cookie expires. This is the property that makes a
   revocation a security control rather than a database edit.
4. **The lifecycle works**, including the parts that are easy to leave half-wired: the
   setup link is mailed and never returned, the password and sessions die with the
   account, the row survives for the eight foreign keys that reference it, and a second
   revocation is a 404 rather than a second ledger row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import get_args
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.authn import operators
from apps.api.authn.bootstrap import ADMIN_REALM
from apps.api.authn.credentials import delete_password, set_password, subjects_with_password
from apps.api.authn.subjects import load_subject, resolve_by_email
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import (
    ADMIN_ROLES,
    GRANTED_PERMISSIONS,
    KNOWN_PERMISSIONS,
    MUTATING_PERMISSIONS,
    NORMAL_ADMIN_ROLE,
    ROLE_PERMISSIONS,
    SUPERADMIN_ROLE,
    role_has,
)
from apps.api.db.session import credential_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.impersonation_grant_test import view_as_headers

REASON = {"reason": "lane S1 test"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


def _address() -> str:
    return f"ops-{uuid.uuid4().hex[:12]}@example.com"


def _principal(admin_id: UUID, role: str = SUPERADMIN_ROLE) -> Principal:
    return Principal(realm="admin", user_id=admin_id, tenant_id=None, role=role)


def _id_of(token: str) -> UUID:
    """`dev:admin:<uuid>` → the uuid. `_make_admin` hands back the token, not the id."""
    return UUID(token.rsplit(":", 1)[1])


async def _make_operator(role: str = NORMAL_ADMIN_ROLE) -> UUID:
    """An operator account created THROUGH the service, so its ledger row exists too."""
    account = await operators.create_operator(
        actor=_principal(_id_of(await _make_admin())),
        email=_address(),
        name="Colleague",
        role=role,  # type: ignore[arg-type]  # the caller passes one of the two literals
        reason="fixture",
        ip=None,
    )
    return account.id


# ---------------------------------------------------------------- 1. the tier boundary


def test_the_super_admin_holds_everything_literally_everything() -> None:
    """The founder's words, as an equality.

    DERIVED rather than listed (`core/rbac.SUPERADMIN_PERMISSIONS`), so this cannot fail
    by somebody adding a permission and forgetting a role — which is the whole reason it
    is derived. What it CAN still catch is the derivation being replaced by a longhand set
    in a future edit, which is exactly when the drift would restart.
    """
    assert ROLE_PERMISSIONS[SUPERADMIN_ROLE] == KNOWN_PERMISSIONS
    assert GRANTED_PERMISSIONS == KNOWN_PERMISSIONS


def test_the_normal_admin_tier_holds_none_of_the_four_platform_authorities() -> None:
    """The exact list of what a normal admin cannot do, stated once and asserted.

    `admin:operators` is the load-bearing one — it is the permission that could grant the
    other three — and the other three are the surfaces the founder's question named. Each
    is spelled out rather than covered by a prefix scan, because a prefix rename would
    make a scan pass while the grant changed.
    """
    for permission in ("admin:operators", "platform:secrets", "platform:config", "ops:manage"):
        assert not role_has(NORMAL_ADMIN_ROLE, permission), (  # type: ignore[arg-type]
            f"the normal admin tier gained {permission} — that is a decision-log change, "
            "not an edit"
        )
    # And the containment, so a permission cannot be added to the normal tier without
    # `superadmin` having it: a normal admin more able than the platform's owner is the
    # drift this pairing catches in the other direction.
    assert ROLE_PERMISSIONS[NORMAL_ADMIN_ROLE] < ROLE_PERMISSIONS[SUPERADMIN_ROLE]


def test_managing_operators_is_a_mutating_permission() -> None:
    """D-22: a read-only view-as session must not be able to hand somebody an account.

    Listed in `MUTATING_PERMISSIONS`, which also hides `GET /v1/admin/operators` from
    impersonation — `tests/impersonation_reads_test.ADMIN_CONSOLE_GETS` carries the reason
    that is correct.
    """
    assert "admin:operators" in MUTATING_PERMISSIONS


def test_the_role_names_the_literal_admits_are_the_role_names_the_table_uses() -> None:
    """`AdminRole` is a `Literal` and cannot be BUILT from constants, so the Literal itself
    is compared here — against `core/rbac.ADMIN_ROLES`, which renders the CHECK constraint,
    and against the role table's own admin keys. A third tuple written out somewhere to be
    compared would be the drift rather than the guard."""
    assert set(get_args(operators.AdminRole)) == set(ADMIN_ROLES)
    assert set(ADMIN_ROLES) == set(ROLE_PERMISSIONS) - {"owner", "staff"}


async def test_a_normal_admin_is_refused_at_every_operator_route() -> None:
    """The whole security property, driven rather than derived.

    All five, because a permission is enforced per route by whoever wrote the decorator:
    the boot assertion proves each route DECLARES one, and only a request proves the lock
    is on the door. The confirmation headers are supplied so the refusal is the
    PERMISSION's and not step-up's — a 403 for the wrong reason would leave this green if
    somebody later dropped the permission dependency.
    """
    normal = await _make_admin(NORMAL_ADMIN_ROLE)
    target = await _make_operator()
    async with _client() as http:
        responses = {
            "list": await http.get("/v1/admin/operators", headers=_headers(normal)),
            "create": await http.post(
                "/v1/admin/operators",
                headers=_headers(normal, "add_operator:superadmin"),
                json={"email": _address(), "role": "superadmin", **REASON},
            ),
            "promote": await http.patch(
                f"/v1/admin/operators/{target}",
                headers=_headers(normal, f"set_operator_role:{target}"),
                json={"role": "superadmin", **REASON},
            ),
            "revoke": await http.post(
                f"/v1/admin/operators/{target}/revocation",
                headers=_headers(normal, f"revoke_operator:{target}"),
                json=REASON,
            ),
            "resend": await http.post(
                f"/v1/admin/operators/{target}/setup-link",
                headers=_headers(normal, f"reissue_operator_setup_link:{target}"),
                json=REASON,
            ),
        }
    for name, response in responses.items():
        assert response.status_code == 403, f"{name}: {response.status_code} {response.text}"
        assert "admin:operators" in response.json()["detail"], f"{name}: {response.text}"

    # The account it tried to promote itself through is untouched.
    async with untenanted_session() as session:
        role = (
            await session.execute(
                text("SELECT role FROM admin_users WHERE id = :id"), {"id": target}
            )
        ).scalar()
    assert role == NORMAL_ADMIN_ROLE


async def test_a_normal_admin_cannot_promote_themselves() -> None:
    """The escalation the tiers exist to prevent, aimed at the attacker's own account.

    Worth its own test beside the sweep above: the sweep aims at somebody else, and the
    interesting request is the one where the actor and the subject are the same person —
    the shape a self-service escalation actually takes.
    """
    normal = await _make_admin(NORMAL_ADMIN_ROLE)
    own_id = _id_of(normal)
    async with _client() as http:
        response = await http.patch(
            f"/v1/admin/operators/{own_id}",
            headers=_headers(normal, f"set_operator_role:{own_id}"),
            json={"role": "superadmin", **REASON},
        )
    assert response.status_code == 403, response.text
    async with untenanted_session() as session:
        role = (
            await session.execute(
                text("SELECT role FROM admin_users WHERE id = :id"), {"id": own_id}
            )
        ).scalar()
    assert role == NORMAL_ADMIN_ROLE, "a normal admin promoted themselves"


async def test_even_a_superadmin_cannot_change_or_revoke_their_own_account() -> None:
    """Fact 2 of the three the invariant rests on.

    A superadmin who could demote or revoke themselves could leave the platform with no
    superadmin at all — nobody able to install a credential, add an operator or reach the
    big red switch — and the only repair would be a hand-written UPDATE against
    production. It is also what keeps every row here naming two people.
    """
    token = await _make_admin()
    own_id = _id_of(token)
    async with _client() as http:
        demote = await http.patch(
            f"/v1/admin/operators/{own_id}",
            headers=_headers(token, f"set_operator_role:{own_id}"),
            json={"role": "operator", **REASON},
        )
        revoke = await http.post(
            f"/v1/admin/operators/{own_id}/revocation",
            headers=_headers(token, f"revoke_operator:{own_id}"),
            json=REASON,
        )
    for name, response in (("demote", demote), ("revoke", revoke)):
        assert response.status_code == 403, f"{name}: {response.text}"
        assert response.json()["type"].endswith("/operator_self_administration"), response.text
        assert "another superadmin" in response.json()["remediation"]

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT role, deactivated_at FROM admin_users WHERE id = :id"), {"id": own_id}
            )
        ).first()
    assert row is not None and row[0] == SUPERADMIN_ROLE and row[1] is None


async def test_the_platform_always_keeps_a_live_superadmin() -> None:
    """The invariant, driven instead of guarded.

    `authn/operators.py` argues that a `count(*) WHERE role = 'superadmin'` check could
    never fire — the actor holds `admin:operators`, so they ARE a live superadmin, and
    they cannot aim at themselves — so the invariant is asserted here by trying the only
    two moves that could break it and reading the table afterwards.
    """
    first = await _make_admin()
    second_id = await _make_operator(SUPERADMIN_ROLE)
    async with _client() as http:
        # The second superadmin demotes the first: allowed, and there is still one left.
        demoted = await http.patch(
            f"/v1/admin/operators/{_id_of(first)}",
            headers=_headers(f"dev:admin:{second_id}", f"set_operator_role:{_id_of(first)}"),
            json={"role": "operator", **REASON},
        )
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == NORMAL_ADMIN_ROLE
    async with untenanted_session() as session:
        live = (
            await session.execute(
                text(
                    "SELECT count(*) FROM admin_users "
                    "WHERE role = 'superadmin' AND deactivated_at IS NULL"
                )
            )
        ).scalar()
    assert live and live >= 1


# ------------------------------------------------- 2. authority is re-read every request


async def test_a_demotion_bites_on_the_next_request() -> None:
    """BACKEND-PATTERNS §7's rule for the admin realm, which had no column to read it from
    until now: the role comes off `admin_users` on every request, so a demoted operator
    loses the console's dangerous surfaces immediately rather than at cookie expiry."""
    target_id = await _make_operator(SUPERADMIN_ROLE)
    token = f"dev:admin:{target_id}"
    async with _client() as http:
        before = await http.get("/v1/admin/operators", headers=_headers(token))
        assert before.status_code == 200, before.text

        actor = await _make_admin()
        demote = await http.patch(
            f"/v1/admin/operators/{target_id}",
            headers=_headers(actor, f"set_operator_role:{target_id}"),
            json={"role": "operator", **REASON},
        )
        assert demote.status_code == 200, demote.text

        after = await http.get("/v1/admin/operators", headers=_headers(token))
    assert after.status_code == 403, after.text


async def test_a_revoked_operator_cannot_authenticate_at_all() -> None:
    """The liveness predicate `core/auth._load_admin_principal` gained.

    `/v1/admin/me` is the cheapest admin-realm route there is and it is the one a console
    calls first, so proving the refusal there proves it for the realm: the principal is
    never constructed.
    """
    target_id = await _make_operator()
    token = f"dev:admin:{target_id}"
    async with _client() as http:
        assert (await http.get("/v1/admin/me", headers=_headers(token))).status_code == 200
        actor = await _make_admin()
        revoked = await http.post(
            f"/v1/admin/operators/{target_id}/revocation",
            headers=_headers(actor, f"revoke_operator:{target_id}"),
            json=REASON,
        )
        assert revoked.status_code == 200, revoked.text
        after = await http.get("/v1/admin/me", headers=_headers(token))
    assert after.status_code == 403, after.text
    assert "no admin access" in after.json()["detail"]


# ------------------------------------------------------------------ 3. the lifecycle


async def test_creating_an_operator_mails_a_link_and_returns_none_of_it() -> None:
    """The account exists, the invitation is queued in the SAME transaction, and no part
    of the token is in the response — D-190's rule applied to the admin realm.

    The outbox row is the assertion that the mail leg is wired: an account created without
    one is an operator who can never sign in and a screen that says otherwise.
    """
    actor = await _make_admin()
    address = _address()
    async with _client() as http:
        created = await http.post(
            "/v1/admin/operators",
            headers=_headers(actor, "add_operator:operator"),
            json={"email": address, "name": "Asha", **REASON},
        )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["role"] == NORMAL_ADMIN_ROLE, "the default tier is the narrow one"
    assert body["activated"] is False
    assert "token" not in body and "link" not in body and "password" not in body

    operator_id = UUID(body["id"])
    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages "
                    "WHERE job = 'deliver_auth_email' AND payload->>'to' = :to "
                    "AND payload->>'kind' = 'admin_bootstrap'"
                ),
                {"to": address},
            )
        ).scalar()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE action = 'admin.operator_created' AND object_id = :oid"
                ),
                {"oid": str(operator_id)},
            )
        ).scalar()
    assert queued == 1, "the setup link was not queued for delivery"
    assert audited == 1, "creating an operator account left no ledger entry"

    async with credential_session() as session:
        token_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_email_tokens "
                    "WHERE purpose = 'admin_bootstrap' AND subject_id = :sid AND used_at IS NULL"
                ),
                {"sid": operator_id},
            )
        ).scalar()
    assert token_rows == 1


async def test_two_live_operators_cannot_share_an_address() -> None:
    """The partial unique index decides it, and the loser gets a 409 rather than a 500.

    Written as a second CREATE rather than as a race, because the index is what makes the
    race safe: what this pins is that the `IntegrityError` is translated at the boundary
    instead of escaping as an internal error.
    """
    actor = await _make_admin()
    address = _address()
    async with _client() as http:
        first = await http.post(
            "/v1/admin/operators",
            headers=_headers(actor, "add_operator:operator"),
            json={"email": address, **REASON},
        )
        second = await http.post(
            "/v1/admin/operators",
            headers=_headers(actor, "add_operator:operator"),
            json={"email": address, **REASON},
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["type"].endswith("/operator_email_taken")


async def test_a_revoked_address_can_be_used_again() -> None:
    """What the PARTIAL index buys, and the reason the migration made it partial.

    An unconditional unique index would spend an address permanently on the first
    revocation, so re-hiring somebody — or undoing a revocation made in error — would be
    impossible while the revoked row is kept for the eight foreign keys that reference it.
    """
    actor = await _make_admin()
    address = _address()
    async with _client() as http:
        first = await http.post(
            "/v1/admin/operators",
            headers=_headers(actor, "add_operator:operator"),
            json={"email": address, **REASON},
        )
        assert first.status_code == 201, first.text
        operator_id = first.json()["id"]
        revoked = await http.post(
            f"/v1/admin/operators/{operator_id}/revocation",
            headers=_headers(actor, f"revoke_operator:{operator_id}"),
            json=REASON,
        )
        assert revoked.status_code == 200, revoked.text
        again = await http.post(
            "/v1/admin/operators",
            headers=_headers(actor, "add_operator:operator"),
            json={"email": address, **REASON},
        )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != operator_id, "the old row was reused instead of a new one"


async def test_revocation_keeps_the_row_and_destroys_the_credential() -> None:
    """Both halves of the trade, in one place.

    The row must survive — eight tables reference it as the record of who decided what —
    and the authentication material must not, because a password left behind for an
    account that can never sign in is what a restore or a mistaken reactivation would
    quietly resurrect.
    """
    actor = await _make_admin()
    operator_id = await _make_operator()
    async with credential_session() as session:
        await set_password(
            session, realm=ADMIN_REALM, subject_id=operator_id, password="a-real-password-9"
        )

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/operators/{operator_id}/revocation",
            headers=_headers(actor, f"revoke_operator:{operator_id}"),
            json=REASON,
        )
    assert response.status_code == 200, response.text
    assert response.json()["activated"] is False

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT deactivated_at FROM admin_users WHERE id = :id"), {"id": operator_id}
            )
        ).first()
    assert row is not None, "the row was deleted — eight foreign keys reference it"
    assert row[0] is not None

    async with credential_session() as session:
        remaining = await subjects_with_password(
            session, realm=ADMIN_REALM, subject_ids=[operator_id]
        )
        live_tokens = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_email_tokens "
                    "WHERE subject_id = :sid AND used_at IS NULL"
                ),
                {"sid": operator_id},
            )
        ).scalar()
    assert not remaining, "the revoked operator kept their password"
    assert live_tokens == 0, "an outstanding setup link survived the revocation"


async def test_revoking_twice_is_a_404_and_not_a_second_ledger_row() -> None:
    """The CAS is the idempotence: `WHERE deactivated_at IS NULL` decides, so a
    double-clicked Revoke cannot enter one act into a tamper-evident log twice."""
    actor = await _make_admin()
    operator_id = await _make_operator()
    async with _client() as http:
        first = await http.post(
            f"/v1/admin/operators/{operator_id}/revocation",
            headers=_headers(actor, f"revoke_operator:{operator_id}"),
            json=REASON,
        )
        second = await http.post(
            f"/v1/admin/operators/{operator_id}/revocation",
            headers=_headers(actor, f"revoke_operator:{operator_id}"),
            json=REASON,
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 404, second.text
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE action = 'admin.operator_revoked' AND object_id = :oid"
                ),
                {"oid": str(operator_id)},
            )
        ).scalar()
    assert rows == 1


async def test_setting_the_role_an_operator_already_has_writes_nothing() -> None:
    """A no-op must not appear in the ledger as a promotion, and must not sign anybody out.

    The same rule `platform.config_set` follows, and the reason is the same: a
    double-clicked Save is one act.
    """
    actor = await _make_admin()
    operator_id = await _make_operator()
    async with _client() as http:
        response = await http.patch(
            f"/v1/admin/operators/{operator_id}",
            headers=_headers(actor, f"set_operator_role:{operator_id}"),
            json={"role": NORMAL_ADMIN_ROLE, **REASON},
        )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == NORMAL_ADMIN_ROLE
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE action = 'admin.operator_role_changed' AND object_id = :oid"
                ),
                {"oid": str(operator_id)},
            )
        ).scalar()
    assert rows == 0, "a no-op was recorded as a role change"


async def test_a_role_change_on_a_revoked_operator_is_a_404() -> None:
    """The other state a rowcount of 0 can mean. The CAS cannot distinguish them, so the
    read that follows it does — otherwise a promotion aimed at a revoked account would
    answer 200 and change nothing."""
    actor = await _make_admin()
    operator_id = await _make_operator()
    await operators.revoke_operator(
        actor=_principal(_id_of(actor)), operator_id=operator_id, reason="fixture", ip=None
    )
    async with _client() as http:
        response = await http.patch(
            f"/v1/admin/operators/{operator_id}",
            headers=_headers(actor, f"set_operator_role:{operator_id}"),
            json={"role": "superadmin", **REASON},
        )
    assert response.status_code == 404, response.text


async def test_the_setup_link_can_be_resent_and_only_the_newest_one_works() -> None:
    """Needed rather than convenient: the link lives an hour, and the address is held by
    the partial unique index — so without this an account whose invitation expired could
    never be signed into and could not be recreated either."""
    actor = await _make_admin()
    operator_id = await _make_operator()
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/operators/{operator_id}/setup-link",
            headers=_headers(actor, f"reissue_operator_setup_link:{operator_id}"),
            json=REASON,
        )
    assert response.status_code == 200, response.text
    async with credential_session() as session:
        live = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_email_tokens "
                    "WHERE purpose = 'admin_bootstrap' AND subject_id = :sid "
                    "AND used_at IS NULL"
                ),
                {"sid": operator_id},
            )
        ).scalar()
    assert live == 1, "the previous setup link was left live beside the new one"


async def test_resending_is_refused_for_an_operator_who_already_has_a_password() -> None:
    """This is not a password reset and must not be usable as one — otherwise a superadmin
    could take over a colleague's account by mailing themselves nothing and waiting, and
    the audit trail would read as a resend."""
    actor = await _make_admin()
    operator_id = await _make_operator()
    async with credential_session() as session:
        await set_password(
            session, realm=ADMIN_REALM, subject_id=operator_id, password="a-real-password-9"
        )
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/operators/{operator_id}/setup-link",
            headers=_headers(actor, f"reissue_operator_setup_link:{operator_id}"),
            json=REASON,
        )
    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/operator_already_activated")


async def test_an_operator_row_with_no_address_cannot_be_sent_a_link() -> None:
    """The Clerk-era shape (`admin_users.email` is nullable for exactly those rows).
    Issuing a token for a mailbox that does not exist would report success for a message
    that cannot be composed."""
    actor = await _make_admin()
    legacy_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Legacy', 'operator', now(), now())"
            ),
            {"id": legacy_id},
        )
    async with _client() as http:
        response = await http.post(
            f"/v1/admin/operators/{legacy_id}/setup-link",
            headers=_headers(actor, f"reissue_operator_setup_link:{legacy_id}"),
            json=REASON,
        )
    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/operator_has_no_address")


async def test_the_directory_lists_live_accounts_and_says_who_has_not_signed_in() -> None:
    """`activated` is what decides whether the console offers "resend" or "revoke", and
    revoked rows are absent because they are evidence rather than accounts."""
    actor = await _make_admin()
    pending = await _make_operator()
    revoked = await _make_operator()
    await operators.revoke_operator(
        actor=_principal(_id_of(actor)), operator_id=revoked, reason="fixture", ip=None
    )
    async with _client() as http:
        response = await http.get("/v1/admin/operators", headers=_headers(actor))
    assert response.status_code == 200, response.text
    listed = {UUID(row["id"]): row for row in response.json()["operators"]}
    assert pending in listed and listed[pending]["activated"] is False
    assert revoked not in listed
    assert _id_of(actor) in listed


async def test_an_activated_operator_reads_as_activated() -> None:
    """The other arm of the flag, which no other test drives: an account that HAS a
    password. Without it `activated` could be hard-coded False and every assertion above
    would still pass."""
    actor = await _make_admin()
    operator_id = await _make_operator()
    async with credential_session() as session:
        await set_password(
            session, realm=ADMIN_REALM, subject_id=operator_id, password="a-real-password-9"
        )
    async with _client() as http:
        response = await http.get("/v1/admin/operators", headers=_headers(actor))
    listed = {UUID(row["id"]): row for row in response.json()["operators"]}
    assert listed[operator_id]["activated"] is True


async def test_a_view_as_session_cannot_manage_operators_even_as_a_superadmin() -> None:
    """D-22 (constraint: impersonation is READ-ONLY) meets the two tiers.

    A super admin has everything — so the interesting question is what "everything" means
    INSIDE a view-as session, and the answer is that the tier does not widen it by one
    permission. `requires()` refuses any `MUTATING_PERMISSIONS` member while
    `principal.impersonating` is True, whatever the role grants, and `admin:operators` is
    in that set. So the most privileged session this product can issue still cannot hand
    somebody an administrator account from inside a client's dashboard, and the GET is
    invisible there too (`ADMIN_CONSOLE_GETS` carries the reason that is right).

    A REAL GRANT, minted through the console's own door. Without one the refusal would
    arrive before the rule this test exists to pin — the trap `view_as_headers`' docstring
    names — and the test would be green for the wrong reason.
    """
    token = await _make_admin()
    org = await admin_service.create_organization(
        name="View As Clinic",
        slug=f"vas-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        created = await http.post(
            "/v1/admin/operators",
            headers={**headers, "X-Confirm-Action": "add_operator:superadmin"},
            json={"email": _address(), "role": "superadmin", **REASON},
        )
        listed = await http.get("/v1/admin/operators", headers=headers)
    assert created.status_code == 403, created.text
    assert "Impersonation is read-only" in created.json()["detail"], created.text
    assert listed.status_code == 403, listed.text


# --------------------------------------------------------------------- 4. step-up


async def test_every_mutation_needs_its_own_confirmation() -> None:
    """Step-up is string equality, so the whole guarantee is that the four strings differ
    and that each route demands its own. Driven with a VALID confirmation for a DIFFERENT
    route, which is the request an operator actually generates mid-procedure."""
    actor = await _make_admin()
    operator_id = await _make_operator()
    async with _client() as http:
        cases = {
            "create": await http.post(
                "/v1/admin/operators",
                headers=_headers(actor, f"revoke_operator:{operator_id}"),
                json={"email": _address(), **REASON},
            ),
            "promote": await http.patch(
                f"/v1/admin/operators/{operator_id}",
                headers=_headers(actor, "add_operator:superadmin"),
                json={"role": "superadmin", **REASON},
            ),
            "revoke": await http.post(
                f"/v1/admin/operators/{operator_id}/revocation",
                headers=_headers(actor, f"set_operator_role:{operator_id}"),
                json=REASON,
            ),
            "resend": await http.post(
                f"/v1/admin/operators/{operator_id}/setup-link",
                headers=_headers(actor),
                json=REASON,
            ),
        }
    for name, response in cases.items():
        assert response.status_code == 403, f"{name}: {response.text}"
        assert response.json()["type"].endswith("/step_up_required"), f"{name}: {response.text}"
        assert "X-Confirm-Action: " in response.json()["remediation"], name

    async with untenanted_session() as session:
        role = (
            await session.execute(
                text("SELECT role, deactivated_at FROM admin_users WHERE id = :id"),
                {"id": operator_id},
            )
        ).first()
    assert role is not None and role[0] == NORMAL_ADMIN_ROLE and role[1] is None


async def test_adding_a_superadmin_needs_a_different_confirmation_from_adding_an_operator() -> None:
    """What binding the create confirmation to the ROLE buys: consent to add a colleague
    who onboards clients is not consent to add a second holder of every platform secret."""
    actor = await _make_admin()
    async with _client() as http:
        response = await http.post(
            "/v1/admin/operators",
            headers=_headers(actor, "add_operator:operator"),
            json={"email": _address(), "role": "superadmin", **REASON},
        )
    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/step_up_required")


async def test_a_revoked_operator_is_invisible_to_every_identity_read() -> None:
    """The `_ADMIN_SELECT` predicate, at the two doors that are NOT `core/auth.py`.

    `load_subject` is what every flow in `authn/service.py` goes through, and
    `resolve_by_email` is what a "forgot password" request resolves — so if either still
    saw a revoked operator, the reset flow would mail that person a link and
    `set_password` would rebuild the credential `revoke_operator` just destroyed. They
    would still be refused at `_load_admin_principal`, which is why this is a second lock
    rather than the only one; a revocation that leaves a live password-reset path is a
    revocation somebody has to explain.

    BOTH answers are the plain `None` every other failure produces — absent, deleted and
    revoked are indistinguishable to the caller, which is `subjects.py`'s whole subject.
    """
    actor = await _make_admin()
    address = _address()
    created = await operators.create_operator(
        actor=_principal(_id_of(actor)),
        email=address,
        name="Departing",
        role=NORMAL_ADMIN_ROLE,
        reason="fixture",
        ip=None,
    )
    assert await load_subject(ADMIN_REALM, created.id) is not None
    assert await resolve_by_email(ADMIN_REALM, address) is not None

    await operators.revoke_operator(
        actor=_principal(_id_of(actor)), operator_id=created.id, reason="left", ip=None
    )

    assert await load_subject(ADMIN_REALM, created.id) is None
    assert await resolve_by_email(ADMIN_REALM, address) is None


# ------------------------------------------------------- 5. the credential helpers


async def test_asking_about_no_subjects_asks_the_database_nothing() -> None:
    """`IN ()` is not valid SQL and a round trip that can only answer "none" is one worth
    not taking — the short-circuit is the reason the directory can render an empty list
    without a second transaction."""
    async with credential_session() as session:
        assert (
            await subjects_with_password(session, realm=ADMIN_REALM, subject_ids=[]) == frozenset()
        )


async def test_deleting_a_password_reports_whether_there_was_one() -> None:
    """The return value is what tells an operator's revocation whether it destroyed a
    credential or revoked an invitation that was never accepted — two different facts
    about what just happened."""
    operator_id = await _make_operator()
    async with credential_session() as session:
        assert await delete_password(session, realm=ADMIN_REALM, subject_id=operator_id) is False
        await set_password(
            session, realm=ADMIN_REALM, subject_id=operator_id, password="a-real-password-9"
        )
        assert await delete_password(session, realm=ADMIN_REALM, subject_id=operator_id) is True


async def test_the_credential_helpers_refuse_a_realm_that_does_not_exist() -> None:
    """The same guard every other function in that module has, so a typo cannot silently
    query a realm nothing writes."""
    async with credential_session() as session:
        with pytest.raises(ValueError, match="not an authentication realm"):
            await subjects_with_password(session, realm="operator", subject_ids=[uuid.uuid4()])
        with pytest.raises(ValueError, match="not an authentication realm"):
            await delete_password(session, realm="operator", subject_id=uuid.uuid4())


async def test_an_unknown_operator_is_a_404_rather_than_an_empty_success() -> None:
    """The read helper's absent arm, reached through the resend route because it is the
    one path with no compare-and-swap in front of it."""
    actor = await _make_admin()
    with pytest.raises(ProblemError) as raised:
        await operators.reissue_setup_link(
            actor=_principal(_id_of(actor)),
            operator_id=uuid.uuid4(),
            reason="fixture",
            ip=None,
            now=datetime.now(UTC),
        )
    assert raised.value.status == 404
