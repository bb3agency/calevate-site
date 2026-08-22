"""The operator allowlist as a MANAGED surface: who may use the admin console (D-171 §2).

`bootstrap.py` answers "how does the FIRST operator come to exist" — a deploy-time script,
no `--force`, refusing once anybody has a password. This module answers everything after
that: a superadmin adds colleagues, promotes and demotes them, and takes their access away.
Both halves mint the same kind of credential-setting link, redeemed on the same public
route, so there is one way for a Calevate operator account to acquire a password and it is
the one `POST /v1/auth/admin/bootstrap/confirm` already implements.

═══ WHY THIS LIVES IN `authn/` AND ITS ROUTES LIVE IN `admin/` ═══

Every act here is a CREDENTIAL act: creating an account mints a single-use setup token,
revoking one destroys the password and every live session, and changing a role invalidates
sessions under ASVS 5.0 V7. `credential_session()` is the only session that can see
`auth_credentials`, `auth_sessions` and `auth_email_tokens`, and `subjects.py` states the
rule this package is built on — `apps/api/authn` is the one package that opens it. So the
transaction lives here and the HTTP surface (`admin/operator_routes.py`) lives with the
rest of the console, exactly as `tenancy/routes.invite_member` calls
`authn.service.enqueue_invitation_email` rather than composing an email itself.

═══ THE SECURITY PROPERTY, AND HOW IT IS OBTAINED ═══

**A normal admin cannot promote themselves, and no operator — of either tier — can change
their own role or revoke their own account.** That is not one check; it is three facts that
together make the escalation unreachable, and each is independently testable:

  1. `admin:operators` is held by `superadmin` ONLY (`core/rbac.ROLE_PERMISSIONS`). A
     normal admin does not reach these routes at all, so there is no self-promotion path
     to defend — the surface that edits the role table is behind the role it would edit.
  2. `_refuse_self` refuses a role change or a revocation whose subject is the actor. Two
     different people are involved in every such act, which is what makes the audit row
     mean something: "X promoted Y" is evidence, "X promoted X" is a note X wrote about
     themselves.
  3. Authority is re-read from `admin_users` on EVERY request
     (`core/auth._load_admin_principal`), so a demotion or a revocation takes effect on
     the target's next request rather than when their cookie expires.

**THE "AT LEAST ONE LIVE SUPERADMIN" INVARIANT IS A CONSEQUENCE OF THOSE THREE, NOT A
FOURTH CHECK, AND THE ABSENCE OF THE FOURTH CHECK IS DELIBERATE.** Only a superadmin can
demote or revoke, and they cannot aim at themselves — so the actor is a live superadmin who
is not the subject, and the platform still has one when the statement commits. A separate
`SELECT count(*) ... WHERE role = 'superadmin'` guard would read as prudent and could never
fire: an arm no request can reach is a branch no test can drive, which is the shape
CLAUDE.md's coverage rule names. `tests/admin_operators_test.py` asserts the invariant by
driving the flow instead. What WOULD reintroduce the need for it is granting
`admin:operators` to a second role; that is why fact 1 is stated first.

A superadmin therefore cannot remove their own account, and that is the intended shape
rather than a gap — a departing operator is removed by a colleague, which is the same
two-person rule that makes every other row in this ledger evidence. The refusal says so.

═══ REVOCATION IS A COLUMN, NOT A `DELETE` ═══

Migration f2c74b81a9d3 carries the argument in full: eight tables reference `admin_users`
`ON DELETE RESTRICT` because they record which operator approved a campaign, verified a
KYC record or installed a credential, so the DELETE this realm's liveness rule assumed
raises 23503 for exactly the operators somebody would want removed. The row therefore
stays as evidence and `deactivated_at` is what ends the account — along with the password
and every session, which are deleted rather than left inert.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn import tokens
from apps.api.authn.bootstrap import ADMIN_REALM
from apps.api.authn.credentials import delete_password, subjects_with_password
from apps.api.authn.service import enqueue_admin_setup_email
from apps.api.authn.sessions import revoke_subject_sessions
from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import credential_session, untenanted_session

log = get_logger(__name__)

#: The two tiers, as a TYPE rather than a runtime check. Every caller reaches this module
#: through a Pydantic body that declares the same Literal, so an unknown role is a 422 at
#: the boundary and mypy refuses one at every internal call site. A `if role not in
#: ADMIN_ROLES: raise` here would be a second statement of the same fact whose arm no
#: request could reach.
#:
#: It cannot be BUILT from `core/rbac.ADMIN_ROLES` — a `Literal` needs literals — so
#: `tests/admin_operators_test.py` compares `get_args(AdminRole)` against that tuple
#: rather than against a third copy written out here.
AdminRole = Literal["superadmin", "operator"]


@dataclass(frozen=True, slots=True)
class OperatorAccount:
    """One live operator account, as the console may see it.

    NO CREDENTIAL MATERIAL AND NO TOKEN. `activated` is the only thing said about the
    password — whether one exists — because that is what decides whether the console
    offers "resend setup link" or "revoke", and a setup token handed back to the person
    who created the account is D-190's defect (the invitation squat) in a new costume: the
    link goes to the invited mailbox and nowhere else.
    """

    id: UUID
    email: str | None
    name: str | None
    role: str
    created_at: datetime
    #: False while the setup link is still outstanding — the account exists and cannot
    #: sign in yet.
    activated: bool


def _refuse_self(actor: Principal, operator_id: UUID, *, act: str) -> None:
    """No operator changes their own role or ends their own account. See the module head.

    ONE refusal for both acts, parameterised by the verb, because the reason is identical
    and two sentences would be two things to keep true.
    """
    if actor.user_id is not None and actor.user_id == operator_id:
        raise ProblemError(
            kind="permission",
            code="operator_self_administration",
            title="You cannot do this to your own account",
            detail=f"An operator may not {act} their own operator account.",
            remediation=(
                "Ask another superadmin to make this change. Every change to the operator "
                "allowlist names two different people on purpose."
            ),
        )


def _not_found() -> ProblemError:
    """One answer for absent, already-revoked and never-existed.

    The same uniformity `subjects.load_subject` has, for a weaker reason: this surface is
    superadmin-only, so it is not an enumeration oracle. What it buys is that a double
    click on Revoke answers "there is no such live operator account" rather than a second
    success that writes a second ledger row for one act.
    """
    return ProblemError.not_found("Operator account")


async def _account(session: AsyncSession, operator_id: UUID, *, live_only: bool) -> OperatorAccount:
    """The account behind an id, read inside the caller's transaction.

    `live_only` is a parameter rather than a fixed predicate because `revoke_operator`
    reads the row it has just deactivated — the record it returns is what the console
    renders as "this is what you removed". Every other caller wants the liveness check,
    and gets a 404 without it.

    `activated` is a SECOND STATEMENT against the credential store rather than a join to
    it: `subjects.py`'s rule is that the identity tables and the credential tables are
    never joined in one statement, and this is inside a `credential_session` where the
    join would have been trivial to write.
    """
    predicate = " AND deactivated_at IS NULL" if live_only else ""
    row = (
        await session.execute(
            # ASSEMBLED FROM TEXT TYPED IN THIS FILE — the two predicates are literals
            # above, not caller input, which is what `scripts/check_raw_sql.py` reads for.
            text(
                "SELECT id, email, name, role, created_at FROM admin_users "
                "WHERE id = :id" + predicate
            ),
            {"id": operator_id},
        )
    ).first()
    if row is None:
        raise _not_found()
    activated = await subjects_with_password(session, realm=ADMIN_REALM, subject_ids=[operator_id])
    return OperatorAccount(
        id=UUID(str(row[0])),
        email=row[1],
        name=row[2],
        role=str(row[3]),
        created_at=row[4],
        activated=operator_id in activated,
    )


async def list_operators() -> list[OperatorAccount]:
    """Every LIVE operator account, newest last.

    REVOKED ROWS ARE NOT ACCOUNTS AND ARE NOT LISTED. They survive only because eight
    foreign keys point at them (migration f2c74b81a9d3); "who was removed, by whom and
    when" is a question for the hash-chained ledger, which answers it tamper-evidently,
    rather than for a directory that would then grow without bound.

    TWO SEQUENTIAL SESSIONS, NOT ONE JOIN, and `subjects.py` states the rule: the identity
    tables and the credential tables are never joined in one statement, so the credential
    GUC's blast radius stays exactly as wide as the credential store. Sequential rather
    than nested — `db/session.py` runs `max_overflow=0` and one task holds one session at
    a time (D-182).
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, email, name, role, created_at FROM admin_users "
                    "WHERE deactivated_at IS NULL ORDER BY created_at, id"
                )
            )
        ).all()
    ids = [UUID(str(row[0])) for row in rows]
    async with credential_session() as session:
        activated = await subjects_with_password(session, realm=ADMIN_REALM, subject_ids=ids)
    return [
        OperatorAccount(
            id=UUID(str(row[0])),
            email=row[1],
            name=row[2],
            role=str(row[3]),
            created_at=row[4],
            activated=UUID(str(row[0])) in activated,
        )
        for row in rows
    ]


async def create_operator(
    *,
    actor: Principal,
    email: str,
    name: str | None,
    role: AdminRole,
    reason: str,
    ip: str | None,
    now: datetime | None = None,
) -> OperatorAccount:
    """Add an operator account and mail its single-use setup link.

    ONE TRANSACTION for the row, the token, the queued email and the ledger entry. The
    audit row commits with the change (hard rule 5 / BACKEND-PATTERNS §7), and the email
    is an outbox message written in the same transaction (§4), so there is no ordering in
    which an account exists without its invitation or an invitation names an account that
    was rolled back.

    THE DUPLICATE-ADDRESS ANSWER IS THE INSERT ITSELF, not a check before it. A
    `SELECT ... WHERE lower(email) = ?` followed by an INSERT is the check-then-act
    BACKEND-PATTERNS §5 names as the defect: two superadmins adding the same colleague at
    once would both see nothing and both insert. The partial unique index
    (`uq_admin_users_email_lower ... WHERE deactivated_at IS NULL`) decides it, and the
    loser gets a 409 rather than a 500.
    """
    at = now or datetime.now(UTC)
    address = email.strip()
    operator_id = uuid7()
    async with credential_session() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO admin_users (id, email, name, role, created_at, updated_at) "
                    "VALUES (:id, :email, :name, :role, :now, :now)"
                ),
                {"id": operator_id, "email": address, "name": name, "role": role, "now": at},
            )
        except IntegrityError as exc:
            raise ProblemError.conflict(
                "operator_email_taken",
                "A live operator account already uses that email address.",
                remediation=(
                    "Use the existing account — resend its setup link if the person never "
                    "finished signing in — or revoke it first."
                ),
            ) from exc
        issued = await tokens.issue_token(
            session,
            purpose="admin_bootstrap",
            realm=ADMIN_REALM,
            subject_id=operator_id,
            now=at,
        )
        await enqueue_admin_setup_email(session, to=address, token=issued.token)
        await write_audit(
            session,
            action="admin.operator_created",
            actor=actor,
            object_type="admin_user",
            object_id=str(operator_id),
            ip=ip,
            # The address is in the summary and NOT in the ledger row: `audit_log` has no
            # summary column, so this reaches only the JSONL log stream, through
            # `redact_mapping`, which masks any key containing `email` (hard rule 6). What
            # the permanent row carries is the actor, the object id, the time and the IP.
            summary={"email": address, "role": role, "reason": reason},
        )
    log.warning(
        "admin_operator_created",
        extra={"operator_id": str(operator_id), "role": role, "actor_id": str(actor.user_id)},
    )
    return OperatorAccount(
        id=operator_id, email=address, name=name, role=role, created_at=at, activated=False
    )


async def set_operator_role(
    *,
    actor: Principal,
    operator_id: UUID,
    role: AdminRole,
    reason: str,
    ip: str | None,
    now: datetime | None = None,
) -> OperatorAccount:
    """Promote or demote another operator, and end their live sessions.

    A COMPARE-AND-SWAP ON THE OLD ROLE, so a no-op is visible rather than silently
    ledgered: `WHERE role <> :role` means an unchanged role writes no audit row, exactly as
    `platform.config_set` refuses to record a write that changed nothing. Rowcount 0 is
    therefore two states — no such live operator, or the role already reads that way — and
    they are separated by the read that follows, in the same transaction.

    SESSIONS ARE REVOKED, AND CORRECTNESS DOES NOT DEPEND ON IT. `_load_admin_principal`
    re-reads the role from `admin_users` on every request, so the new permission set is in
    force on the target's next call whatever happens to their session rows. The revocation
    is ASVS 5.0 V7's requirement that an entitlement change not leave live sessions behind,
    and it is in the same transaction so the two cannot disagree.
    """
    _refuse_self(actor, operator_id, act="change the role of")
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        changed = rowcount_of(
            await session.execute(
                text(
                    "UPDATE admin_users SET role = :role, updated_at = :now "
                    "WHERE id = :id AND deactivated_at IS NULL AND role <> :role"
                ),
                {"id": operator_id, "role": role, "now": at},
            )
        )
        account = await _account(session, operator_id, live_only=True)
        if not changed:
            # The role already reads this way. No ledger entry and no session revocation:
            # a double-clicked Save must not appear in a tamper-evident log as two
            # promotions, and must not sign somebody out for a request that changed
            # nothing. The account is still returned, so the console re-renders from the
            # server's view rather than from what it hoped it had sent.
            return account
        await revoke_subject_sessions(session, realm=ADMIN_REALM, subject_id=operator_id, now=at)
        await write_audit(
            session,
            action="admin.operator_role_changed",
            actor=actor,
            object_type="admin_user",
            object_id=str(operator_id),
            ip=ip,
            summary={"role": role, "reason": reason},
        )
    log.warning(
        "admin_operator_role_changed",
        extra={"operator_id": str(operator_id), "role": role, "actor_id": str(actor.user_id)},
    )
    return account


async def revoke_operator(
    *,
    actor: Principal,
    operator_id: UUID,
    reason: str,
    ip: str | None,
    now: datetime | None = None,
) -> OperatorAccount:
    """End another operator's access: the account, the password, every session, every link.

    FOUR THINGS DIE AND THE ROW DOES NOT. `deactivated_at` is what every liveness read
    checks, so it alone ends the account; the password, the sessions and any outstanding
    setup link are destroyed as well because leaving authentication material behind for an
    account that must never sign in again is the state a reactivation — or a restored
    backup — would quietly resurrect.

    THE CAS IS THE IDEMPOTENCE. `WHERE deactivated_at IS NULL` means a second revocation
    of the same account answers 404 rather than writing a second ledger row for one act.
    """
    _refuse_self(actor, operator_id, act="revoke")
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        revoked = rowcount_of(
            await session.execute(
                text(
                    "UPDATE admin_users SET deactivated_at = :now, updated_at = :now "
                    "WHERE id = :id AND deactivated_at IS NULL"
                ),
                {"id": operator_id, "now": at},
            )
        )
        if not revoked:
            raise _not_found()
        # `live_only=False`: the row this reads is the one the statement above just
        # deactivated. `activated` is forced False below rather than read, because the
        # password is deleted three lines further down and the field means "can sign in",
        # not "had a password a moment ago".
        account = replace(await _account(session, operator_id, live_only=False), activated=False)
        await delete_password(session, realm=ADMIN_REALM, subject_id=operator_id)
        await revoke_subject_sessions(
            session, realm=ADMIN_REALM, subject_id=operator_id, reason="administrative", now=at
        )
        await tokens.invalidate_outstanding(
            session,
            purpose="admin_bootstrap",
            realm=ADMIN_REALM,
            subject_id=operator_id,
            now=at,
        )
        await write_audit(
            session,
            action="admin.operator_revoked",
            actor=actor,
            object_type="admin_user",
            object_id=str(operator_id),
            ip=ip,
            summary={"reason": reason},
        )
    log.warning(
        "admin_operator_revoked",
        extra={"operator_id": str(operator_id), "actor_id": str(actor.user_id)},
    )
    return account


async def reissue_setup_link(
    *,
    actor: Principal,
    operator_id: UUID,
    reason: str,
    ip: str | None,
    now: datetime | None = None,
) -> OperatorAccount:
    """Mail a fresh setup link to an operator account that never finished signing in.

    NEEDED, NOT A CONVENIENCE: the link lives one hour (`tokens.TOKEN_LIFETIMES`), mail
    bounces, and without this an account created for a mistyped-but-deliverable address —
    or one whose invitation expired over lunch — could never be signed into and could not
    be recreated either, because the partial unique index holds its address.

    IT IS NOT A PASSWORD RESET AND CANNOT BECOME ONE. An account that already has a
    password is refused here, and `bootstrap.confirm_bootstrap` refuses the token as well,
    so neither half can be used to take over an established operator. A superadmin who
    needs to help a colleague who forgot their password sends them to the ordinary reset
    flow, which mails the LINK to that colleague rather than to the person asking.

    Only the newest link works — `invalidate_outstanding` before `issue_token`, the same
    order and the same reason as a password reset.
    """
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        account = await _account(session, operator_id, live_only=True)
        if await subjects_with_password(session, realm=ADMIN_REALM, subject_ids=[operator_id]):
            raise ProblemError.conflict(
                "operator_already_activated",
                "That operator has already set a password, so there is no setup link to send.",
                remediation=(
                    "If they cannot sign in, ask them to use the sign-in page's password "
                    "reset — the link has to be mailed to them, not to you."
                ),
            )
        if account.email is None:
            # A Clerk-era row (`email` is nullable for exactly those) has no mailbox to
            # send to. Refusing names the fix; issuing a token nobody receives would
            # report success for a message that cannot be composed.
            raise ProblemError.conflict(
                "operator_has_no_address",
                "That operator account predates first-party sign-in and has no email address.",
                remediation="Revoke it and add the person again with their address.",
            )
        await tokens.invalidate_outstanding(
            session,
            purpose="admin_bootstrap",
            realm=ADMIN_REALM,
            subject_id=operator_id,
            now=at,
        )
        issued = await tokens.issue_token(
            session,
            purpose="admin_bootstrap",
            realm=ADMIN_REALM,
            subject_id=operator_id,
            now=at,
        )
        await enqueue_admin_setup_email(session, to=account.email, token=issued.token)
        await write_audit(
            session,
            action="admin.operator_setup_link_issued",
            actor=actor,
            object_type="admin_user",
            object_id=str(operator_id),
            ip=ip,
            summary={"reason": reason},
        )
    log.warning(
        "admin_operator_setup_link_issued",
        extra={"operator_id": str(operator_id), "actor_id": str(actor.user_id)},
    )
    return account


__all__ = [
    "AdminRole",
    "OperatorAccount",
    "create_operator",
    "list_operators",
    "reissue_setup_link",
    "revoke_operator",
    "set_operator_role",
]
