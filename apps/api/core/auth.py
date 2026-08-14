"""Clerk authentication for TWO SEPARATE REALMS + the tenant-scoped session dep.

D-37 keeps Clerk and states the reason plainly: Hard Rule 1's RLS model trusts
`tenant_id` from a verified session, so an auth defect is a cross-tenant data breach,
not a login bug. Clerk authenticates; **our Postgres stays the system of record**
(users/organizations mirrored via Clerk webhooks), and RLS keys off OUR tenant_id.

Realms never share session logic (TRD §11): admin tokens are verified against the
admin application's JWKS and can only produce an admin principal; client tokens the
same. A token minted for one realm is not a token for the other.

Local development: when `APP_ENV=local` AND the realm has no Clerk secret configured,
a `Bearer dev:<realm>:<clerk_user_id>` token is accepted. A deployment that declares
itself `staging` or `prod` can never reach this path, whatever else is misconfigured
(asserted in `tests/authz_audit_test.py`).

`app_env` carries that whole weight, so it has NO DEFAULT: `Settings.app_env` is a
required field and `APP_ENV` is in `BOOTSTRAP_REQUIRED`, because the previous default
of `"local"` meant a deployment that simply never set the variable accepted dev tokens
AND reported itself healthy (`runtime_config_missing_keys` skipped its Clerk checks
under the same branch). Two guards, one missing variable, both off. The environment is
now stated or the process does not start — see `core/settings.py::BOOTSTRAP_REQUIRED`
and `tests/app_env_required_test.py`.
"""

from __future__ import annotations

import base64
import binascii
import re
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from uuid import UUID

import jwt
from fastapi import Depends, Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.context import (
    IMPERSONATE_HEADER,
    ORG_HEADER,
    Principal,
    Realm,
    principal_var,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import MUTATING_PERMISSIONS, Permission, role_has
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, untenanted_session, user_session

log = get_logger(__name__)

CLERK_LEEWAY_S = 30

_jwk_clients: dict[str, PyJWKClient] = {}

# A Clerk publishable key is `pk_test_`/`pk_live_` + base64 of the application's
# Frontend API host with a trailing `$`.
_PUBLISHABLE_PREFIXES = ("pk_test_", "pk_live_")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
# Header values arrive latin-1-decoded, so a raw control byte survives as a character.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    clerk_user_id: str
    email: str | None
    realm: Realm


def _host_from_publishable_key(key: str | None) -> str | None:
    """The Frontend API host a Clerk publishable key encodes, or None if it encodes
    nothing we recognise (unset, a placeholder, a secret key pasted by mistake)."""
    if not key:
        return None
    encoded = next((key[len(p) :] for p in _PUBLISHABLE_PREFIXES if key.startswith(p)), None)
    if not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("ascii")
    except (binascii.Error, ValueError):
        return None
    host = decoded.rstrip("$").lower()
    return host if _HOSTNAME_RE.match(host) else None


def jwks_url(realm: Realm) -> str:
    """Where THIS realm's signing keys live.

    The realms are two separate Clerk applications (TRD §11, D-37) and each publishes
    its JWKS on its OWN Frontend API host. Resolving both to one host would make the
    separation nominal: the admin verifier would accept a signature minted for the
    client application, leaving `admin_users` membership as the only thing between a
    client token and the admin console — an authorization check standing in for an
    authentication one.

    The publishable key encodes its application's host, which is why both keys are in
    Settings. `clerk_frontend_api` remains the fallback for a single-application or
    custom-domain deployment, which is what it always described.
    """
    settings = get_settings()
    publishable = (
        settings.clerk_admin_publishable_key
        if realm == "admin"
        else settings.clerk_client_publishable_key
    )
    host = _host_from_publishable_key(publishable) or settings.clerk_frontend_api
    return f"https://{host or 'accounts.calevate.tech'}/.well-known/jwks.json"


def _jwk_client(realm: Realm) -> PyJWKClient:
    if realm not in _jwk_clients:
        settings = get_settings()
        secret = (
            settings.clerk_admin_secret_key
            if realm == "admin"
            else settings.clerk_client_secret_key
        )
        if not secret:
            raise ProblemError(
                kind="dependency",
                code="auth_not_configured",
                title="Authentication is not configured",
                detail="This deployment has no Clerk credentials for that realm.",
            )
        _jwk_clients[realm] = PyJWKClient(jwks_url(realm), cache_keys=True)
    return _jwk_clients[realm]


def _verify_dev_token(token: str, realm: Realm) -> VerifiedToken | None:
    """`dev:<realm>:<clerk_user_id>` — local only, and only when Clerk is absent."""
    settings = get_settings()
    if settings.app_env != "local":
        return None
    configured = (
        settings.clerk_admin_secret_key if realm == "admin" else settings.clerk_client_secret_key
    )
    if configured:
        return None
    parts = token.split(":")
    if len(parts) != 3 or parts[0] != "dev" or parts[1] != realm:
        return None
    log.warning("dev_token_accepted", extra={"realm": realm})
    return VerifiedToken(clerk_user_id=parts[2], email=None, realm=realm)


async def verify_token(token: str, realm: Realm) -> VerifiedToken:
    dev = _verify_dev_token(token, realm)
    if dev is not None:
        return dev
    if token.startswith("dev:"):
        # A dev token for the WRONG realm (or in an environment where dev tokens are
        # disabled). It is never a valid JWT, so answering 401 is both correct and
        # honest — falling through to JWKS would report "auth not configured", which
        # tells the caller about our deployment instead of about their token.
        raise ProblemError.unauthorized("This token is not valid for this realm.")
    try:
        signing_key = _jwk_client(realm).get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            leeway=CLERK_LEEWAY_S,
            options={"verify_aud": False},
        )
    except ProblemError:
        raise
    except (PyJWKClientConnectionError, OSError) as exc:
        # Clerk is unreachable. That is OUR dependency failing, not the caller's
        # session expiring: answering 401 would sign everybody out during an outage,
        # and letting it escape (which it did — `PyJWKClient` fetches over urllib, so
        # the old `httpx.HTTPError` clause never matched) turned every request into a
        # 500 plus an alert.
        log.warning("jwks_unavailable", extra={"realm": realm, "reason": type(exc).__name__})
        raise ProblemError(
            kind="dependency",
            code="auth_provider_unavailable",
            title="Sign-in is temporarily unavailable",
            detail="We could not reach the sign-in service.",
            remediation="Retry in a few seconds.",
        ) from exc
    except jwt.PyJWTError as exc:
        # `jwt.PyJWTError`, not `jwt.InvalidTokenError`: `PyJWKClientError` (raised for
        # an unknown `kid` — exactly what a token from the OTHER realm looks like) is a
        # sibling of InvalidTokenError, not a subclass, so it used to escape as a 500.
        # Never echo the reason to the caller: "expired" vs "bad signature" vs "unknown
        # key" is a probing oracle. It is logged (redacted) for support.
        log.warning("token_rejected", extra={"realm": realm, "reason": type(exc).__name__})
        raise ProblemError.unauthorized("Your session is not valid. Sign in again.") from exc

    exp = claims.get("exp")
    if isinstance(exp, int) and exp + CLERK_LEEWAY_S < int(time.time()):
        raise ProblemError.unauthorized("Your session has expired.")
    subject = claims.get("sub")
    if not isinstance(subject, str) or _CONTROL_CHARS.search(subject):
        # The subject becomes a SQL parameter two calls from here. See `_bearer`.
        raise ProblemError.unauthorized()
    email = claims.get("email")
    return VerifiedToken(
        clerk_user_id=subject, email=email if isinstance(email, str) else None, realm=realm
    )


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ProblemError.unauthorized()
    token = token.strip()
    if not token or _CONTROL_CHARS.search(token):
        # A credential is ASCII-printable — a JWT is base64url, a dev token is
        # `dev:<realm>:<clerk-user-id>` — so a control byte is not a token that failed
        # to verify. It matters because the token's subject travels into a SQL
        # parameter: `Bearer dev:client:a\x00b` reached the `users` lookup and psycopg
        # refused it ("PostgreSQL text fields cannot contain NUL"), which is a 500 and
        # an alert, on every authenticated endpoint, for any unauthenticated caller.
        # Rejected here, at the boundary, so every path downstream is spared the case.
        raise ProblemError.unauthorized()
    return token


# --- Principal resolution -----------------------------------------------------


async def _load_client_principal(verified: VerifiedToken, org_slug: str | None) -> Principal:
    """users + memberships are OURS (D-37) — Clerk says who, we say what they may see.

    `is_active` is re-checked against the DB on every request rather than trusted
    from the cached session (§7): deactivation must take effect immediately.
    """
    # `users` is a GLOBAL table (identity crosses tenants), so this lookup needs no
    # tenant context — which is exactly why it can be the first step.
    async with untenanted_session() as session:
        user_row = (
            await session.execute(
                text("SELECT id FROM users WHERE clerk_user_id = :cid AND deactivated_at IS NULL"),
                {"cid": verified.clerk_user_id},
            )
        ).first()
    if user_row is None:
        raise ProblemError.unauthorized("This account is not provisioned.")
    user_id: UUID = user_row[0]

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
        clerk_user_id=verified.clerk_user_id,
        tenant_id=tenant_id,
        role=role,
    )


# --- D-22 / SEC-COMP §5: the impersonated read is audited ---------------------
#
# The spec is "session start + every page view audit-logged (actor=admin_user, tenant,
# at, ip)". Only the first half existed: `POST /v1/admin/tenants/{id}/impersonate`
# writes `admin.impersonation_started` — and MINTS NOTHING, so nothing ever forced an
# operator through it. The entry to a tenant is the `X-Impersonate-Org` header, and an
# admin who sent that header and skipped the announcement left no trace at all, while
# four docstrings across this repo asserted that every page view was recorded.
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
# THE BYPASS IS NARROWED, NOT CLOSED, AND IT IS NAMED HERE. The start endpoint still
# mints no credential, so an operator can still enter a tenant with the header alone
# and never announce it. What changes is that doing so is no longer INVISIBLE — the
# read path records it whether or not the announcement happened. Making the header
# useless without a minted, short-lived, signed grant is the real fix, and it is out of
# scope for this change because it needs `apps/web` to call the start endpoint and hold
# the grant (that code sends the slug directly today — `apps/web/src/lib/api/admin.ts`)
# plus a decision-log entry for the credential's shape, lifetime and revocation. Until
# then the ledger's answer to "did an operator go in the front door" is
# `admin.impersonation_started`, and its answer to "was an operator in there at all" is
# the action below — which is the one that cannot be skipped.
IMPERSONATION_READ_ACTION = "admin.impersonation_read"
IMPERSONATION_AUDIT_WINDOW_S = 60


async def _record_impersonated_read(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID,
    ip: str | None,
    route: str,
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
        summary={"route": route, "window_s": IMPERSONATION_AUDIT_WINDOW_S},
    )


async def _load_admin_principal(
    verified: VerifiedToken,
    impersonate_slug: str | None,
    *,
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
                text("SELECT id, role FROM admin_users WHERE clerk_user_id = :cid"),
                {"cid": verified.clerk_user_id},
            )
        ).first()
        if row is None:
            raise ProblemError.forbidden("This account has no admin access.")
        admin_id, role = row[0], row[1]

        tenant_id: UUID | None = None
        if impersonate_slug:
            # `admin:impersonate` gates the ACT of entering a tenant, not just the
            # `/v1/admin/tenants/{id}/impersonate` call that announces it — that
            # endpoint mints no credential, so nothing forced a caller through it and
            # the permission named after the act did not gate the act. Checked before
            # the slug lookup so an admin without it cannot use 404-vs-403 to probe
            # which client slugs exist.
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

        principal = Principal(
            realm="admin",
            user_id=admin_id,
            clerk_user_id=verified.clerk_user_id,
            tenant_id=tenant_id,
            role=role,
            # D-22: "view as client" is READ-ONLY and every page view is audit-logged.
            impersonating=impersonate_slug is not None,
        )
        if tenant_id is not None:
            # Recorded HERE, before the route's own permission check runs, so an
            # operator who enters a tenant and is then refused by the endpoint is still
            # in the ledger. That is deliberate: "tried to look" is the same question an
            # investigator is asking, and the alternative (audit only successful reads)
            # would let a probe of a client's surface leave nothing behind.
            await _record_impersonated_read(
                session, principal=principal, tenant_id=tenant_id, ip=ip, route=route
            )

    return principal


async def current_identity(request: Request) -> tuple[UUID, str]:
    """A verified client-realm user with NO membership requirement.

    Exactly one flow needs this: accepting an invitation. The invitee has signed up
    with Clerk and has been mirrored into `users`, but has no `memberships` row yet —
    that row is what accepting the invitation creates. `current_principal` would 403
    them, correctly, which is why the invite path cannot use it.

    Returns (user_id, clerk_user_id) rather than a Principal, because a Principal
    without a tenant is a shape the rest of the code should never have to handle.
    """
    verified = await verify_token(_bearer(request), "client")
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT id FROM users WHERE clerk_user_id = :cid AND deactivated_at IS NULL"),
                {"cid": verified.clerk_user_id},
            )
        ).first()
    if row is None:
        raise ProblemError.unauthorized("This account is not provisioned.")
    return UUID(str(row[0])), verified.clerk_user_id


async def current_principal(request: Request) -> Principal:
    """The client-realm dependency. Admin routes use `current_admin` instead."""
    verified = await verify_token(_bearer(request), "client")
    principal = await _load_client_principal(verified, request.headers.get(ORG_HEADER))
    principal_var.set(principal)
    return principal


def _request_ip(request: Request) -> str | None:
    """The peer address, which is what SEC-COMP §5 wants stamped on the audit row.

    Deliberately the SOCKET peer and not a forwarded header: a header is whatever the
    caller typed unless the immediate peer is a trusted edge, and this process has no
    trusted-proxy predicate of its own (voice-runtime's `client_ip` has one because it
    authenticates an unsigned engine by source IP — a different problem with a
    different threat model). Behind Cloudflare + nginx this is the edge's address until
    DEPLOYMENT §5's real-ip restoration is in front of the API, at which point it
    becomes the operator's. An honest "the request came from our edge" beats a
    spoofable "it came from 1.2.3.4" in a tamper-evident ledger. Same source
    `admin/routes.py` already stamps on `admin.impersonation_started`, so both halves
    of one session's trail agree.
    """
    return request.client.host if request.client else None


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
    verified = await verify_token(_bearer(request), "admin")
    principal = await _load_admin_principal(
        verified,
        request.headers.get(IMPERSONATE_HEADER),
        ip=_request_ip(request),
        route=_route_template(request),
    )
    principal_var.set(principal)
    return principal


async def current_any(request: Request) -> Principal:
    """Surfaces both realms reach (a client dashboard an admin is viewing, D-22).

    The admin realm is tried FIRST and only when the impersonation header is present,
    so a client token can never be mistaken for an admin one.
    """
    if request.headers.get(IMPERSONATE_HEADER):
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
            raise ProblemError.forbidden(f"This action requires the {permission} permission.")
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
            remediation=f"Send the {ORG_HEADER} header (client) or {IMPERSONATE_HEADER} (admin).",
        )
    return principal.tenant_id


__all__ = [
    "IMPERSONATE_HEADER",
    "IMPERSONATION_AUDIT_WINDOW_S",
    "IMPERSONATION_READ_ACTION",
    "ORG_HEADER",
    "PermissionDependency",
    "VerifiedToken",
    "current_admin",
    "current_any",
    "current_identity",
    "current_principal",
    "jwks_url",
    "requires",
    "tenant_of",
    "verify_token",
]
