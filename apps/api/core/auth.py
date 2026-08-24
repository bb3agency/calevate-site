"""First-party authentication for TWO SEPARATE REALMS + the tenant-scoped session dep.

D-177 removed Clerk. What this module does is unchanged in shape and changed entirely in
substance: it turns a presented credential into a `Principal`, and the credential is now
one of ours — the opaque session `apps/api/authn/sessions.py` mints, carried in the
realm's `__Host-` cookie. There is no JWKS fetch, no vendor host, no signature to check
and no third party whose outage signs everybody out.

D-37's load-bearing half STANDS and is what made the swap cheap: **our Postgres is the
system of record.** `users`, `memberships`, `organizations`, `admin_users` and every RLS
policy key off OUR ids, and they always did. Only the authentication leg moved.

**WHAT A VERIFIED CREDENTIAL NOW CARRIES, and why that is the whole simplification.**
`authn.sessions.verify_session` answers with a row, and the row's `subject_id` IS
`users.id` (client realm) or `admin_users.id` (admin realm). The old flow had to translate
a vendor subject into one of our ids on every request — a mirror lookup, a just-in-time
reconcile against Clerk's Backend API, and the transient
`identity_mirror_pending` refusal when the Svix webhook had not landed yet (D-124). All of
that is deleted rather than replaced: there is no upstream to be behind, so there is no
race to lose.

Realms never share session logic (TRD §11). The separation is now ours to hold up and is
four independent mechanisms, argued in AUTH-MIGRATION §3: the realm is inside the session
token's hash domain, it is in the `WHERE` clause beside it, it selects the cookie name,
and the auth routes enforce a per-realm origin. A client session presented on the admin
door does not match a row — that is arithmetic, not a predicate somebody has to remember.

**MFA is mandatory on the admin realm** (TRD §2, SEC-COMP §5) and is enforced here, in
`verify_token`, from `auth_sessions.mfa_verified_at`. A password alone issues a
session with that column NULL which can reach exactly one route — `POST
/v1/auth/admin/login/otp` — and answering the emailed code rotates the session with the
column set (D-170). `MFA_REQUIRED_REALMS` is the single copy of that fact, asserted equal
to `authn/service.py`'s by `tests/authn_mfa_test.py`, so the sign-in path and the verifier
cannot disagree.

Local development: `Bearer dev:<realm>:<subject-uuid>` (with an optional `:nomfa` segment
standing in for a session that never completed a second factor). It is the ONLY thing this
API still accepts on the `Authorization` header — a real session is a cookie and nothing
else — and it is guarded by two independent facts, exactly as it was:

  1. `APP_ENV=local`. `Settings.app_env` has NO DEFAULT and is in `BOOTSTRAP_REQUIRED`, so
     no configuration is `local` without somebody having typed `local`.
  2. `PLATFORM_KEK` is unset. That is the successor to the old "this realm has no Clerk
     secret configured" guard, and it is the same statement of fact: a deployment holding
     real key material is a real deployment. A prod host cannot omit `PLATFORM_KEK` — it is
     what every password is peppered with (`authn/hashing.py`), `/healthz/ready` reports it
     missing, and a local box falls back to a constant printed in this repository. So one
     mis-set variable can no longer switch the dev path on, which was the entire point of
     there being two guards (`tests/authz_audit_test.py` pins both).

The subject is a UUID of OUR issuing rather than a caller-chosen string, which is the other
half of the re-pointing AUTH-MIGRATION §1 C-21 asked for: `dev:admin:<anything>` no longer
even parses.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast
from uuid import UUID

from calevate_shared.client_address import client_ip
from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn.cookies import read_token
from apps.api.authn.sessions import verify_session
from apps.api.authn.subjects import load_subject
from apps.api.compliance.audit import write_audit
from apps.api.core.context import (
    IMPERSONATE_HEADER,
    IMPERSONATION_GRANT_HEADER,
    ORG_HEADER,
    Principal,
    Realm,
    bearer_token,
    principal_var,
)
from apps.api.core.errors import ProblemError
from apps.api.core.impersonation import ImpersonationGrant, verify_grant
from apps.api.core.logging import get_logger
from apps.api.core.ratelimit import consume, profile_for, too_many_requests
from apps.api.core.rbac import MUTATING_PERMISSIONS, Permission, role_has
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, user_session

log = get_logger(__name__)

#: The realms where a second factor is MANDATORY. The client realm is deliberately not
#: here: SEC-COMP §5 requires MFA on admin only, and client owners on Indian SMB
#: hardware are not who this control protects against.
#:
#: THE SINGLE COPY OF THAT FACT. `authn/service.py` decides whether a sign-in needs a
#: challenge and reads this same name; `tests/authn_mfa_test.py` asserts the two are equal,
#: because two copies is exactly how a sign-in path and a verifier come to disagree,
#: silently, in the unsafe direction.
MFA_REQUIRED_REALMS: frozenset[str] = frozenset({"admin"})

#: `dev:<realm>:<subject-uuid>:nomfa` — the local-only way to obtain a credential that has
#: NOT completed a second factor, so the refusal can be exercised in both directions.
#: A plain three-segment dev token counts as MFA-complete, because it already bypasses
#: authentication entirely (see the module docstring's two guards) and making it
#: MFA-incomplete by default would only mean every local screen and every admin test
#: asserts the refusal path and nothing asserts the allowed one.
DEV_TOKEN_NO_MFA_SUFFIX = "nomfa"


def _require_second_factor(realm: Realm, mfa_verified_at: datetime | None) -> None:
    """Refuse a credential of an MFA-mandatory realm that never proved a second factor.

    ONE code for one condition. `authn/routes.py` raises the identical
    `second_factor_required` on the sign-in surface, and it has to be identical: the
    pre-code session is a real, live session that may reach exactly one route, so a console
    meets this refusal on the auth router and on every other router, and two names for it
    would be two things for a client to handle and one of them to get wrong.

    The Clerk-era pair is gone with the vendor. `mfa_claim_missing` existed because a
    custom JWT template could silently drop the `fva` claim and "unknown" had to fail
    closed; a NULL column cannot be ambiguous, so there is nothing left for that code to
    describe.
    """
    if realm not in MFA_REQUIRED_REALMS or mfa_verified_at is not None:
        return
    log.warning("admin_mfa_missing")
    raise ProblemError(
        kind="auth",
        code="second_factor_required",
        title="Two-step verification required",
        detail=(
            "The operator console requires two-step verification, and this sign-in has "
            "not completed a second factor."
        ),
        remediation="Enter the code emailed to your operator address to finish signing in.",
    )


@dataclass(frozen=True, slots=True)
class VerifiedCaller:
    """A proved credential, before any authorization has been read.

    `subject_id` is OURS — `users.id` on the client realm, `admin_users.id` on the admin
    realm — which is the whole shape change D-177 buys. The Clerk-era `VerifiedToken`
    carried a vendor subject string that every request then had to translate, and the
    translation was a query, sometimes a call to Clerk's Backend API, and a transient
    refusal when neither had the row yet (D-124).

    `mfa_verified_at` is carried rather than recomputed, for the reason
    `authn.sessions.VerifiedSession` gives: it is a property of the CREDENTIAL and nothing
    downstream may re-decide it.
    """

    realm: Realm
    subject_id: UUID
    mfa_verified_at: datetime | None


def dev_tokens_permitted() -> bool:
    """The two independent guards, in one place so neither can be checked without the other.

    See the module docstring for why `PLATFORM_KEK` is the successor to "this realm has no
    Clerk secret configured": both are the statement *this deployment holds no real
    credential material*, and both are false on any host that could serve a customer.
    """
    settings = get_settings()
    return settings.app_env == "local" and not settings.platform_kek


def _verify_dev_token(token: str, realm: Realm) -> VerifiedCaller | None:
    """`dev:<realm>:<subject-uuid>[:nomfa]` — local only, and only on a keyless deployment.

    None means "not a dev credential this deployment will honour", and the caller turns
    that into a 401 rather than into a fall-through: after D-177 there is nothing else an
    `Authorization` header could be.

    The optional fourth segment is the local stand-in for a session that has proved a
    password and not the emailed code. It exists so the admin-realm MFA refusal is
    exercised on the SAME code path that serves the allowed case, rather than only in a
    unit test of the predicate.
    """
    if not dev_tokens_permitted():
        return None
    parts = token.split(":")
    if len(parts) not in (3, 4) or parts[0] != "dev" or parts[1] != realm:
        return None
    if len(parts) == 4 and parts[3] != DEV_TOKEN_NO_MFA_SUFFIX:
        # An unrecognised suffix is not a token with a typo we should be lenient about:
        # `dev:admin:<uuid>:mfa` would otherwise be read as "no suffix I know, so allow",
        # which is the wrong direction for the one realm this gate protects.
        return None
    try:
        subject_id = UUID(parts[2])
    except ValueError:
        # The subject is a uuid7 WE issued, not a string the caller picked — the other half
        # of the re-pointing AUTH-MIGRATION C-21 asked for. `dev:admin:<anything>` no
        # longer parses, so the dev path cannot name a subject that was never minted.
        return None
    log.warning("dev_token_accepted", extra={"realm": realm})
    return VerifiedCaller(
        realm=realm,
        subject_id=subject_id,
        mfa_verified_at=None if len(parts) == 4 else datetime.now(UTC),
    )


async def verify_token(token: str, realm: Realm) -> VerifiedCaller:
    """A proved credential for THIS realm — and on the admin realm, only ever one that
    completed a second factor.

    WHY THE MFA GATE IS HERE AND NOT IN `current_admin` OR IN A ROUTE DEPENDENCY.
    This function is the only way to turn a string into an admin-realm identity. Putting
    the check here makes "an admin credential" and "an admin credential that passed MFA"
    the SAME object: there is no `VerifiedCaller(realm="admin")` in existence that skipped
    it, so a dependency written next year is covered by calling the verifier at all, and
    cannot opt out without opting out of authentication. Rejected:
      - `current_admin`: correct today (it is the sole admin caller) and one direct
        `verify_token(..., "admin")` away from being wrong — the same shape of defect as
        a permission named after an act that did not gate the act.
      - A ROUTE DEPENDENCY / `requires(..., realm="admin")`: ~60 declarations, and the
        one that forgets it is the one that matters.
      - MIDDLEWARE: runs before the realm is known — it would have to re-parse the
        credential and re-decide which realm this request is, which is a second definition
        of the thing this module exists to define once.

    `verify_session` OWNS ITS TRANSACTION and that matters here: presenting a superseded
    token revokes the whole family, and that write has to survive the refusal it causes.
    So this function takes no session and opens none — see that function's docstring.
    """
    dev = _verify_dev_token(token, realm)
    if dev is not None:
        _require_second_factor(realm, dev.mfa_verified_at)
        return dev
    if token.startswith("dev:"):
        # A dev token for the WRONG realm, malformed, or presented where dev tokens are
        # disabled. Answering 401 is both correct and honest — falling through to
        # `verify_session` would spend a fingerprint lookup on a string that can never be
        # one of our tokens, and would answer with the same sentence anyway.
        raise ProblemError.unauthorized("This token is not valid for this realm.")
    verified = (await verify_session(token=token, realm=realm)).require_live()
    caller = VerifiedCaller(
        realm=realm,
        subject_id=verified.subject_id,
        mfa_verified_at=verified.mfa_verified_at,
    )
    # AFTER the session is proved live: an unknown or expired credential must answer "sign
    # in again", never "finish two-step verification" — the second sentence would tell an
    # anonymous caller that a valid-looking credential got further than it did.
    _require_second_factor(realm, caller.mfa_verified_at)
    return caller


def _credential(request: Request, realm: Realm) -> str:
    """The credential this request presents for THIS realm, or a 401.

    TWO SOURCES, AND THEY ARE NOT TWO WAYS OF DOING ONE THING. The cookie is the
    credential: `HttpOnly`, `__Host-`-prefixed, `SameSite=Strict`, unreadable by any
    script on the page (`authn/cookies.py` argues the whole trade). The `Authorization`
    header survives for exactly one shape — the local `dev:` token — and for nothing else:
    a real session token presented as a bearer is refused here, before it can be looked up,
    so there is no arrangement in which the browser can be talked into carrying our
    credential somewhere the cookie attributes would not have gone.

    That refusal is silent rather than explanatory. "Bearer tokens are not accepted" is a
    sentence for an integrator we do not have; every caller that reaches this line with a
    header instead of a cookie is either a stale client or somebody probing.
    """
    cookie = read_token(request, realm)
    if cookie:
        return cookie
    header = bearer_token(request.headers.get("authorization"))
    if header is not None and header.startswith("dev:"):
        return header
    raise ProblemError.unauthorized()


async def _live_subject(verified: VerifiedCaller) -> UUID:
    """The client-realm subject's id, re-proving on THIS request that they may sign in.

    `load_subject` returns `None` for absent, hard-deleted and deactivated alike and has no
    way to say which (`authn/subjects.py` explains why that uniformity is a property of the
    return type rather than of whoever remembered). The refusal it produces is therefore
    the one every failed credential produces.
    """
    if await load_subject(verified.realm, verified.subject_id) is None:
        log.info("auth_subject_not_live", extra={"realm": verified.realm})
        raise ProblemError.unauthorized("Your session is not valid. Sign in again.")
    return verified.subject_id


# --- Principal resolution -----------------------------------------------------


async def _load_client_principal(verified: VerifiedCaller, org_slug: str | None) -> Principal:
    """users + memberships are OURS (D-37) — the session says who, we say what they see.

    LIVENESS IS RE-READ ON EVERY REQUEST (BACKEND-PATTERNS §7), and that is what
    `live_subject` is for: `deactivated_at` set between two requests must take effect on
    the second one. Revoking the SESSION is now also possible and is strictly better, but
    it is a different act performed by a different operator, so both survive.

    The Clerk-era translation step is gone. `verified.subject_id` IS `users.id`, so there
    is no mirror to be behind, no Backend API to call, and no `identity_mirror_pending`
    refusal for a member who accepted an invite in one tab and opened the console in
    another (D-124's whole subject).
    """
    user_id = await _live_subject(verified)

    # Set inside the session below when the resolution came back empty BECAUSE the
    # account is closed; stays None on every other path. Declared here rather than
    # relied on to exist, so the refusal below reads as one decision instead of two
    # branches that happen to be in step.
    closed: object | None = None

    # Now, and only now, a session that can see THIS user's memberships.
    async with user_session(user_id) as session:
        params: dict[str, object] = {"uid": user_id}
        sql = (
            "SELECT m.tenant_id, m.role, o.slug FROM memberships m "
            "JOIN organizations o ON o.id = m.tenant_id "
            "WHERE m.user_id = :uid AND o.deleted_at IS NULL AND o.status <> 'churned'"
        )
        if org_slug:
            sql += " AND o.slug = :slug"
            params["slug"] = org_slug
        sql += " ORDER BY m.created_at LIMIT 2"
        memberships = (await session.execute(text(sql), params)).all()

        if not memberships:
            # ZERO ROWS IS TWO DIFFERENT FACTS, and only one of them is "you are not a
            # member" (D-189). The predicate above hides a CLOSED account as well as a
            # foreign one, so the owner of a business we offboarded — who is still on
            # `memberships`, still holds the credential, and whose leads export FLOWS §9
            # puts in the offboarding flow — was told, on their own account, that they
            # were not a member of it. That sentence is false, it names nothing they can
            # act on, and `admin.service.assert_account_open` already cites this exact
            # symptom as the reason an invitation into a closed account is refused; the
            # people who were ALREADY inside hit the same wall and nobody had named it.
            #
            # The second read stays inside `user_session`, so it can only ever see this
            # caller's own memberships and discloses nothing about anyone else's account
            # — it is the same row they could see yesterday, not a probe.
            #
            # `account_closed` is `compliance.service.account_stopped_blocker`'s and
            # `assert_account_open`'s own name for this state, deliberately: one
            # condition explained three ways is how an operator ends up believing they
            # are three problems.
            closed_sql = (
                "SELECT 1 FROM memberships m JOIN organizations o ON o.id = m.tenant_id "
                "WHERE m.user_id = :uid AND (o.deleted_at IS NOT NULL OR o.status = 'churned')"
            )
            if org_slug:
                closed_sql += " AND o.slug = :slug"
            closed_sql += " LIMIT 1"
            closed = (await session.execute(text(closed_sql), params)).first()

    if not memberships:
        if closed is not None:
            raise ProblemError(
                kind="permission",
                code="account_closed",
                title="Account closed",
                detail="This account has been closed and can no longer be signed in to.",
                remediation=(
                    "Contact Calevate support if you still need an export of its calls and leads."
                ),
            )
        raise ProblemError.forbidden("You are not a member of this account.")
    if len(memberships) > 1 and not org_slug:
        raise ProblemError(
            kind="validation",
            code="org_required",
            title="Account not specified",
            detail="You belong to more than one account; name one.",
            remediation=f"Send the {ORG_HEADER} header.",
        )
    tenant_id, role, _slug = memberships[0]
    return Principal(
        realm="client",
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
    )


# --- D-22 / SEC-COMP §5: BOTH halves of the trail, and what each one means -----
#
# The spec is "session start + every page view audit-logged (actor=admin_user, tenant,
# at, ip)", and for a long time neither half was what it looked like. The start row was
# written by an endpoint that MINTED NOTHING and that the console never called, so it
# was absent for every real session; the page-view row did not exist at all, so an admin
# who sent `X-Impersonate-Org` read a client's leads, calls and transcripts and left no
# trace, while four docstrings asserted otherwise.
#
# BOTH ROWS NOW EXIST AND THEY ANSWER DIFFERENT QUESTIONS. Keep them distinct:
#
#   `admin.impersonation_started` — ONE PER GRANT, written by the mint route
#     (`admin/routes.py`). It means AUTHORITY WAS ISSUED: operator X was granted the
#     ability to view tenant Y at time T from address I, expiring at E. It is no longer
#     skippable, because `_load_admin_principal` below refuses every impersonated
#     request that does not carry a grant, and a grant cannot exist without this row.
#     It is written even if the operator then reads nothing — "asked to go in" is its
#     own fact.
#
#   `admin.impersonation_read` — AT MOST ONE PER (ADMIN, TENANT) PER WINDOW, written
#     here. It means DATA WAS ACTUALLY REACHED, and at what times. It carries the
#     `grant_id` of the session it belongs to, so a start row and its reads join
#     exactly rather than by guessing from a timestamp.
#
# Neither implies the other and that is the point: a start row with no reads is an
# operator who opened a session and looked at nothing, and reads with no start row are
# now impossible. Together they bound a session at both ends.
#
# WHERE THIS LIVES, AND WHY NOT THE THREE OBVIOUS PLACES.
# `_load_admin_principal` is the ONLY function that can produce a principal with
# `impersonating=True`; `current_admin`, `current_any`, `requires(...)` and
# `core/deps.admin_db` all funnel through it, and a route has no other way to obtain a
# tenant-scoped admin session. So a route written tomorrow is covered by having been
# written at all — its author does nothing, and cannot opt out without opting out of
# authentication. Rejected:
#   - MIDDLEWARE: runs before the auth dependency, so it has no principal and no tenant
#     to name; reading `principal_var` on the way out means auditing AFTER the response
#     is composed, from outside the request's transaction, with no way to refuse.
#   - A ROUTE DEPENDENCY: correct once, forgotten on route 200. That is the exact
#     failure this defect is (a permission named after an act that did not gate the act).
#   - THE TENANCY CONTEXT (`db/session.tenant_session`): reached by client requests too,
#     which are not impersonation and must not pay for a write; it also has no principal.
#
# WHAT A "PAGE VIEW" IS FOR AN API, AND THE VOLUME ARGUMENT.
# A browser page is many requests: this console's dashboard opens ~6 TanStack Query
# subscriptions and refetches them on an interval, so "one audit row per request" is
# ~1400 rows/hour per operator sitting on one screen doing nothing. On an INSERT-ONLY
# table that is not a table that gets vacuumed — it is permanent, and each row also
# costs a Redis lock round trip plus a `SELECT ... ORDER BY at DESC LIMIT 1` because
# every entry links into the tamper-evident hash chain (BACKEND-PATTERNS §7). Worse
# than the cost: it buries the rows that matter. An investigator asking "who was inside
# this client's data on the 14th" wants a readable trail, and 1400 identical rows an
# hour is how a control becomes something nobody reads.
#
# So: A READ IS RECORDED AT MOST ONCE PER (ADMIN, TENANT) PER `IMPERSONATION_AUDIT_
# WINDOW_S`, AND THE FIRST READ AFTER EACH WINDOW ALWAYS RECORDS. That is the rule, it
# is testable (tests/impersonation_audit_test.py exercises both halves), and at 60
# seconds it bounds the ledger to <=60 rows/hour per operator-tenant while keeping
# minute-resolution presence — enough to answer "when did they enter, how long were
# they in there, from what IP", which is the DPDP question. WHICH SCREEN they were on
# is deliberately NOT the ledger's job: that lives in the request log, which already
# carries route + correlation id for every request and costs nothing to keep.
#
# THE BYPASS IS NOW CLOSED, and this is where it closes. The header alone no longer
# reaches a tenant: `_load_admin_principal` requires a grant that names this operator
# and this tenant (`core/impersonation.py`), so "entered without announcing" is not a
# state the system has. The read row below is still the one that cannot be skipped —
# it records presence whether or not anything was successfully read — but it is no
# longer the ONLY thing standing between an operator and a client's data.
IMPERSONATION_READ_ACTION = "admin.impersonation_read"
IMPERSONATION_AUDIT_WINDOW_S = 60


async def _record_impersonated_read(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID,
    ip: str | None,
    route: str,
    grant_id: UUID,
) -> None:
    """Append the page-view row, coalesced per the window above.

    The dedupe marker is a Redis SETNX with a TTL — the same primitive the webhook
    receiver dedupes execution ids with, rather than a second mechanism. It is a CACHE
    of "already recorded", never a source of truth, so IT FAILS TOWARDS RECORDING: if
    Redis cannot answer, we write the row. An audit control degrades into noise, never
    into silence, and the cost of that direction is bounded (a Redis outage is minutes,
    and the rows are still correct).

    The write goes into the CALLER'S transaction — the same `admin_session` that just
    read the tenant directory to authorise this view — so the row and the authorisation
    commit together. If it cannot be written the request fails: a read we cannot record
    is a read D-22 does not permit.
    """
    marker = f"calevate:imp:seen:{principal.user_id}:{tenant_id}"
    try:
        first_in_window = bool(
            await get_redis().set(marker, "1", nx=True, ex=IMPERSONATION_AUDIT_WINDOW_S)
        )
    except Exception:
        log.warning("impersonation_audit_dedupe_unavailable")
        first_in_window = True
    if not first_in_window:
        return
    await write_audit(
        session,
        action=IMPERSONATION_READ_ACTION,
        actor=principal,
        tenant_id=tenant_id,
        object_type="organization",
        object_id=str(tenant_id),
        ip=ip,
        # The ROUTE TEMPLATE, never the resolved path and never the query string: a
        # filter can carry a phone number (hard rule 6), and a template cannot carry an
        # identifier at all. It rides in `summary`, which goes to the log stream keyed
        # by the entry id — the ledger row itself carries exactly what SEC-COMP §5 asks
        # for (actor, tenant, at, ip).
        #
        # `grant_id` joins this read to the ONE `admin.impersonation_started` row that
        # authorised it. Without it an investigator matches a start row to its reads by
        # timestamp proximity, which stops working the moment two operators are in one
        # tenant — the case `test_two_operators_in_one_tenant_are_two_trails` already
        # cares about. It is a uuid, so it is not PII and the coalescing rule above is
        # untouched by its presence.
        summary={
            "route": route,
            "window_s": IMPERSONATION_AUDIT_WINDOW_S,
            "grant_id": str(grant_id),
        },
    )


async def _load_admin_principal(
    verified: VerifiedCaller,
    impersonate_slug: str | None,
    *,
    impersonation_grant: str | None = None,
    ip: str | None = None,
    route: str = "",
) -> Principal:
    # `admin_session`, not `untenanted_session`: resolving an impersonation slug is a
    # read of the tenant DIRECTORY, and `organizations` is RLS'd on `app.tenant_id` or
    # a membership — an operator has neither. Under the untenanted session the lookup
    # saw zero rows and every "view as client" request 404'd on a tenant that exists.
    # `app.admin` widens USING on `organizations` alone (migration b57e2f9c4a13) and
    # widens no WITH CHECK anywhere, which is exactly the authority this needs: the
    # admin identity is verified from `admin_users` in the same session, first.
    async with admin_session() as session:
        row = (
            await session.execute(
                # BY PRIMARY KEY, AND WITH THE LIVENESS PREDICATE — the admin realm's
                # equivalent of the `deactivated_at IS NULL` `_load_client_principal`
                # re-reads on every request (BACKEND-PATTERNS §7). This used to be the
                # bare id lookup, because "no row" was the only revocation the realm had;
                # eight `ON DELETE RESTRICT` references made that DELETE impossible for
                # any operator who had done the job, so revocation is now a column
                # (migration f2c74b81a9d3, `authn/subjects._ADMIN_SELECT`).
                #
                # RE-READ HERE rather than trusted from the session, which is what makes
                # `POST /v1/admin/operators/{id}/revocation` take effect on the revoked
                # operator's NEXT request rather than whenever their cookie expires. The
                # session rows are revoked in the same transaction as belt and braces
                # (ASVS 5.0 V7), but correctness does not depend on that write landing.
                #
                # `role` comes from the same row for the same reason: a demotion is a
                # `requires()` refusal on the next request, not on the next sign-in.
                text("SELECT id, role FROM admin_users WHERE id = :sid AND deactivated_at IS NULL"),
                {"sid": verified.subject_id},
            )
        ).first()
        if row is None:
            raise ProblemError.forbidden("This account has no admin access.")
        admin_id, role = row[0], row[1]

        tenant_id: UUID | None = None
        grant: ImpersonationGrant | None = None
        if impersonate_slug:
            # `admin:impersonate` gates the ACT of entering a tenant, not just the mint
            # call that announces it. Checked FIRST, before the slug lookup and before
            # the grant, so an admin without it cannot use 404-vs-403 to probe which
            # client slugs exist — and so that a role that lost the permission is
            # refused even while holding a grant that has not yet expired. That last
            # property is this repo's whole revocation story: authority is re-read from
            # `admin_users` on every request, so a grant outlives nothing.
            if not role_has(role, "admin:impersonate"):
                raise ProblemError.forbidden("This account may not view client accounts.")
            org = (
                await session.execute(
                    text("SELECT id FROM organizations WHERE slug = :slug AND deleted_at IS NULL"),
                    {"slug": impersonate_slug},
                )
            ).first()
            if org is None:
                raise ProblemError.not_found("Organization")
            tenant_id = org[0]
            # THE GRANT IS CHECKED AGAINST THE TENANT THIS REQUEST NAMED, which is why
            # it is checked here and not at the top: the header carries a slug and the
            # grant carries an id, so there is nothing to compare until the slug has
            # been resolved. `verify_grant` takes both bindings in one call so the
            # tenant check cannot be the line somebody forgets — see its docstring.
            grant = verify_grant(
                impersonation_grant, admin_id=UUID(str(admin_id)), tenant_id=UUID(str(tenant_id))
            )

        principal = Principal(
            realm="admin",
            user_id=admin_id,
            tenant_id=tenant_id,
            role=role,
            # D-22: "view as client" is READ-ONLY and every page view is audit-logged.
            #
            # DERIVED FROM THE RESOLVED TENANT, not from the header. `tenant_id` is set
            # on exactly one path — the branch above, which has already checked
            # `admin:impersonate`, resolved the slug and verified the grant — so this
            # spelling makes the flag's contract structural: `impersonating=True` cannot
            # exist without an authorised entry, and the `_record_impersonated_read`
            # call below (guarded on the same value) cannot be skipped for a principal
            # that carries it. `impersonate_slug is not None` was one blank header away
            # from being false on both counts (see `_impersonation_slug`), and the flag
            # is what every mutating dependency in the app reads.
            impersonating=tenant_id is not None,
        )
        if tenant_id is not None and grant is not None:
            # Recorded HERE, before the route's own permission check runs, so an
            # operator who enters a tenant and is then refused by the endpoint is still
            # in the ledger. That is deliberate: "tried to look" is the same question an
            # investigator is asking, and the alternative (audit only successful reads)
            # would let a probe of a client's surface leave nothing behind.
            #
            # `grant is not None` is a type narrowing, not a condition: the two are set
            # in the same branch and `verify_grant` raises rather than returning None.
            await _record_impersonated_read(
                session,
                principal=principal,
                tenant_id=tenant_id,
                ip=ip,
                route=route,
                grant_id=grant.grant_id,
            )

    return principal


async def current_identity(request: Request) -> UUID:
    """A verified client-realm user with NO membership requirement.

    Two flows need this — accepting an invitation, and self-serve signup. The caller holds
    a first-party session but has no `memberships` row yet: that row is what the call
    creates. `current_principal` would 403 them, correctly, which is why neither path can
    use it.

    Returns the user id rather than a `Principal`, because a Principal without a tenant is
    a shape the rest of the code should never have to handle.

    D-124'S RACE IS GONE RATHER THAN HANDLED, and this is where it was worst. These two
    routes used to be reached seconds after Clerk minted an identity, while `user.created`
    was still in flight to our Svix endpoint, so "no `users` row" answered 401 — the one
    status a browser is built to treat as "sign in again", which minted another valid token
    and reproduced it exactly. The row now exists BEFORE any session does: it is created by
    the flow that also sets the password (`authn/invitations.py`), in one transaction, and
    the session is issued from it.
    """
    verified = await verify_token(_credential(request, "client"), "client")
    return await _live_subject(verified)


def _impersonation_slug(request: Request) -> str | None:
    """WHICH tenant this request asks to be read as — absent, or a non-blank slug.

    ONE reading of `X-Impersonate-Org`, shared by `current_admin`, `current_any` and
    `current_principal`, because those three used to disagree about what a PRESENT BUT
    BLANK header means and each disagreement had its own wrong answer:

      - `current_admin` treated `""` as "not a slug to look up" (so no
        `admin:impersonate` check, no grant, no `admin.impersonation_read` row) while
        still setting `impersonating=True` from `is not None`. The result was a
        principal flagged as inside a tenant that had entered none — refused every
        mutation with "Impersonation is read-only. Perform this action from the admin
        console." on the admin console itself, and, more importantly, made
        `Principal.impersonating` mean something weaker than the flag's whole contract
        ("a grant was verified and a read was audited").
      - `current_any` read `""` as falsy and fell through to the CLIENT verifier, so
        an operator met "This token is not valid for this realm" — a realm complaint
        about a header problem, which sends them to the wrong support desk.

    So a blank value is neither "no header" nor a slug: it is a caller that meant to
    name a tenant and named nothing, which is a request defect and is answered as one.
    Whitespace is stripped first for the same reason — ` ` used to reach the directory
    lookup and answer 404 "Organization not found", which reads as "that client was
    deleted".
    """
    raw = request.headers.get(IMPERSONATE_HEADER)
    if raw is None:
        return None
    slug = raw.strip()
    if not slug:
        raise ProblemError(
            kind="validation",
            code="impersonate_org_blank",
            title="No client account named",
            detail=f"{IMPERSONATE_HEADER} was sent with no account slug.",
            remediation=(
                f"Send {IMPERSONATE_HEADER} with the client's slug, or omit it entirely "
                "to use your own operator session."
            ),
        )
    return slug


#: Set on the ASGI scope by the first dependency that resolves a principal for this
#: request. See `_memoised_principal`.
_PRINCIPAL_MEMO = "calevate_principal"


def _memoised_principal(request: Request, realm: Realm) -> Principal | None:
    """The principal an earlier dependency on THIS request already resolved — but only
    if it is one this realm's resolver would itself have produced.

    WHY A MEMO AND NOT FastAPI's DEPENDENCY CACHE. `requires()` calls `current_admin` /
    `current_principal` DIRECTLY rather than through `Depends`, and it has to: the
    permission it enforces is a closure argument, so the dependency FastAPI caches is
    `requires._dep`, not the resolver inside it. A route carrying both
    `Depends(requires(...))` and `Depends(tenant_of)` therefore reaches the resolver
    through two different callables and resolves a principal TWICE — which is most
    tenant-scoped routes in this app (`Session` → `db` → `tenant_of` → `current_any`).

    WHAT THE SECOND RESOLUTION COST, measured rather than assumed (see
    `tests/principal_resolution_test.py`): a second session lookup, and for the client
    realm a second liveness read plus a second membership query. On the admin realm it
    was worse — a second `admin_session` transaction, a second `admin_users` lookup, a
    second directory lookup, a second `verify_grant`, and a SECOND ATTEMPT AT THE
    `admin.impersonation_read` LEDGER ROW. That last one only ever produced one row
    because the Redis dedupe marker absorbed the duplicate; when Redis is unavailable
    `_record_impersonated_read` deliberately fails TOWARDS recording, so every
    impersonated request wrote the D-22 page-view row twice, with the same grant, the
    same instant, and nothing to tell an investigator they were one read.

    D-131 patched the symptom it could see — the tenant rate-limit charge, memoised on
    the same scope — and named the double resolution as the cause. This is the cause.

    `request.scope` rather than `request.state`: the scope is the one object every
    `Request` wrapper built for a request shares, and FastAPI builds several.

    KEYED BY REALM so the memo can only return what the caller asked for. A client-realm
    resolver never receives an admin principal, whatever order the dependencies ran in,
    which keeps this an optimisation rather than a second place realms are decided.

    WHAT IS GIVEN UP, stated because it is a real property: the second within-request
    re-read of `is_active` / membership / `admin_users`. §7 requires deactivation to take
    effect on the next REQUEST, not twice inside one, and nothing observes the principal
    between the two resolutions.
    """
    principal = request.scope.get(_PRINCIPAL_MEMO)
    if isinstance(principal, Principal) and principal.realm == realm:
        return principal
    return None


def _remember_principal(request: Request, principal: Principal) -> Principal:
    """Publish a freshly resolved principal to the rest of the request."""
    request.scope[_PRINCIPAL_MEMO] = principal
    principal_var.set(principal)
    return principal


async def current_principal(request: Request) -> Principal:
    """The client-realm dependency. Admin routes use `current_admin` instead.

    A "view as client" session cannot reach a route declared `realm="client"`: this
    dependency verifies against the CLIENT application's JWKS, and an operator's token
    is not one (TRD §11). That refusal is correct and stays — what changes here is what
    it SAYS. The answer used to be `verify_token`'s "This token is not valid for this
    realm", which is true of the credential and useless to the operator holding it: it
    reads as a broken sign-in rather than as "this surface is not part of view-as".
    Three live routes are in exactly that position (`PUT /v1/billing/caps`,
    `POST /v1/billing/topups/intent`, `POST /v1/compliance/whatsapp-alerts`), and the
    sweep in `tests/realm_boundary_test.py` drives every one of them.

    The check is on the HEADER, not on the token, deliberately: deciding "this is an
    admin's token" would mean verifying it against the admin realm here too, which is a
    second definition of which realm a request belongs to — the thing this module
    exists to define once. The header is what the caller asked for, and asking for
    view-as on a client-realm route is answerable without verifying anything.
    """
    if _impersonation_slug(request) is not None:
        raise ProblemError(
            kind="permission",
            code="impersonation_not_available_here",
            title="Not available in a view-as session",
            detail=(
                "This endpoint is part of the client's own sign-in and is not reachable "
                "from a view-as session."
            ),
            remediation=(
                "Perform this from the operator console's own surfaces for this client, "
                "or ask someone signed in to the account to do it."
            ),
        )
    memoised = _memoised_principal(request, "client")
    if memoised is not None:
        return memoised
    verified = await verify_token(_credential(request, "client"), "client")
    principal = _remember_principal(
        request, await _load_client_principal(verified, request.headers.get(ORG_HEADER))
    )
    await charge_tenant_quota(request, principal)
    return principal


#: Set on the ASGI scope once this request has spent its per-tenant budget.
_TENANT_QUOTA_CHARGED = "calevate_tenant_quota_charged"


async def charge_tenant_quota(request: Request, principal: Principal) -> None:
    """Spend one unit of the tenant's per-minute budget for this route's profile.

    WHY HERE AND NOT IN THE MIDDLEWARE. The per-IP and per-caller dimensions are decided
    before routing, in `RateLimitMiddleware`. This one cannot be: the tenant arrives as
    `X-Org-Slug` (or the view-as pair), and an UNVERIFIED tenant dimension would be a
    weapon rather than a control — anyone could put a competitor's slug on an
    unauthenticated request and exhaust that tenant's bucket. It is charged at the first
    instant the tenant is a verified fact: the resolved principal.

    WHY IT IS MEMOISED ON THE SCOPE, AND HOW THAT RELATES TO `_memoised_principal`.
    They are two invariants, not one guard written twice. `_memoised_principal` makes the
    principal RESOLVE once per request; this makes the tenant budget be SPENT once per
    request, which is the narrower promise and the one that has to survive a second
    caller of this function appearing (it is exported, and a route may charge explicitly).
    Charging twice would make the effective limit depend on which dependencies a route
    happens to declare — the same class of defect as the per-process `hash()` seed D-131
    replaced: a limiter that does not mean what it says. `request.scope` is the one object
    shared by every `Request` wrapper for a request.

    Fails open on a Redis outage (`ratelimit.consume`), like every other dimension.
    """
    if principal.tenant_id is None or request.scope.get(_TENANT_QUOTA_CHARGED):
        return
    request.scope[_TENANT_QUOTA_CHARGED] = True
    route = _route_template(request)
    profile = profile_for(route, request.method)
    if not profile.per_tenant or profile.tenant_from_last_path_segment:
        return
    decision = await consume(profile, "tenant", str(principal.tenant_id), profile.per_tenant)
    if not decision.allowed:
        log.warning(
            "rate_limited",
            extra={"route": route, "profile": profile.name, "dimension": "tenant"},
        )
        raise too_many_requests(decision)


def client_request_ip(request: Request) -> str | None:
    """The CALLER's address, which is what SEC-COMP §5 wants stamped on the audit row.

    IT USED TO BE THE SOCKET PEER, and behind the edge that is nginx — so every row this
    stamped recorded our own proxy, and the ledger satisfied "actor, tenant, at, ip" in
    shape only. The docstring defended it: "this process has no trusted-proxy predicate
    of its own". It has one now, and it is not a new one — `client_ip` is the definition
    voice-runtime has always used to authenticate an unsigned engine by source address,
    promoted into `calevate_shared` so there is exactly one answer to "who is calling"
    across both deployables (CLAUDE.md, "one way per problem").

    The other half of that docstring was already stale when it was written: nginx SETS
    `CF-Connecting-IP` to the real-ip-restored `$remote_addr` on every vhost, api
    included (`infra/nginx/snippets/calevate-proxy.conf`, included by all four server
    blocks), so the value is the edge's statement about the caller and a forgery from
    inside the perimeter is overwritten rather than believed.

    None when the deployment cannot vouch for an address — a peer that is not a trusted
    proxy, or a missing header. NULL in an evidentiary column is honest; the proxy's
    address in it is not, and neither is a header nobody checked.

    THIS IS NOW THE ONLY CALLER OF THAT DEFINITION IN `apps/api`, and a guardrail keeps
    it that way. Eighty handlers used to write `ip=request.client.host if request.client
    else None` inline into `write_audit(...)` — one copy of the defect per audited route,
    every one of them recording the edge — and this docstring carried the grep as a
    worklist until they were swept. `scripts/check_audit_ip.py` now fails CI on any new
    occurrence outside this function, because a worklist in a docstring is a promise and
    a check is a guarantee: the next author to reach for `request.client` is stopped by
    the build rather than by whether a reviewer remembered this paragraph.

    The line below is the ONE legitimate read of the socket peer in this process, and it
    is legitimate precisely because it is an ARGUMENT to the predicate rather than an
    answer: `client_ip` decides whether that peer is a trusted proxy before believing any
    header it sent.
    """
    return client_ip(
        request.client.host if request.client else None,
        request.headers,
        app_env=get_settings().app_env,
    )


def _route_template(request: Request) -> str:
    """`/v1/leads/{lead_id}`, not `/v1/leads/018f...?phone=+9198...`.

    The template is available on the scope once Starlette has matched the route, which
    it has by the time a dependency runs. Falling back to the concrete path would be a
    hard-rule-6 hazard for one line of convenience, so the fallback is a marker instead.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


async def current_admin(request: Request) -> Principal:
    """A verified admin principal, and — when it is entering a tenant — a granted one.

    D-68's MFA gate runs first, inside `verify_token`, and the ORDER matters: the grant
    is never an alternative route in. It cannot be, because it is not a credential —
    every request that presents one also presents the operator's own admin-realm token,
    which has already had to pass the second-factor check. So a grant is strictly
    NARROWER than the session carrying it, and there is no way to combine "a grant" with
    "a token that skipped MFA" into an entry, because the second one never becomes a
    principal at all.

    A grant sent WITHOUT `X-Impersonate-Org` is inert rather than a refusal, and that is
    deliberate: it names a tenant this request is not asking for, so it authorises
    nothing and widens nothing — the caller gets the plain admin session their token was
    always good for. Refusing it would be a rule with no threat behind it, breaking any
    caller that attaches the header uniformly.
    """
    memoised = _memoised_principal(request, "admin")
    if memoised is not None:
        # Including the `admin.impersonation_read` row: one REQUEST is one presence in
        # the ledger, not one per dependency that happened to ask who the caller is.
        return memoised
    verified = await verify_token(_credential(request, "admin"), "admin")
    principal = await _load_admin_principal(
        verified,
        _impersonation_slug(request),
        impersonation_grant=request.headers.get(IMPERSONATION_GRANT_HEADER),
        ip=client_request_ip(request),
        route=_route_template(request),
    )
    _remember_principal(request, principal)
    # A no-op on the admin surface itself (`admin_api` declares no tenant dimension — an
    # operator acting on a tenant must not be throttled by that tenant's own dashboard
    # traffic), and a real charge when a view-as session reads a CLIENT route, where the
    # profile does declare one and the reads are that tenant's.
    await charge_tenant_quota(request, principal)
    return principal


async def current_any(request: Request) -> Principal:
    """Surfaces both realms reach (a client dashboard an admin is viewing, D-22).

    The admin realm is tried FIRST and only when the impersonation header is present,
    so a client token can never be mistaken for an admin one.
    """
    if _impersonation_slug(request) is not None:
        return await current_admin(request)
    return await current_principal(request)


class PermissionDependency(Protocol):
    """A route dependency that CARRIES the permission it enforces.

    `permission_meta()` writes the permission into `openapi_extra` for the docs and the
    generated client; these attributes let the boot registry (rbac §7) check that the
    declared permission is the one the route actually verifies. Without them the
    registry can only read the label, never the lock — and a route that declares a
    permission and forgets the dependency passes a green boot assertion.
    """

    calevate_permission: Permission
    calevate_realm: str

    def __call__(self, request: Request) -> Awaitable[Principal]: ...


def requires(
    permission: Permission, *, realm: Literal["client", "admin", "any"] = "any"
) -> PermissionDependency:
    """Route dependency factory. Pair with `permission_meta(permission)` in
    `openapi_extra` so the boot assertion can see the declaration."""

    async def _dep(request: Request) -> Principal:
        principal = (
            await current_admin(request)
            if realm == "admin"
            else await current_principal(request)
            if realm == "client"
            else await current_any(request)
        )
        if principal.role is None or not role_has(principal.role, permission):
            raise ProblemError.forbidden("You do not have permission to do this.")
        if principal.impersonating and permission in MUTATING_PERMISSIONS:
            # D-22 in one line: read-only keeps the audit trail unambiguous.
            raise ProblemError.forbidden(
                "Impersonation is read-only. Perform this action from the admin console."
            )
        return principal

    dep = cast(PermissionDependency, _dep)
    dep.calevate_permission = permission
    dep.calevate_realm = realm
    return dep


async def tenant_of(principal: Principal = Depends(current_any)) -> UUID:
    if principal.tenant_id is None:
        raise ProblemError(
            kind="validation",
            code="org_required",
            title="Account not specified",
            detail="This endpoint is tenant-scoped and no account was resolved.",
            remediation=(
                f"Send the {ORG_HEADER} header (client), or {IMPERSONATE_HEADER} plus "
                f"{IMPERSONATION_GRANT_HEADER} (admin view-as)."
            ),
        )
    return principal.tenant_id


__all__ = [
    "DEV_TOKEN_NO_MFA_SUFFIX",
    "IMPERSONATE_HEADER",
    "IMPERSONATION_AUDIT_WINDOW_S",
    "IMPERSONATION_GRANT_HEADER",
    "IMPERSONATION_READ_ACTION",
    "MFA_REQUIRED_REALMS",
    "ORG_HEADER",
    "PermissionDependency",
    "VerifiedCaller",
    "charge_tenant_quota",
    "client_request_ip",
    "current_admin",
    "current_any",
    "current_identity",
    "current_principal",
    # Public because `core/stepup.py` asks it the same question this module does — "is this
    # a deployment where a credential-less admin request is legitimate?" — and a second
    # copy of the predicate is exactly the drift that would let the two answers diverge.
    "dev_tokens_permitted",
    "requires",
    "tenant_of",
    "verify_token",
]
