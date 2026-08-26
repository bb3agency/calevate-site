"""Self-serve signup — a business creating its own tenant (D-34 motion 2, FLOWS §2).

D-34 is explicit that the two motions share one product: **a self-serve org is the
same `organizations` row as a managed one**, told apart by `plan_tier`. So this module
does not build a tenant — `admin/service.py::create_organization` already does that
atomically (org + retention policies + agent with a non-null disclosure line +
extraction schema), and a second implementation would be a second thing to keep in
step with SEC-COMP §1. What is different is only the CALLER:

- **Who.** FLOWS §2 step 1: an account exists first, and THEN the org-create step runs.
  So the caller is a verified client-realm identity with no membership yet
  (`core.auth.current_identity`), and the membership is what this call creates. (The brief
  for this work described the endpoint as unauthenticated; FLOWS §2 says otherwise and the
  docs win. It also matters practically — an owner membership needs a user to point at.)
  **WHAT D-177 COST HERE, stated rather than left to be discovered:** the account used to
  be minted by Clerk, whose bot mitigation and email verification were free abuse control
  on the way in. First-party signup has neither yet — AUTH-MIGRATION §1 C-23/C-24 carry
  that as accepted risk, and `assert_signup_quota` below is what stands in for it
  meanwhile.
- **What tier.** `self_serve` or `trial`, never `managed`: the managed tier is the one
  with no wallet gate in front of it (compliance/service.py §2b), so it is not
  self-assignable.
- **Who checks the name.** There is no operator in this flow. Reserved slugs and slug
  collisions are enforced server-side, by the same `assert_slug_available` the wizard
  uses — the slug is immutable once set (a DB trigger enforces it), so this is the one
  chance to get it right.
- **How much of it anyone may do.** An endpoint that creates tenants is a
  resource-exhaustion surface: each signup writes an org, an agent, a schema and
  several retention policies, and a script can call it in a loop. `assert_signup_quota`
  is the control — literally `core/ratelimit.py::consume`, the one fixed-window counter
  every limit in this platform shares, at a limit that suits tenant creation rather than
  page loads. It differs from the request limiter in ONE respect, passed as
  `fail_open=False` rather than reimplemented: it fails **closed**. That limiter fails
  open because a
  Redis blip must not 500 the whole API; here Redis is the only thing standing between
  an unattended endpoint and unlimited tenants, so losing it means the endpoint is
  unavailable, not unguarded.

**What a fresh self-serve tenant CANNOT do**, so nobody reads this as a dialer being
handed out (R-11): its agent is a `draft`, it has no number, and its wallet is empty —
and the compliance gate already refuses a self-serve tenant with an exhausted wallet.
Calling requires a verified business (`compliance/kyc.py`, refused at dial time as
`kyc_missing`) and, for the account's first campaign, a human release
(`compliance/first_campaign.py`, refused at launch and at every dispatch tick as
`first_campaign_review_pending`). Neither is anything this module can grant, and both
are now controls rather than sentences — the hold in particular is a property of the
ACCOUNT, so a new tenant cannot reach it by launching a second campaign or by deleting
the first.

ONE TRANSACTION (the gap that used to be here). This module once let
`create_organization` commit the tenant root and then wrote the tier and the owner
membership in a SECOND transaction, soft-deleting the org if that failed.
`create_organization` now takes `plan_tier` and `owner_user_id` and writes them in the
same transaction as the org, and `on_created` puts the audit row there too — so there
is no half-built state to compensate for, and no compensation that can itself fail.
The slug a failed attempt asked for is free again for the retry rather than held
forever by a soft-deleted shell.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.authn.subjects import load_subject
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.ratelimit import LimitProfile, bucket_subject, consume
from apps.api.core.settings import get_settings

log = get_logger(__name__)

SelfServeTier = Literal["self_serve", "trial"]

# The quota. Fixed windows, because the middleware's limiter is a fixed window and one
# mechanism in a codebase beats two that behave subtly differently under load.
#
# Per identity: a real business creates one tenant. Five an hour leaves room for a
# fumbled slug and a retry; a hundred does not look like a business at all.
# Per address: the per-identity window is defeated by making more accounts, which
# is the cheap half of the attack — this is the other half. Loose enough that an office
# behind one NAT can onboard several sites in an afternoon.
SIGNUPS_PER_USER_PER_HOUR: int = 5
SIGNUPS_PER_IP_PER_HOUR: int = 30
QUOTA_WINDOW_S: Final = 3600


#: Bidirectional FORMATTING controls, which are the half of Unicode category `Cf` that
#: has no business in a business name. U+202A-U+202E are the legacy embedding/override
#: set and U+2066-U+2069 are the isolates; U+200E/U+200F are the directional marks.
#: `U+202E RIGHT-TO-LEFT OVERRIDE` in a stored name renders the rest of the string
#: backwards in every console, every invoice and every email that shows it, which is a
#: spoofing primitive rather than a typo.
#:
#: **THE REST OF `Cf` IS DELIBERATELY ALLOWED, AND THAT IS THE WHOLE POINT OF NAMING
#: THESE EIGHT INSTEAD OF THE CATEGORY.** `U+200C ZERO WIDTH NON-JOINER` and `U+200D ZERO
#: WIDTH JOINER` are also `Cf`, and on a Telugu-first product (D-36) they are ORDINARY
#: LETTERS' WORK: they are what controls conjunct formation in Telugu and Devanagari, so
#: a category-wide refusal would reject correctly-spelled Indic business names while
#: passing every ASCII one. That is the failure mode this repo has already met once, in
#: `admin_service.slugify` — a rule written against ASCII that turns the default case on
#: this product into the error case.
_BIDI_CONTROLS: Final = frozenset(
    "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def clean_business_name(raw: str) -> str:
    """The business name as it will be STORED, or an actionable refusal.

    `Field(min_length=2, max_length=120)` was the only thing in front of
    `organizations.name` and it let three shapes through, each measured against the live
    endpoint before this function existed:

      * **A NUL byte produced a 500.** `"Ab\x00cd"` satisfies `min_length` and reaches
        psycopg, which raises `DataError: PostgreSQL text fields cannot contain NUL
        (0x00) bytes` — an unhandled driver exception on the one route whose whole job is
        to be reachable by a stranger. Not a security hole, but it is a 500 where the
        RFC-9457 contract promises a refusal, and "errors are part of the interface".
      * **`"   "` created a workspace named `"   "`** (201, no complaint): three spaces
        satisfy `min_length=2`, and the tenant is then unnameable in every list it appears
        in. The slug derivation does not catch it, because a caller who supplies their own
        slug never reaches the derivation.
      * **Control characters and bidi overrides were stored verbatim.** A name containing
        `\r\n` breaks any line-oriented rendering of it; `U+202E` reverses everything
        after it on screen.

    So the name is normalized (NFC, the same form `authn/policy.py` argues for and for the
    same reason — one visual name should be one stored string), stripped of the characters
    that are not text, whitespace-collapsed, and then measured. The LENGTH IS RE-CHECKED
    AFTER CLEANING, which is the point of returning a value rather than validating in
    place: `min_length` on the raw string is a bound on what was typed, and what matters
    is what is left.

    ⚠ THE ADMIN WIZARD DOES NOT USE THIS YET. `admin/service.create_organization` takes
    `name` straight from `admin/routes.py`, which has the identical `Field` bound and the
    identical three holes. That path is operator-only, so a stranger cannot reach it — but
    it is the same defect and it wants the same call, at `admin/routes.py`'s intake model.
    It is not done here only because another change is in flight in those files.
    """
    name = " ".join(
        "".join(
            ch
            for ch in unicodedata.normalize("NFC", raw)
            # `Cc` is the C0/C1 controls, NUL and CR/LF among them. `Cs` (surrogates) and
            # `Co` (private use) are not text either. Whitespace survives this because
            # SPACE and TAB are `Zs`/`Cc`-adjacent — TAB is `Cc` and is deliberately
            # dropped, which is correct: the join below would have collapsed it anyway.
            if ch not in _BIDI_CONTROLS and unicodedata.category(ch) not in ("Cc", "Cs", "Co")
        ).split()
    )
    if 2 <= len(name) <= 120:
        return name
    raise ProblemError(
        kind="validation",
        code="invalid_business_name",
        title="Check the business name",
        detail=(
            "A business name is 2 to 120 characters once spacing is tidied up, and cannot "
            "be made only of spaces or invisible characters."
        ),
        fields=[
            {
                "field": "business_name",
                "rule": "length",
                "message": "2-120 characters of ordinary text",
            }
        ],
        remediation="Enter the name your callers know you as.",
    )


def derive_slug(name: str) -> str:
    """The slug we offer when the caller does not pick one. Deliberately the wizard's
    own derivation, so a business gets the same URL — and, when the name yields no ASCII
    at all, the same actionable refusal — whichever motion it arrives through.

    A delegate rather than a re-export, because the two motions genuinely could diverge
    (this one has no operator to catch a bad answer) and the seam is where that argument
    would live. It has not diverged; see `admin_service.derive_slug`.
    """
    return admin_service.derive_slug(name)


async def assert_email_verified(user_id: UUID) -> None:
    """A tenant is not created for a mailbox nobody has proved.

    ═══ WHY THIS WAS MISSING, AND WHY IT IS THE CONTROL THIS MODULE ASKED FOR ═══

    The module docstring above already names the hole in its own words: Clerk's "bot
    mitigation and email verification were free abuse control on the way in. First-party
    signup has neither yet — AUTH-MIGRATION §1 C-23/C-24 carry that as accepted risk, and
    `assert_signup_quota` below is what stands in for it meanwhile." A quota is not a
    substitute for proof of a mailbox; it only makes an unattended tenant factory slower.

    Measured against the endpoint before this function existed: a client-realm session
    whose `users.email_verified_at` was NULL created a tenant and got a 201.
    `email_verified_at` was written by exactly one thing (`/otp/verify` →
    `subjects.mark_email_verified`) and READ by exactly two — `SessionOut.email_verified`,
    which only reports it, and `invitations.py:213`, which uses it for a different rule.
    It gated nothing. A column that is written, displayed and never enforced is the
    half-wired shape: it looks like a control on the screen and is not one.

    **THIS IS REACHABLE, NOT A LOCKOUT, AND THAT IS LOAD-BEARING.** D-185 deliberately
    does NOT set `email_verified_at` when an invitation is redeemed — possession of a
    forwarded link is not proof of the mailbox — so a brand-new account genuinely arrives
    here unverified. What clears it is `POST /v1/auth/client/otp/request` +
    `/otp/verify`, which is built, mounted, mailed and already has its own page at
    `/auth/account` (D-174). So the refusal below names a door that exists; the signup
    page renders it as a step rather than as an error.

    **WHY THE TENANT AND NOT THE SESSION.** The gate could have been put on
    `current_identity`, refusing every unverified client request. It is not, because that
    would break the one flow that must work for an unverified account — reaching
    `/auth/account` to verify — and because the thing worth protecting is not "reading a
    console" but "manufacturing a tenant", which writes an org, an agent, a schema and
    several retention policies per call and is the resource-exhaustion surface
    `assert_signup_quota` exists for. Verification is the control that makes the quota
    mean something: it costs an attacker a deliverable mailbox per five tenants an hour
    instead of nothing at all.

    A subject that has vanished between the session check and this read is refused the
    same way. `current_identity` already proved they were live a moment ago, so this is
    not the liveness check — it is only that `load_subject` has no other answer, and
    "verify your address" is a safe thing to tell someone whose account just went away.
    """
    subject = await load_subject("client", user_id)
    if subject is not None and subject.email_verified_at is not None:
        return
    log.info("signup_refused_unverified_email", extra={"user_id": str(user_id)})
    raise ProblemError(
        kind="business_rule",
        code="email_not_verified",
        title="Confirm your email address first",
        detail=(
            "Your email address has not been confirmed yet, so we cannot create a workspace on it."
        ),
        remediation=(
            "Open your account settings, send yourself a confirmation code, and enter "
            "it. Then come back here."
        ),
    )


async def assert_signup_open() -> None:
    """Two switches, both of which must be on.

    `self_serve_signup_enabled` is R-11's kill switch: self-serve plus Indian telecom
    compliance is the sharp edge of D-34, and turning the intake off must be an
    environment change, not a deploy. Default is OFF — a surface that lets the public
    create tenants should be something someone switched on.

    The platform mode is the second, and the reason recorded here was true when it was
    written and is not now. It said `/v1/auth` was in `ALWAYS_ALLOWED_PREFIXES`
    (loadshed.py) so the middleware could not shed signup and the route had to do it
    itself. That exemption is GONE: nothing under `/v1/auth` mints a session, so it named
    a surface that does not exist and its only effect was to keep this endpoint
    manufacturing tenants during an incident. `LoadShedMiddleware` now refuses
    `POST /v1/auth/signup` in every non-normal mode — the same condition as the branch
    below — and `tests/loadshed_exemption_test.py::test_signup_is_shed_like_any_other_
    expensive_write` is what keeps that true.

    The branch below therefore stays for two reasons, neither of which is the old one:
    the refusal NAMES signup (`signup_load_shed`, with a signup-length `Retry-After`),
    which is the code `apps/web/src/lib/api/signup.ts` keys its "come back later" state
    on rather than the generic `service_load_shed`; and this function is also reached
    in-process, where no middleware runs. It is a second refusal of the same condition,
    not a second definition of it — the condition itself is read from
    `get_platform_status`, the one source both layers share.
    """
    if not get_settings().self_serve_signup_enabled:
        raise ProblemError(
            kind="transient",
            code="signup_disabled",
            title="Signup is closed",
            detail="Self-serve signup is not open right now.",
            remediation="Contact us and we will set your account up.",
        )
    status = await get_platform_status()
    if status.mode != "normal":
        raise ProblemError(
            kind="transient",
            code="signup_load_shed",
            title="Temporarily unavailable",
            detail="Calevate is not taking new sign-ups right now. Please try again shortly.",
            remediation="Try again shortly.",
            headers={"Retry-After": "120"},
        )


#: The counter's namespace and window. The MECHANISM is `core/ratelimit.consume` — the
#: same INCR/EXPIRE pair every other limit in the platform uses, with `fail_open=False`
#: as the one difference (see the module docstring). It used to be a second copy of that
#: pair in this file, which is how two limiters end up behaving differently under load.
#: The key is `calevate:rl:signup:{scope}:{subject}:{bucket}` — see `_consume` for why
#: the subject is the identity itself rather than a hash of it.
#:
#: THE EFFECTIVE LIMITS ARE THE TWO CONSTANTS ABOVE, PASSED PER DIMENSION, not this
#: profile's `per_client` — this surface has two different ceilings on one window, and a
#: profile field is read at import while those constants are read per call, which is what
#: lets a test turn one of them down to make the refusal observable.
SIGNUP_QUOTA: Final = LimitProfile(
    "signup",
    per_client=SIGNUPS_PER_IP_PER_HOUR,
    per_tenant=None,
    window_s=QUOTA_WINDOW_S,
)


async def _consume(scope: str, subject: str, limit: int) -> None:
    # BOTH SUBJECTS GO IN AS THEMSELVES. The comment that used to sit here — "identities
    # are hashed before they reach Redis, the limiter needs a stable key, not a directory
    # of who signed up from where" — was a promise the hash could not keep, in two
    # directions. `ratelimit.fingerprint` is an UNKEYED blake2s justified on the grounds
    # that its input is a high-entropy credential; an IPv4 address is a 32-bit space, so
    # hashing one is an encoding of it, not a pseudonym (BACKEND-PATTERNS §4 keys the
    # idempotency fingerprint with an HMAC for exactly this reason, and that argument was
    # not carried across to this caller). And the property it claimed is contradicted one
    # module over: `RateLimitMiddleware` writes `calevate:rl:<profile>:client:ip:<the
    # address itself>` for every request that address makes, while SEC-COMP §5 REQUIRES
    # the same address kept durably in `audit_log.ip`. An hour-long Redis key cannot be
    # the privacy boundary for a value the platform is obliged to retain permanently.
    #
    # One rule replaces the claim: `fingerprint` is for the single input that is a live
    # CREDENTIAL — the bearer token in `RateLimitMiddleware._subjects` — and every other
    # bucket subject goes through `bucket_subject`, which bounds the key space by length
    # and charset (hex output bounded it implicitly, which is the only thing lost here).
    decision = await consume(SIGNUP_QUOTA, scope, bucket_subject(subject), limit, fail_open=False)
    if decision.allowed:
        return
    if decision.reason == "unavailable":
        # FAIL CLOSED — see the module docstring. Everywhere else in this codebase a
        # Redis failure degrades gracefully; on an unattended tenant factory it would
        # degrade into no control at all. 503, not 429: the caller hit no limit, and
        # telling them they did would send them away for an hour over our outage.
        log.warning("signup_quota_unavailable", extra={"scope": scope})
        raise ProblemError(
            kind="transient",
            code="signup_unavailable",
            title="Temporarily unavailable",
            detail="Signup cannot be processed right now.",
            remediation="Try again in a few minutes.",
            headers={"Retry-After": "60"},
        )
    log.warning("signup_quota_exceeded", extra={"scope": scope})
    raise ProblemError(
        kind="transient",
        code="rate_limited",
        title="Too many requests",
        detail="Too many accounts have been created from here recently.",
        status=429,
        remediation=f"Retry in {decision.retry_after_s}s.",
        headers={"Retry-After": str(decision.retry_after_s)},
    )


async def assert_signup_quota(*, user_id: UUID, ip: str | None) -> None:
    """Consumed on every ATTEMPT, not on every success.

    A caller who burns their window on refused slugs has still made us do the work of
    refusing them, and letting failures be free is what makes a limiter enumerable.
    The window is per hour, so a genuine fumble costs a wait, not an account.

    `ip` IS NOW THE CALLER'S ADDRESS, and that is the whole point of this change. The
    route used to pass the socket peer, which behind Cloudflare + nginx is one shared
    proxy address for the entire internet — so `SIGNUPS_PER_IP_PER_HOUR = 30` was a cap
    on the PLATFORM, not on an abuser, and thirty signups an hour denied self-serve to
    everyone else. It comes from `core/auth.client_request_ip` now.

    `None` — the deployment could not vouch for an address at all — still shares one
    bucket, and that stays fail-closed on purpose: it is only reachable when the edge
    has stopped setting `CF-Connecting-IP`, and in that state we genuinely cannot tell
    two callers apart. The per-identity window above is untouched by it, so a legitimate
    signup is still bounded rather than blocked, and `signup_quota_exceeded` on the `ip`
    scope with `ip_established=false` in the log is the operator's signal.
    """
    await _consume("user", str(user_id), SIGNUPS_PER_USER_PER_HOUR)
    if ip is None:
        log.warning("signup_ip_unresolved")
    await _consume("ip", ip or "unknown", SIGNUPS_PER_IP_PER_HOUR)


async def create_self_serve_tenant(
    *,
    user_id: UUID,
    name: str,
    slug: str,
    vertical_template: str,
    language: str,
    billing_email: str | None,
    plan_tier: SelfServeTier,
    ip: str | None = None,
) -> dict[str, Any]:
    """The tenant, its tier and its owner — in ONE transaction.

    `create_organization` does all of it and is the arbiter of the slug: it probes
    `reserved_slugs` and `organizations` under `admin_session` (RLS would hide every
    other tenant's slug otherwise) and translates the unique-index race back into the
    same 409 the probe would have raised. Nothing here re-implements that.

    A tenant on the self-serve tier with no owner, or an owner on a managed-tier org,
    are both states nothing downstream expects — so neither is reachable: the tier, the
    membership and the audit row are written inside the transaction that creates the
    org, and anything that fails takes the whole tenant with it. There is no
    compensating delete because there is nothing left to compensate for.
    """

    async def _audit(session: AsyncSession, tenant_id: UUID) -> None:
        """The last write of the birth transaction. `audit_log` is not tenant-RLS'd
        (migration 05bba2f3c19c) but it IS the same transaction, so a tenant that
        exists with no record of its creation is not a reachable state."""
        await write_audit(
            session,
            action="organization.self_serve_created",
            actor_type="user",
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=ip,
            summary={"plan_tier": plan_tier, "vertical_template": vertical_template},
        )

    created = await admin_service.create_organization(
        name=name,
        slug=slug,
        vertical_template=vertical_template,
        billing_email=billing_email,
        language=language,
        # The signing-up user, not an operator. `organizations.created_by` carries no
        # FK, and "who made this" is more useful than a null on the one motion where
        # the answer is not "someone in ops".
        created_by=user_id,
        plan_tier=plan_tier,
        owner_user_id=user_id,
        on_created=_audit,
    )

    log.info(
        "self_serve_signup",
        extra={"tenant_id": str(created["id"]), "plan_tier": plan_tier},
    )
    return {**created, "plan_tier": plan_tier, "role": "owner"}


__all__ = [
    "QUOTA_WINDOW_S",
    "SIGNUPS_PER_IP_PER_HOUR",
    "SIGNUPS_PER_USER_PER_HOUR",
    "SIGNUP_QUOTA",
    "SelfServeTier",
    "assert_email_verified",
    "assert_signup_open",
    "assert_signup_quota",
    "clean_business_name",
    "create_self_serve_tenant",
    "derive_slug",
]
