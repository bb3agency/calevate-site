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
  - `auth_time` = when the operator proved the second factor this view-as session rests
             on (D-210). INHERITED by every renewal rather than restamped, which is what
             bounds the whole chain at `VIEW_AS_MAX_AGE` with no server-side table. See
             `AUTH_TIME_CLAIM` and `renewable_grant`.

RENEWAL IS NOT DELEGATION CHAINING, and the two must not be confused because this file
refuses one and performs the other. Nested `act` — an impersonating session minting a
grant of its own — is refused at the route and always will be: that would be a second
actor in a trail D-22 requires to name exactly one. A RENEWAL re-issues the SAME single
hop to the SAME operator for the SAME tenant with the SAME `auth_time`; nothing about who
is acting on whose behalf changes, only `jti` and `exp`. AWS STS draws the same line and
caps the same way — a chained role session is limited to one hour and cannot be extended
past it (`VIEW_AS_MAX_AGE`).

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
registered claims with agreed semantics, PyJWT is already a dependency — it verified
Clerk's tokens next door until D-177 removed them, and it stays for THIS, which is the
only signed token this product still mints — and it enforces expiry and audience for us. A bespoke
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
from apps.api.core.settings import get_settings, resolve_hmac_key
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

#: Tolerance for clock skew between API replicas. Small on purpose: both the minting and
#: the verifying process are ours, so this covers NTP drift, not a third party's clock.
#: (`CLERK_LEEWAY_S` is 30 because the other end of that comparison is Clerk's clock.)
GRANT_CLOCK_SKEW_S: Final = 5

#: RFC 8693 §4.1. A JSON object whose members identify the actor; we carry only `sub`.
ACTOR_CLAIM: Final = "act"

#: OIDC Core 1.0 §2: "Time when the End-User authentication occurred", seconds since the
#: epoch. Borrowed for the same reason `act` and `aud` were — it is a registered claim
#: whose meaning a reviewer already knows, and inventing `stepped_up_at` would be a
#: private spelling of a public idea.
#:
#: Here it carries the instant the operator PROVED A SECOND FACTOR for this view-as
#: session, and it is what makes `VIEW_AS_MAX_AGE` enforceable without a table: a renewed
#: grant inherits its predecessor's value rather than restarting the clock, so no chain of
#: renewals can outlive the one step-up that started it.
AUTH_TIME_CLAIM: Final = "auth_time"

#: ONE HOUR — how long a view-as session may be extended on the strength of a single
#: step-up (D-210), after which the operator proves a factor again.
#:
#: THE ALTERNATIVE THIS REPLACES, stated because it is the obvious one: demand a fresh
#: second factor on EVERY mint. `REAUTH_MAX_AGE` is 5 minutes and `GRANT_TTL` is 15, so
#: every mint after the first would fall outside the freshness window and an operator
#: would answer an emailed code roughly every fourteen minutes to stay inside one client's
#: account. `authn/stepup.py` records this repo's own name for that failure — "a control
#: that gets switched off" — and a read-only support session is exactly the workflow it
#: would be switched off for.
#:
#: The shape used instead is the one the industry converged on for "assume authority into
#: another account's data": AWS STS `AssumeRole` takes the MFA code ONCE and returns a
#: session credential with its own bounded life (one hour by default, and — the detail
#: that matters here — a CHAINED role session is capped at one hour and cannot be extended
#: past it). So a factor at the door, a bounded session behind it, and a hard ceiling on
#: the chain. One hour is that ceiling, and it sits below the admin realm's own 8-hour
#: absolute bound, so this is never the loosest clock in the request.
#:
#: The effective ceiling is one hour PLUS `GRANT_TTL`: the last grant a chain may mint is
#: issued just inside the hour and then lives out its fifteen minutes. Capping `exp` at
#: `auth_time + VIEW_AS_MAX_AGE` instead would make the boundary exact and would make the
#: final grant arbitrarily short-lived, which the console reads as "stale, re-mint" — a
#: mint loop against an INSERT-ONLY ledger (hard rule 4). A stated 75-minute ceiling beats
#: an exact 60-minute one bought with a write amplifier.
VIEW_AS_MAX_AGE: Final = timedelta(hours=1)

_REQUIRED_CLAIMS: Final = ("exp", "iat", "jti", "sub", "aud", AUTH_TIME_CLAIM)


@dataclass(frozen=True, slots=True)
class ImpersonationGrant:
    """A verified grant. Ids and instants only — nothing here is PII (hard rule 6)."""

    grant_id: UUID
    tenant_id: UUID
    admin_id: UUID
    expires_at: datetime
    #: When the operator last proved a second factor for THIS view-as session. Inherited
    #: by every renewal, so it dates the chain rather than the link. See `AUTH_TIME_CLAIM`.
    auth_time: datetime


def _signing_key() -> bytes:
    """The HMAC key, or a refusal.

    A DEDICATED secret rather than a subkey derived from `audit_chain_secret`, and the
    reason is rotation rather than cryptography: the two keys have unrelated rotation
    triggers and unrelated costs. Rotating this one costs at most fifteen minutes of
    re-minting; rotating the audit chain's means carrying the outgoing value in
    `AUDIT_CHAIN_SECRET_RETIRED` so history keeps verifying. Deriving one from the other
    would couple both to whichever moved, and coupled rotations are the ones that never
    happen. (This is also NIST SP 800-57 Part 1's key-separation rule — one key, one
    purpose — arriving at the same answer from the other direction.)

    IT FAILS CLOSED OUTSIDE LOCAL. `audit_chain_secret` USED TO fall back to a derived
    constant in any environment, which was defensible for tamper-EVIDENCE (a known key
    makes the chain unverifiable, not forgeable-into-authority) but never for a token
    that authorises reading a client's leads and transcripts: a staging or production
    deploy that forgot the variable would be handing out grants anybody could forge. So
    the local convenience is scoped to `local`, and everywhere else an absent secret is
    an outage — a loud one, matching `_jwk_client`'s answer to an absent Clerk secret,
    which is the same class of failure and already has a shape in this repo. That
    asymmetry is now gone in the other direction too: `compliance/audit.py` refuses an
    absent chain secret on the same terms, so this module's stance is the house style
    rather than the exception it was when it was written.
    `runtime_config_missing_keys` reports it at `/healthz/ready` before an operator
    finds out by clicking.

    THE LADDER ITSELF NOW LIVES IN `core/settings.py::resolve_hmac_key`, because the
    policy this module reasoned out first — configured, too short, absent; local
    fallback scoped to `local`; a weak key refused with the same code as no key — is the
    policy all three of this deployment's HMAC secrets need, and three copies is where
    the fourth one gets it wrong. What stays here is the part that is about THIS key: it
    is dedicated (above), and the local constant is >=32 bytes because PyJWT warns below
    the HMAC-SHA256 key size and a warning on every local request trains people to
    ignore warnings.
    """
    settings = get_settings()
    return resolve_hmac_key(
        settings.impersonation_grant_secret,
        env_var="IMPERSONATION_GRANT_SECRET",
        purpose="D-22 view-as grants",
        code="impersonation_not_configured",
        title="View-as is not configured",
        local_fallback=f"calevate-local-dev-impersonation-grant-key:{settings.app_env}",
        app_env=settings.app_env,
    )


def mint_grant(
    *, tenant_id: UUID, admin_id: UUID, auth_time: datetime
) -> tuple[str, ImpersonationGrant]:
    """One grant, for one operator, into one tenant. Returns (wire form, what it says).

    The caller writes `admin.impersonation_started` from the returned grant, in its own
    transaction, so the row and the credential come into existence together.

    `auth_time` is when the operator proved the second factor this view-as session rests
    on — the step-up instant on a cold start, the PREDECESSOR'S value on a renewal. It is
    a required argument rather than a defaulted one precisely so that "now" cannot be
    reached for by accident: a renewal that restarted the clock would turn
    `VIEW_AS_MAX_AGE` into no bound at all, and a default would make that a typo away.
    """
    issued_at = datetime.now(UTC)
    # Floored to whole seconds so `expires_at` on the wire is exactly the `exp` the
    # verifier will enforce. A response promising a moment the token does not honour is
    # how a console ends up re-minting one second too late.
    expires_epoch = int((issued_at + GRANT_TTL).timestamp())
    auth_time_epoch = int(auth_time.timestamp())
    grant_id = uuid7()
    claims: dict[str, Any] = {
        "aud": GRANT_AUDIENCE,
        "sub": str(tenant_id),
        ACTOR_CLAIM: {"sub": str(admin_id)},
        "jti": str(grant_id),
        "iat": int(issued_at.timestamp()),
        "exp": expires_epoch,
        AUTH_TIME_CLAIM: auth_time_epoch,
    }
    token = jwt.encode(claims, _signing_key(), algorithm=GRANT_ALGORITHM)
    return token, ImpersonationGrant(
        grant_id=grant_id,
        tenant_id=tenant_id,
        admin_id=admin_id,
        expires_at=datetime.fromtimestamp(expires_epoch, UTC),
        auth_time=datetime.fromtimestamp(auth_time_epoch, UTC),
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
    # PyJWT's `require` proves the claim is PRESENT, never that it is a number. A grant
    # whose `auth_time` we cannot read is one whose `VIEW_AS_MAX_AGE` we cannot enforce,
    # so it joins the malformed branch below rather than being defaulted to anything.
    auth_time = _as_instant(claims.get(AUTH_TIME_CLAIM))
    if grant_admin is None or grant_tenant is None or grant_id is None or auth_time is None:
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
        auth_time=auth_time,
    )


def renewable_grant(
    raw: str | None, *, admin_id: UUID, tenant_id: UUID, now: datetime | None = None
) -> ImpersonationGrant | None:
    """The live grant a new mint may CONTINUE, or `None` if there is nothing to continue.

    D-210. A view-as session starts with a step-up and is then extended by presenting the
    grant it already holds, up to `VIEW_AS_MAX_AGE` from the step-up that started it. This
    is the "may it be extended?" question, and it is deliberately TOTAL: every way of
    failing returns `None`, which sends the caller to the STRICTER path (prove a factor).

    ═══ WHY SWALLOWING `verify_grant`'S REFUSALS IS SAFE HERE, AND ONLY HERE ═══

    Everywhere else those refusals are the answer — `core/auth.py` turns them into the 403
    that keeps an operator out of a tenant, and their distinguishable codes exist so the
    console can tell "re-mint silently" from "this is a bug". Here they are a QUESTION
    about an optional extra credential, asked before the gate rather than instead of it,
    and the answer `None` grants nothing: it costs the caller an emailed code. There is no
    input to this function that can make it return a grant `verify_grant` would refuse, so
    it cannot widen anything; the worst a malformed `renew` can do is make its sender
    prove a second factor they would otherwise have skipped.

    The bound is on `auth_time`, not on `iat`: `iat` is the age of the LINK and would let
    a chain run forever fifteen minutes at a time. See `AUTH_TIME_CLAIM`.

    WHAT RENEWAL COSTS, STATED PLAINLY: an attacker holding BOTH a live admin cookie and a
    live grant can extend without answering a code, up to `VIEW_AS_MAX_AGE`. That is not a
    new capability — the grant they hold already opens the tenant for the rest of its own
    TTL, and both travel on the same requests, so anything that has one has the other.
    What renewal removes is the second factor at the 15-minute boundary; what it does NOT
    remove is the one at the hour, or the one that stopped a cookie-only attacker at the
    door, which is the case a stolen session actually is.
    """
    if not raw:
        return None
    try:
        grant = verify_grant(raw, admin_id=admin_id, tenant_id=tenant_id)
    except ProblemError:
        # Absent, forged, expired, another operator's or another tenant's — see above.
        # Logged at debug nowhere: `verify_grant` already logs the cases worth an
        # operator's attention, and a second line per ordinary expiry would be noise.
        return None
    if (now or datetime.now(UTC)) - grant.auth_time > VIEW_AS_MAX_AGE:
        # The chain has run its hour. The grant itself is still valid for whatever is left
        # of its own TTL — reads keep working while the operator answers the code — but it
        # buys no further extension.
        log.info("impersonation_view_as_window_elapsed", extra={"grant_id": str(grant.grant_id)})
        return None
    return grant


def _as_instant(value: object) -> datetime | None:
    """A NumericDate claim as a timezone-aware instant, or `None` if it is not one.

    `bool` is excluded explicitly because it is an `int` in Python, and `auth_time: true`
    would otherwise decode to the epoch — an instant so old the window check would refuse
    it, which is the right answer arrived at for the wrong reason and only by luck.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None


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
    "AUTH_TIME_CLAIM",
    "GRANT_ALGORITHM",
    "GRANT_AUDIENCE",
    "GRANT_CLOCK_SKEW_S",
    "GRANT_TTL",
    "VIEW_AS_MAX_AGE",
    "ImpersonationGrant",
    "mint_grant",
    "renewable_grant",
    "verify_grant",
]
