"""Self-serve signup — a business creating its own tenant (D-34 motion 2, FLOWS §2).

D-34 is explicit that the two motions share one product: **a self-serve org is the
same `organizations` row as a managed one**, told apart by `plan_tier`. So this module
does not build a tenant — `admin/service.py::create_organization` already does that
atomically (org + retention policies + agent with a non-null disclosure line +
extraction schema), and a second implementation would be a second thing to keep in
step with SEC-COMP §1. What is different is only the CALLER:

- **Who.** FLOWS §2 step 1: Clerk creates the user, our webhook mirrors it into
  `users`, and THEN the org-create step runs. So the caller is a verified client-realm
  identity with no membership yet — the same state the invitation-accept route handles
  (`core.auth.current_identity`), and for the same reason: the membership is what this
  call creates. (The brief for this work described the endpoint as unauthenticated;
  FLOWS §2 says otherwise and the docs win. It also matters practically — an owner
  membership needs a user to point at, and Clerk's own bot mitigation and email
  verification are the cheapest abuse control we will ever get.)
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
  is the control — a fixed-window Redis counter, the same mechanism and key namespace
  as `core/middleware.py::RateLimitMiddleware`, at a limit that suits tenant creation
  rather than page loads. It differs from the middleware in ONE respect and that
  difference is deliberate: it fails **closed**. The middleware fails open because a
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

import hashlib
import time
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings

log = get_logger(__name__)

SelfServeTier = Literal["self_serve", "trial"]

# The quota. Fixed windows, because the middleware's limiter is a fixed window and one
# mechanism in a codebase beats two that behave subtly differently under load.
#
# Per identity: a real business creates one tenant. Five an hour leaves room for a
# fumbled slug and a retry; a hundred does not look like a business at all.
# Per address: the per-identity window is defeated by making more Clerk accounts, which
# is the cheap half of the attack — this is the other half. Loose enough that an office
# behind one NAT can onboard several sites in an afternoon.
SIGNUPS_PER_USER_PER_HOUR: int = 5
SIGNUPS_PER_IP_PER_HOUR: int = 30
QUOTA_WINDOW_S: Final = 3600


def derive_slug(name: str) -> str:
    """The slug we offer when the caller does not pick one. Deliberately the wizard's
    `slugify`, so a business gets the same URL whichever motion it arrives through."""
    return admin_service.slugify(name)


async def assert_signup_open() -> None:
    """Two switches, both of which must be on.

    `self_serve_signup_enabled` is R-11's kill switch: self-serve plus Indian telecom
    compliance is the sharp edge of D-34, and turning the intake off must be an
    environment change, not a deploy. Default is OFF — a surface that lets the public
    create tenants should be something someone switched on.

    The platform mode is the second: `/v1/auth` is in `ALWAYS_ALLOWED_PREFIXES`
    (loadshed.py), which is right for signing IN and wrong for signing UP — creating a
    tenant is exactly the expensive write `reduced` mode exists to stop. The middleware
    cannot make that distinction by prefix, so the route makes it here.
    """
    if not get_settings().self_serve_signup_enabled:
        raise ProblemError(
            kind="transient",
            code="signup_disabled",
            title="Signup is closed",
            detail="Self-serve signup is not open on this deployment.",
            remediation="Contact us and we will set your account up.",
        )
    status = await get_platform_status()
    if status.mode != "normal":
        raise ProblemError(
            kind="transient",
            code="signup_load_shed",
            title="Temporarily unavailable",
            detail=f"The platform is in {status.mode} mode and is not creating accounts.",
            remediation="Try again shortly.",
            headers={"Retry-After": "120"},
        )


def _fingerprint(subject: str) -> str:
    """Identities are hashed before they reach Redis — the limiter needs a stable key,
    not a directory of who signed up from where."""
    return hashlib.sha256(subject.encode()).hexdigest()[:16]


async def _consume(scope: str, subject: str, limit: int) -> None:
    bucket = int(time.time() // QUOTA_WINDOW_S)
    key = f"calevate:rl:signup:{scope}:{_fingerprint(subject)}:{bucket}"
    try:
        redis = get_redis()
        count = int(await redis.incr(key))
        if count == 1:
            await redis.expire(key, QUOTA_WINDOW_S + 1)
    except Exception as exc:
        # FAIL CLOSED — see the module docstring. Everywhere else in this codebase a
        # Redis failure degrades gracefully; on an unattended tenant factory it would
        # degrade into no control at all.
        log.warning("signup_quota_unavailable", extra={"scope": scope})
        raise ProblemError(
            kind="transient",
            code="signup_unavailable",
            title="Temporarily unavailable",
            detail="Signup cannot be processed right now.",
            remediation="Try again in a few minutes.",
            headers={"Retry-After": "60"},
        ) from exc

    if count > limit:
        retry_after = QUOTA_WINDOW_S - int(time.time() % QUOTA_WINDOW_S)
        log.warning("signup_quota_exceeded", extra={"scope": scope})
        raise ProblemError(
            kind="transient",
            code="rate_limited",
            title="Too many requests",
            detail="Too many accounts have been created from here recently.",
            status=429,
            remediation=f"Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )


async def assert_signup_quota(*, clerk_user_id: str, ip: str | None) -> None:
    """Consumed on every ATTEMPT, not on every success.

    A caller who burns their window on refused slugs has still made us do the work of
    refusing them, and letting failures be free is what makes a limiter enumerable.
    The window is per hour, so a genuine fumble costs a wait, not an account.
    """
    await _consume("user", clerk_user_id, SIGNUPS_PER_USER_PER_HOUR)
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
    "SelfServeTier",
    "assert_signup_open",
    "assert_signup_quota",
    "create_self_serve_tenant",
    "derive_slug",
]
