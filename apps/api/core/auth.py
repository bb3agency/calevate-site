"""Clerk authentication for TWO SEPARATE REALMS + the tenant-scoped session dep.

D-37 keeps Clerk and states the reason plainly: Hard Rule 1's RLS model trusts
`tenant_id` from a verified session, so an auth defect is a cross-tenant data breach,
not a login bug. Clerk authenticates; **our Postgres stays the system of record**
(users/organizations mirrored via Clerk webhooks), and RLS keys off OUR tenant_id.

Realms never share session logic (TRD §11): admin tokens are verified against the
admin application's JWKS and can only produce an admin principal; client tokens the
same. A token minted for one realm is not a token for the other.

Local development: when `APP_ENV=local` AND the realm has no Clerk secret configured,
a `Bearer dev:<realm>:<clerk_user_id>` token is accepted. Both conditions are
required, so staging/prod (which always carry Clerk keys, enforced by
`runtime_config_missing_keys`) can never fall into this path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Request
from jwt import PyJWKClient
from sqlalchemy import text

from apps.api.core.context import Principal, Realm, principal_var
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import MUTATING_PERMISSIONS, Permission, role_has
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session, user_session

log = get_logger(__name__)

ORG_HEADER = "X-Org-Slug"
IMPERSONATE_HEADER = "X-Impersonate-Org"
CLERK_LEEWAY_S = 30

_jwk_clients: dict[str, PyJWKClient] = {}


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    clerk_user_id: str
    email: str | None
    realm: Realm


def _jwks_url(secret_key: str) -> str:
    """Clerk's JWKS lives on the instance's Frontend API host. The publishable key
    encodes that host; the secret key does not, so we read it from settings — the
    custom domain is `accounts.calevate.tech` (D-37)."""
    del secret_key
    settings = get_settings()
    host = settings.clerk_frontend_api or "accounts.calevate.tech"
    return f"https://{host}/.well-known/jwks.json"


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
        _jwk_clients[realm] = PyJWKClient(_jwks_url(secret), cache_keys=True)
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
    except (jwt.InvalidTokenError, httpx.HTTPError) as exc:
        # Never echo the reason to the caller: "expired" vs "bad signature" is a
        # probing oracle. It is logged (redacted) for support.
        log.warning("token_rejected", extra={"realm": realm, "reason": type(exc).__name__})
        raise ProblemError.unauthorized("Your session is not valid. Sign in again.") from exc

    exp = claims.get("exp")
    if isinstance(exp, int) and exp + CLERK_LEEWAY_S < int(time.time()):
        raise ProblemError.unauthorized("Your session has expired.")
    subject = claims.get("sub")
    if not isinstance(subject, str):
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
    return token.strip()


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


async def _load_admin_principal(verified: VerifiedToken, impersonate_slug: str | None) -> Principal:
    async with untenanted_session() as session:
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
            org = (
                await session.execute(
                    text("SELECT id FROM organizations WHERE slug = :slug AND deleted_at IS NULL"),
                    {"slug": impersonate_slug},
                )
            ).first()
            if org is None:
                raise ProblemError.not_found("Organization")
            tenant_id = org[0]

    return Principal(
        realm="admin",
        user_id=admin_id,
        clerk_user_id=verified.clerk_user_id,
        tenant_id=tenant_id,
        role=role,
        # D-22: "view as client" is READ-ONLY and every page view is audit-logged.
        impersonating=impersonate_slug is not None,
    )


async def current_principal(request: Request) -> Principal:
    """The client-realm dependency. Admin routes use `current_admin` instead."""
    verified = await verify_token(_bearer(request), "client")
    principal = await _load_client_principal(verified, request.headers.get(ORG_HEADER))
    principal_var.set(principal)
    return principal


async def current_admin(request: Request) -> Principal:
    verified = await verify_token(_bearer(request), "admin")
    principal = await _load_admin_principal(verified, request.headers.get(IMPERSONATE_HEADER))
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


def requires(permission: Permission, *, realm: Literal["client", "admin", "any"] = "any"):
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

    return _dep


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
    "ORG_HEADER",
    "VerifiedToken",
    "current_admin",
    "current_any",
    "current_principal",
    "requires",
    "tenant_of",
    "verify_token",
]
