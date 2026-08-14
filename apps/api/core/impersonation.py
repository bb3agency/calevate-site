"""The short-lived grant that authorises ONE D-22 "view as client" session.

WHAT WAS BROKEN, AND WHY THIS FILE EXISTS.
`POST /v1/admin/tenants/{id}/impersonate` wrote `admin.impersonation_started` and MINTED
NOTHING. Entry to a tenant was the `X-Impersonate-Org` header alone, and the console
never called the endpoint at all — it simply set the header (`apps/web/src/lib/api/
admin.ts`). So D-22's "session start ... audit-logged" half was absent for every real
session: the row existed in the source and in no database. The read path
(`core/auth.py::_record_impersonated_read`) narrowed that hole but could not close it —
it records that an operator WAS inside a tenant, never that they were ever authorised to
enter. This module is the authorisation, and it is what makes the start row exist.

WHAT THIS IS, IN THE VOCABULARY OF THE SPEC THAT ALREADY MODELS IT.
RFC 8693 (OAuth 2.0 Token Exchange) names this exact shape. Its `act` claim "provides a
means within a JWT to express that delegation has occurred and identify the acting party
to whom authority has been delegated" (IANA JWT Claims registry entry for `act`, citing
RFC 8693 §4.1), and the spec's own distinction is that a token CARRYING `act` has
DELEGATION semantics — "this actor is acting on behalf of this subject" — while a token
WITHOUT it has IMPERSONATION semantics: the actor simply *is* the subject.

That distinction is D-22's, written by somebody else first. D-22 forbids acting-as
precisely because it wants "no dual attribution" in the audit trail — so although the
feature is called impersonation, its credential is RFC-8693-*delegation*-shaped on
purpose: `sub` is the tenant whose data may be read and `act.sub` is the operator
reading it, and both are on the wire, always. A grant that named only the tenant would
be the impersonation shape and would be the ambiguity D-22 exists to prevent.
(rfc-editor.org and datatracker.ietf.org are both blocked from this build host, so the
registry description quoted above is the wording that could be read directly; the
delegation/impersonation split is RFC 8693 §1.1 and §4.1.)

DELIBERATELY NOT ADOPTED FROM THAT SPEC: the token-exchange *endpoint*, `may_act`, and
nested `act` chains. We have one actor, one subject, one hop, and one issuer who is also
the only verifier. A `/token` endpoint with `subject_token_type` negotiation would be a
second authentication protocol in a service whose authentication is Clerk (D-37). The
CLAIM SHAPE is the part worth borrowing, because it is the part a reviewer already
knows how to read. Chaining is refused explicitly at the mint route: an impersonating
session may not mint a grant.

WHAT THE GRANT IS BOUND TO, AND WHY EACH BINDING IS THERE.
  - `sub`  = the TENANT (`organizations.id`, never the slug — a slug is a display
             handle and could in principle be reassigned; RLS keys off the id).
             Without this a grant is a skeleton key: mint one for a client you are
             allowed to see, replay it against any other. This is the binding
             `tests/impersonation_grant_test.py` sabotage-checks.
  - `act.sub` = the ADMIN (`admin_users.id`). Without it, a leaked grant plus any
             admin token is an entry with no start row naming the entrant — which
             would put us back where we started, one indirection later.
  - `aud`  = a fixed audience, so this token is refused by anything that verifies a
             different one. Audience binding is the standard defence against replaying
             a token at a service it was not minted for (RFC 8707 resource indicators
             make the same argument for access tokens).
  - `exp`  = a short life. See GRANT_TTL for why fifteen minutes and not five.
  - `jti`  = the grant id. It is what makes `admin.impersonation_started` and
             `admin.impersonation_read` JOINABLE: one start row, N read rows, same id.

WHAT THE GRANT IS **NOT**: a credential. It never travels in `Authorization` and it can
do nothing on its own. Every request that presents it also presents the operator's own
admin-realm Clerk token, which is verified (and MFA-gated, D-68) by `verify_token`, and
whose `admin_users` row and role are re-read from the database on every single request
by `_load_admin_principal`. That is the whole revocation story and it has ZERO lag:

  - operator signs out / session expires  -> `verify_token` 401s. Grant inert.
  - `admin_users` row removed             -> "This account has no admin access." 403.
  - role loses `admin:impersonate`        -> the existing `role_has` check refuses.
  - tenant soft-deleted                   -> the slug lookup already filters it. 404.

So there is no denylist and no `impersonation_grants` table, and that is a decision
rather than an omission. A revocation list exists to shorten the window between "this
principal lost authority" and "their outstanding tokens stop working"; here that window
is one request, enforced by machinery that already runs. Adding a table would add a
migration, an RLS policy, a reaper job and a per-request read, and would close nothing.
WHAT WOULD CHANGE THE ANSWER: making the grant presentable *without* the admin's own
token. If that is ever proposed, this paragraph is the thing it invalidates.

WHY A JWT AND NOT A HAND-ROLLED HMAC ENVELOPE. `exp`/`aud`/`jti`/`sub`/`act` are all
registered claims with agreed semantics, PyJWT is already a dependency (it verifies
Clerk's tokens next door), and it enforces expiry and audience for us. A bespoke
`v1.<payload>.<mac>` format would be a second token format in this repo and would have
to re-derive the parts every hand-rolled one gets wrong. `algorithms=[...]` is pinned on
BOTH encode and decode: an unpinned `decode` is the classic algorithm-confusion bug
(`alg: none`, or RS256→HS256 downgrade), and the mitigation everyone converged on is an
explicit allowlist at the verify call rather than trusting the token's own header
(portswigger.net/web-security/jwt/algorithm-confusion; PyJWT made `algorithms` mandatory
for this reason).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import jwt

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: The one audience this token is minted for and the only one it is accepted under.
GRANT_AUDIENCE: Final = "calevate:impersonation"

#: Pinned on encode AND decode — see the module docstring on algorithm confusion.
GRANT_ALGORITHM: Final = "HS256"

#: FIFTEEN MINUTES, and the number is argued rather than copied.
#:
#: The usual reason to push an access token down to five is to bound how long a
#: revocation takes to bite. That reason does not apply here: revocation is already
#: instant (module docstring), because the grant is not a credential. What the TTL
#: actually bounds is how long a *leaked* grant remains pairable with a still-valid
#: admin session — a much narrower window, since an attacker holding an admin session
#: can simply mint their own.
#:
#: So the number is chosen against the other cost: every re-mint writes an
#: `admin.impersonation_started` row into an INSERT-ONLY table (hard rule 4). The
#: console re-mints silently one minute before expiry, so a fifteen-minute life is at
#: most FOUR start rows per hour per (operator, tenant) — the same order as the <=60
#: read rows the coalescing window already allows, and a readable heartbeat rather than
#: a flood. At five minutes it would be twelve an hour and the ledger's most common row
#: would be bookkeeping.
GRANT_TTL: Final = timedelta(minutes=15)

# RFC 7518 §3.2: an HS256 key should be at least the hash output size. PyJWT warns
# below this; this module refuses, for the reason given in `_signing_secret`.
_MIN_SECRET_BYTES = 32

#: Tolerance for clock skew between API replicas. Small on purpose: both the minting and
#: the verifying process are ours, so this covers NTP drift, not a third party's clock.
#: (`CLERK_LEEWAY_S` is 30 because the other end of that comparison is Clerk's clock.)
GRANT_CLOCK_SKEW_S: Final = 5

#: RFC 8693 §4.1. A JSON object whose members identify the actor; we carry only `sub`.
ACTOR_CLAIM: Final = "act"

_REQUIRED_CLAIMS: Final = ("exp", "iat", "jti", "sub", "aud")


@dataclass(frozen=True, slots=True)
class ImpersonationGrant:
    """A verified grant. Ids and an instant only — nothing here is PII (hard rule 6)."""

    grant_id: UUID
    tenant_id: UUID
    admin_id: UUID
    expires_at: datetime


def _signing_key() -> bytes:
    """The HMAC key, or a refusal.

    A DEDICATED secret rather than a subkey derived from `audit_chain_secret`, and the
    reason is rotation rather than cryptography: rotating the audit chain secret "starts
    a new chain, so it is rotated with a drill" (`calevate_shared.config`). Deriving this
    key from it would couple a routine credential rotation — which costs at most fifteen
    minutes of re-minting — to that drill, and coupled rotations are the ones that never
    happen.

    IT FAILS CLOSED OUTSIDE LOCAL. `audit_chain_secret` falls back to a derived constant
    in any environment, which is defensible for tamper-EVIDENCE (a known key makes the
    chain unverifiable, not forgeable-into-authority). It is not defensible for a token
    that authorises reading a client's leads and transcripts: a staging or production
    deploy that forgot the variable would be handing out grants anybody could forge. So
    the local convenience is scoped to `local`, and everywhere else an absent secret is
    an outage — a loud one, matching `_jwk_client`'s answer to an absent Clerk secret,
    which is the same class of failure and already has a shape in this repo.
    `runtime_config_missing_keys` reports it at `/healthz/ready` before an operator
    finds out by clicking.
    """
    settings = get_settings()
    secret = settings.impersonation_grant_secret
    if secret:
        # LENGTH IS PART OF BEING CONFIGURED, not a warning to read later. RFC 7518 §3.2
        # requires an HMAC key at least the size of the hash output — 32 bytes for
        # HS256 — and PyJWT only WARNS below it. Failing closed on a MISSING secret while
        # silently accepting a present-but-weak one would leave the refusal below
        # guarding the easier half of the same mistake: an operator who pastes a short
        # string into the secrets manager gets a signing key an attacker can search,
        # and the only signal is a log line nobody reads. Refused with the same shape as
        # absence, because to this module they are the same condition.
        if len(secret.encode()) < _MIN_SECRET_BYTES:
            log.error(
                "impersonation_grant_secret_too_short",
                extra={"app_env": settings.app_env, "bytes": len(secret.encode())},
            )
            raise ProblemError(
                kind="dependency",
                code="impersonation_not_configured",
                title="View-as is not configured",
                detail="This deployment's signing key for view-as sessions is too short.",
                remediation=(
                    f"IMPERSONATION_GRANT_SECRET must be at least {_MIN_SECRET_BYTES} "
                    "bytes (RFC 7518 §3.2 for HS256); inject a longer one from the "
                    "secrets manager (DEV-SETUP §4)."
                ),
            )
        return secret.encode()
    if settings.app_env != "local":
        log.error("impersonation_grant_secret_missing", extra={"app_env": settings.app_env})
        raise ProblemError(
            kind="dependency",
            code="impersonation_not_configured",
            title="View-as is not configured",
            detail="This deployment has no signing key for view-as sessions.",
            remediation=(
                "Inject IMPERSONATION_GRANT_SECRET from the secrets manager (DEV-SETUP §4)."
            ),
        )
    # >=32 bytes: PyJWT warns (RFC 7518 §3.2) below the HMAC-SHA256 key size, and a
    # warning every local request trains people to ignore warnings.
    return f"calevate-local-dev-impersonation-grant-key:{settings.app_env}".encode()


def mint_grant(*, tenant_id: UUID, admin_id: UUID) -> tuple[str, ImpersonationGrant]:
    """One grant, for one operator, into one tenant. Returns (wire form, what it says).

    The caller writes `admin.impersonation_started` from the returned grant, in its own
    transaction, so the row and the credential come into existence together.
    """
    issued_at = datetime.now(UTC)
    # Floored to whole seconds so `expires_at` on the wire is exactly the `exp` the
    # verifier will enforce. A response promising a moment the token does not honour is
    # how a console ends up re-minting one second too late.
    expires_epoch = int((issued_at + GRANT_TTL).timestamp())
    grant_id = uuid7()
    claims: dict[str, Any] = {
        "aud": GRANT_AUDIENCE,
        "sub": str(tenant_id),
        ACTOR_CLAIM: {"sub": str(admin_id)},
        "jti": str(grant_id),
        "iat": int(issued_at.timestamp()),
        "exp": expires_epoch,
    }
    token = jwt.encode(claims, _signing_key(), algorithm=GRANT_ALGORITHM)
    return token, ImpersonationGrant(
        grant_id=grant_id,
        tenant_id=tenant_id,
        admin_id=admin_id,
        expires_at=datetime.fromtimestamp(expires_epoch, UTC),
    )


def _refuse(code: str, title: str, detail: str, remediation: str) -> ProblemError:
    """Every refusal below is a 403 with its own machine code.

    The codes are distinguishable ON PURPOSE, against the usual "don't build an oracle"
    instinct, because the caller here is an authenticated operator who already holds
    `admin:impersonate` and already knows their own id and which tenant they asked for —
    there is nothing left for these to disclose. What the distinction buys is that the
    console can re-mint silently on `..._expired` and must NOT on `..._tenant_mismatch`,
    which is a version skew or a bug and has to be visible.
    """
    return ProblemError(
        kind="permission",
        code=code,
        title=title,
        detail=detail,
        remediation=remediation,
    )


def verify_grant(raw: str | None, *, admin_id: UUID, tenant_id: UUID) -> ImpersonationGrant:
    """Accept this grant for THIS operator entering THIS tenant, or refuse.

    ONE function does all five checks — presence, signature/shape, expiry, actor, subject
    — because a two-call API ("decode it, then remember to check the tenant") is one
    forgotten line away from being the vulnerability it was written to prevent. There is
    no way to obtain an `ImpersonationGrant` that has not been matched against the tenant
    the request named.

    Fails closed in every direction: absent, malformed, wrong signature, wrong audience,
    expired, another operator's, or another tenant's are all refusals. None of them
    degrades to a plain admin session and none of them widens one.
    """
    if not raw:
        raise _refuse(
            "impersonation_grant_required",
            "View-as session not started",
            "Viewing a client account needs a view-as grant, and this request carried none.",
            "Start the view-as session again from the client's page in the operator console.",
        )
    try:
        claims: dict[str, Any] = jwt.decode(
            raw,
            _signing_key(),
            algorithms=[GRANT_ALGORITHM],
            audience=GRANT_AUDIENCE,
            leeway=GRANT_CLOCK_SKEW_S,
            options={"require": list(_REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError as exc:
        # Its own code, because it is the one refusal with a silent remedy: the console
        # re-mints and retries rather than showing the operator anything.
        raise _refuse(
            "impersonation_grant_expired",
            "View-as session expired",
            "This view-as grant has expired.",
            "Reopen the client's page in the operator console to start a new session.",
        ) from exc
    except jwt.PyJWTError as exc:
        # `PyJWTError`, not `InvalidTokenError`, for the reason `verify_token` records:
        # some PyJWT failures are siblings of InvalidTokenError rather than subclasses,
        # and one escaping here would be a 500 on an authorization path.
        log.warning("impersonation_grant_rejected", extra={"reason": type(exc).__name__})
        raise _refuse(
            "impersonation_grant_invalid",
            "View-as grant is not valid",
            "This view-as grant could not be verified.",
            "Reopen the client's page in the operator console to start a new session.",
        ) from exc

    actor = claims.get(ACTOR_CLAIM)
    actor_sub = actor.get("sub") if isinstance(actor, dict) else None
    grant_admin = _as_uuid(actor_sub)
    grant_tenant = _as_uuid(claims.get("sub"))
    grant_id = _as_uuid(claims.get("jti"))
    if grant_admin is None or grant_tenant is None or grant_id is None:
        # A correctly signed token with claims we cannot read is still a refusal: the
        # only way to produce one is with our key, so this is a bug on our side, and
        # answering "valid" would be reading "unknown" as "authorised".
        log.error("impersonation_grant_malformed")
        raise _refuse(
            "impersonation_grant_invalid",
            "View-as grant is not valid",
            "This view-as grant could not be verified.",
            "Reopen the client's page in the operator console to start a new session.",
        )

    if grant_admin != admin_id:
        # A grant is one OPERATOR's. Without this, a grant leaked out of one operator's
        # browser would let a second admin enter a tenant with no start row naming them.
        raise _refuse(
            "impersonation_grant_actor_mismatch",
            "View-as grant belongs to another operator",
            "This view-as grant was issued to a different operator.",
            "Open the client's page in your own operator console to start a session.",
        )
    if grant_tenant != tenant_id:
        # THE REPLAY THIS DESIGN EXISTS TO PREVENT: a grant minted for one client,
        # presented against another. Without it the grant is strictly worse than the
        # bare header it replaces, because it would carry an air of authorisation.
        log.warning("impersonation_grant_tenant_mismatch", extra={"grant_id": str(grant_id)})
        raise _refuse(
            "impersonation_grant_tenant_mismatch",
            "View-as grant is for a different account",
            "This view-as grant does not authorise the account this request names.",
            "Start a view-as session on the account you want to look at.",
        )

    return ImpersonationGrant(
        grant_id=grant_id,
        tenant_id=grant_tenant,
        admin_id=grant_admin,
        expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
    )


def _as_uuid(value: object) -> UUID | None:
    """A claim we wrote as a uuid string, back as a UUID — or None if it is not one."""
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


__all__ = [
    "ACTOR_CLAIM",
    "GRANT_ALGORITHM",
    "GRANT_AUDIENCE",
    "GRANT_CLOCK_SKEW_S",
    "GRANT_TTL",
    "ImpersonationGrant",
    "mint_grant",
    "verify_grant",
]
