"""Clerk authentication for TWO SEPARATE REALMS + the tenant-scoped session dep.

D-37 keeps Clerk and states the reason plainly: Hard Rule 1's RLS model trusts
`tenant_id` from a verified session, so an auth defect is a cross-tenant data breach,
not a login bug. Clerk authenticates; **our Postgres stays the system of record**
(users/organizations mirrored via Clerk webhooks), and RLS keys off OUR tenant_id.

**Which user a client-realm token IS lives in `core/clerk_identity.py`**, not here, and
both client-realm dependencies call it (D-124). Clerk's mirror is eventually consistent,
so a verified token can arrive before its `users` row: that module reconciles the row
from Clerk's Backend API rather than answering 401, which is what the two membership-less
routes — signup and invite-accept — used to do to every new customer. The admin realm is
deliberately NOT reconciled: `admin_users` is an ops-managed allowlist, not a mirror.

Realms never share session logic (TRD §11): admin tokens are verified against the
admin application's JWKS and can only produce an admin principal; client tokens the
same. A token minted for one realm is not a token for the other.

**MFA is mandatory on the admin realm** (TRD §2, SEC-COMP §5) and is enforced in
`verify_token`, from Clerk's `fva` session claim — see the block above `VerifiedToken`
for the claim's semantics and for why the gate lives in the verifier rather than in
`current_admin` or on each route. The client realm is untouched by it.

Local development: when `APP_ENV=local` AND the realm has no Clerk secret configured,
a `Bearer dev:<realm>:<clerk_user_id>` token is accepted (with an optional `:nomfa`
segment that stands in for a session which never completed a second factor). A
deployment that declares itself `staging` or `prod` can never reach this path,
whatever else is misconfigured
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
from apps.api.core.clerk_identity import resolve_mirrored_user
from apps.api.core.context import (
    IMPERSONATE_HEADER,
    IMPERSONATION_GRANT_HEADER,
    ORG_HEADER,
    Principal,
    Realm,
    principal_var,
)
from apps.api.core.errors import ProblemError
from apps.api.core.impersonation import ImpersonationGrant, verify_grant
from apps.api.core.logging import get_logger
from apps.api.core.rbac import MUTATING_PERMISSIONS, Permission, role_has
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, user_session

log = get_logger(__name__)

CLERK_LEEWAY_S = 30

_jwk_clients: dict[str, PyJWKClient] = {}

# A Clerk publishable key is `pk_test_`/`pk_live_` + base64 of the application's
# Frontend API host with a trailing `$`.
_PUBLISHABLE_PREFIXES = ("pk_test_", "pk_live_")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
# Header values arrive latin-1-decoded, so a raw control byte survives as a character.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


# --- Admin-realm MFA (TRD §2 "MFA mandatory on admin realm", SEC-COMP §5) ----------
#
# WHAT CLERK ACTUALLY GIVES US, AND WHERE THAT WAS ESTABLISHED.
# A Clerk session token carries `fva` — "factor verification age" — a two-element array
# of MINUTES since each factor was last verified: `[firstFactorAge, secondFactorAge]`.
# `-1` in a slot means that factor was NEVER verified for this session; `[0, -1]` is the
# ordinary shape for a user with no second factor enrolled, and `[9, 3]` is a session
# that completed both. The claim is on the DEFAULT session token — no JWT template is
# needed to obtain it — and it is the same value Clerk's own SDKs read: the Go SDK
# declares `FactorVerificationAge [2]int64 \`json:"fva"\`` on `Claims` and builds
# `SessionClaims.NeedsReverification(policy)` on top of it
# (pkg.go.dev/github.com/clerk/clerk-sdk-go/v2, read 2026-08-14), and Clerk's own
# Supabase integration guide shows the identical predicate expressed as an RLS policy
# ("check that the second factor verification age element in the fva claim is not -1").
# Clerk's docs for it are clerk.com/docs/guides/sessions/session-tokens and
# clerk.com/docs/guides/secure/force-mfa; both are unreachable from this build host, so
# the citations above are the ones that could be read directly.
#
# WHY THE PREDICATE IS `fva[1] >= 0` AND NOT AN AGE BOUND.
# The requirement in TRD §2 is about AUTHENTICATION — did this session ever prove a
# second factor — not about freshness. Clerk models freshness separately, as
# "reverification" (`strict_mfa` etc.), and using it here would mean an operator whose
# second factor is two hours old could not lift a halt at 3am without signing out and
# back in, because this repo has no reverification flow in the browser to raise the
# prompt. Gating an incident lever on a flow that does not exist would be a control that
# gets switched off. Freshness is therefore a NAMED follow-up (OPERATIONS §2), not a
# silent omission — and per-action consent is separately covered by `X-Confirm-Action`
# (see `ops/routes.py`, which records why both survive).
#
# WHY AN ABSENT CLAIM IS A REFUSAL.
# A missing `fva` means we cannot tell whether a second factor happened, and this is the
# realm that holds the big red switch. Reading "unknown" as "verified" would mean a
# custom JWT template that drops the claim silently disables MFA for the whole console
# with nothing failing. So it fails CLOSED, and the refusal names the fix rather than
# saying "forbidden".
SECOND_FACTOR_CLAIM = "fva"

#: The realms where a second factor is MANDATORY. The client realm is deliberately not
#: here: SEC-COMP §5 requires MFA on admin only, and client owners on Indian SMB
#: hardware are not who this control protects against.
MFA_REQUIRED_REALMS: frozenset[str] = frozenset({"admin"})

#: `dev:<realm>:<clerk_user_id>:nomfa` — the local-only way to obtain a token that has
#: NOT completed a second factor, so the refusal can be exercised in both directions.
#: A plain three-segment dev token counts as MFA-complete, because it already bypasses
#: authentication entirely (local + no Clerk secret, asserted in `authz_audit_test`) and
#: making it MFA-incomplete by default would only mean every local screen and every
#: admin test asserts the refusal path and nothing asserts the allowed one.
DEV_TOKEN_NO_MFA_SUFFIX = "nomfa"


def _second_factor_age_minutes(claims: dict[str, Any]) -> int | None:
    """Minutes since this session verified a SECOND factor.

    `-1` (Clerk's "never verified") is returned as-is; `None` means the token carried no
    usable `fva` claim at all, which the caller treats as a refusal, not as a pass.
    """
    fva = claims.get(SECOND_FACTOR_CLAIM)
    if not isinstance(fva, list) or len(fva) < 2:
        return None
    second = fva[1]
    # `bool` is an `int` in Python and `fva: [true, true]` must not read as "verified".
    if isinstance(second, bool) or not isinstance(second, int):
        return None
    return second


def _require_second_factor(realm: Realm, second_factor_age_min: int | None) -> None:
    if realm not in MFA_REQUIRED_REALMS:
        return
    if second_factor_age_min is None:
        raise ProblemError(
            kind="permission",
            code="mfa_claim_missing",
            title="Two-step verification could not be checked",
            detail="This session does not say whether a second factor was verified.",
            remediation=(
                "The admin Clerk application must issue the default session token "
                "claims: a custom JWT template that omits `fva` cannot be used on this "
                "realm (OPERATIONS §2)."
            ),
        )
    if second_factor_age_min < 0:
        log.warning("admin_mfa_missing")
        raise ProblemError(
            kind="permission",
            code="mfa_required",
            title="Two-step verification required",
            detail=(
                "The operator console requires two-step verification, and this sign-in "
                "did not complete a second factor."
            ),
            remediation=(
                "Set up two-step verification on your Calevate operator account, then "
                "sign out and sign in again."
            ),
        )


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    clerk_user_id: str
    email: str | None
    realm: Realm
    #: Minutes since this session's second factor was verified; `-1` = never verified,
    #: `None` = the token said nothing. Carried on the token rather than recomputed,
    #: because it is a property of the CREDENTIAL and nothing downstream may re-decide
    #: it. See `_require_second_factor` for the policy applied to it.
    second_factor_age_min: int | None = None


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
    """`dev:<realm>:<clerk_user_id>[:nomfa]` — local only, and only when Clerk is absent.

    The optional fourth segment is the local stand-in for Clerk's `fva[1] == -1`: an
    operator who signed in but never completed a second factor. It exists so the
    admin-realm MFA refusal is exercised on the SAME code path that serves the allowed
    case, rather than only in a unit test of the predicate — the gate is in
    `verify_token`, so a dev token that claims no second factor must meet it there.
    """
    settings = get_settings()
    if settings.app_env != "local":
        return None
    configured = (
        settings.clerk_admin_secret_key if realm == "admin" else settings.clerk_client_secret_key
    )
    if configured:
        return None
    parts = token.split(":")
    if len(parts) not in (3, 4) or parts[0] != "dev" or parts[1] != realm:
        return None
    if len(parts) == 4 and parts[3] != DEV_TOKEN_NO_MFA_SUFFIX:
        # An unrecognised suffix is not a token with a typo we should be lenient about:
        # `dev:admin:me:mfa` would otherwise be read as "no suffix I know, so allow",
        # which is the wrong direction for the one realm this gate protects.
        return None
    log.warning("dev_token_accepted", extra={"realm": realm})
    return VerifiedToken(
        clerk_user_id=parts[2],
        email=None,
        realm=realm,
        second_factor_age_min=-1 if len(parts) == 4 else 0,
    )


async def verify_token(token: str, realm: Realm) -> VerifiedToken:
    """A verified credential for THIS realm — and on the admin realm, only ever one that
    completed a second factor.

    WHY THE MFA GATE IS HERE AND NOT IN `current_admin` OR IN A ROUTE DEPENDENCY.
    This function is the only way to turn a string into an admin-realm identity. Putting
    the check here makes "an admin token" and "an admin token that passed MFA" the SAME
    object: there is no `VerifiedToken(realm="admin")` in existence that skipped it, so a
    dependency written next year is covered by calling the verifier at all, and cannot
    opt out without opting out of authentication. Rejected:
      - `current_admin`: correct today (it is the sole admin caller) and one direct
        `verify_token(..., "admin")` away from being wrong — the same shape of defect as
        a permission named after an act that did not gate the act.
      - A ROUTE DEPENDENCY / `requires(..., realm="admin")`: ~60 declarations, and the
        one that forgets it is the one that matters.
      - MIDDLEWARE: runs before the realm is known — it would have to re-parse the
        Authorization header and re-decide which realm this request is, which is a
        second definition of the thing this module exists to define once.
    """
    dev = _verify_dev_token(token, realm)
    if dev is not None:
        _require_second_factor(realm, dev.second_factor_age_min)
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
    second_factor_age_min = _second_factor_age_minutes(claims)
    # AFTER the signature, the expiry and the subject: an unsigned or expired token must
    # answer "sign in again", never "set up two-step verification" — the second sentence
    # would tell an anonymous caller that a valid-looking token got further than it did.
    _require_second_factor(realm, second_factor_age_min)
    return VerifiedToken(
        clerk_user_id=subject,
        email=email if isinstance(email, str) else None,
        realm=realm,
        second_factor_age_min=second_factor_age_min,
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

    The identity half is `clerk_identity.resolve_mirrored_user`, shared with
    `current_identity` — one definition of "which user is this token", reconciling from
    Clerk's Backend API when the Svix mirror has not landed yet (D-124). This route
    reaches that state too: a member who accepted an invite in one tab and opens the
    console in another can beat the webhook, and the answer there was the same
    unrecoverable 401.
    """
    user_id: UUID = await resolve_mirrored_user(verified.clerk_user_id)

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
    verified: VerifiedToken,
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
                text("SELECT id, role FROM admin_users WHERE clerk_user_id = :cid"),
                {"cid": verified.clerk_user_id},
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
            clerk_user_id=verified.clerk_user_id,
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


async def current_identity(request: Request) -> tuple[UUID, str]:
    """A verified client-realm user with NO membership requirement.

    Two flows need this — accepting an invitation, and self-serve signup. The caller has
    signed up with Clerk but has no `memberships` row yet: that row is what the call
    creates. `current_principal` would 403 them, correctly, which is why neither path can
    use it.

    Returns (user_id, clerk_user_id) rather than a Principal, because a Principal
    without a tenant is a shape the rest of the code should never have to handle.

    THE MIRROR RACE IS THE ORDINARY CASE HERE, not an edge (D-124). These two routes are
    reached seconds after Clerk mints the identity, while `user.created` is still in
    flight to our Svix endpoint, so "no `users` row" used to answer 401 — the one status
    a browser is built to treat as "sign in again", which mints another valid token and
    reproduces it exactly. `resolve_mirrored_user` reconciles from Clerk's Backend API
    instead, and only falls back to a transient, retryable refusal when Clerk itself
    cannot be reached.
    """
    verified = await verify_token(_bearer(request), "client")
    return await resolve_mirrored_user(verified.clerk_user_id), verified.clerk_user_id


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
    verified = await verify_token(_bearer(request), "admin")
    principal = await _load_admin_principal(
        verified,
        _impersonation_slug(request),
        impersonation_grant=request.headers.get(IMPERSONATION_GRANT_HEADER),
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
    "SECOND_FACTOR_CLAIM",
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
