"""Who a verified Clerk token IS in OUR tables — one resolution, one mirror write.

D-37 keeps Clerk for authentication and keeps **our Postgres as the system of record**:
`users` and `memberships` are ours, and RLS keys off our `tenant_id`. The mirror that
carries a Clerk subject into `users` has always been the Svix webhook
(`tenancy/clerk_webhooks.py`). This module exists because "the webhook has not landed
yet" was being answered as "you are not authenticated", which is neither true nor
survivable for the caller.

## The defect, stated at the instant it happens

`POST /v1/auth/signup` and `POST /v1/invitations/accept` are the only two routes that
accept a verified client-realm identity with NO membership — creating the membership is
what they are for. Both resolved the caller with

    SELECT id FROM users WHERE clerk_user_id = :cid AND deactivated_at IS NULL

and answered `401 "This account is not provisioned."` on zero rows. Zero rows is the
ORDINARY state for the first few hundred milliseconds of a new identity's life: Clerk
mints the session the moment the account exists and redirects the browser straight back
to us, while `user.created` travels to our webhook out of band. So the two moments that
matter most commercially — a founder finishing signup, a colleague accepting an invite —
raced a webhook, and the browser reads 401 as "your session is bad, sign in again".
Signing in again mints another valid token and produces the same 401. There was no exit
and no sentence.

## The decision: RECONCILE FROM CLERK'S BACKEND API, and refuse transiently only if we
## cannot reach it

Clerk's own guidance is explicit, and it is guidance against what we were doing:
"Webhooks are asynchronous and eventually consistent. Delivery is fast but not
guaranteed to be immediate, and may occasionally fail." … "**Do NOT rely on webhook
delivery as part of a synchronous flow such as onboarding** ('user signs up, then we
read X from our DB')." … "For data the user just created, read it from the Clerk session
token or call the Backend API directly. Webhooks fill the gap when you need data about
other users or events the session token doesn't carry."
(github.com/clerk/skills — `skills/features/clerk-webhooks/SKILL.md`, read 2026-08-15;
clerk.com is unreachable from this build host, as `core/auth.py` already records, so the
citation is the copy that could be read directly.)

Two honest designs were on the table and BOTH are implemented, layered, because they
answer different failures.

**(a) Just-in-time reconcile — chosen as the first answer.** The token is
cryptographically verified, so the subject is not in doubt; what is missing is a row we
were always going to write from Clerk's own record of that subject. So we go and get
that record: `GET https://api.clerk.com/v1/users/{id}` with this realm's secret key,
and write it through the SAME upsert the webhook uses.

**BUT NOT FROM THE TOKEN'S CLAIMS**, which is the version of (a) the brief described and
which is refused here. `POST /v1/invitations/accept` binds an invitation to the address
it was sent to by comparing `users.email` (see `tenancy/routes.py::accept_invitation`),
so `users.email` is an AUTHORIZATION INPUT, not a display string. Minting it from an
`email` claim would mean the row that decides who may redeem an invitation is built from
a claim whose verification status the token does not state — an attacker who adds
`victim@example.com` to their own Clerk account, unverified, would mint a mirror row that
satisfies the binding. The Backend API returns the full `email_addresses` array with
`primary_email_address_id`, which is the identical payload the webhook carries, so the
JIT path places EXACTLY the trust in Clerk that the webhook path already places, and no
more. That equivalence is the whole safety argument, and it is why the reconcile and the
webhook share one function (`mirror_clerk_user`) rather than resembling each other.

**(b) Refuse, but transiently and actionably — kept as the fallback.** When the Backend
API cannot be reached, or this deployment has no secret key for the realm, we still must
not say 401. `identity_mirror_pending` is `kind="transient"` (so `retryable: true` on the
wire) with `Retry-After`, and the browser's transport retries it with backoff
(`apps/web/src/lib/api/client.ts`) instead of bouncing to sign-in. Retrying a POST is
safe HERE and only here: this refusal is raised by the auth DEPENDENCY, before any route
handler body runs, so a refused attempt has provably done nothing.

Rejected: **waiting server-side** for the webhook (holding a request open on another
system's delivery schedule is an availability coupling, and the wait would sit inside the
one process a signup surge saturates first); **trusting `org_id`/`org_role` from the
token** (we have no Clerk organizations at all — D-10's tenancy is flat and
`clerk_webhooks.py` deliberately ignores every `organization*` event, so those claims
describe nothing we could act on).

## What this does NOT do

**The admin realm is never reconciled.** `admin_users` is not a Clerk mirror; it is an
ops-managed allowlist, and a missing row there means "this person is not an operator",
which is a permanent and correct 403. Auto-creating one from a verified admin-realm token
would turn "can sign in to the admin Clerk application" into "is an operator", which is
privilege escalation wearing a race condition's clothes. `_load_admin_principal` keeps its
own lookup and is untouched.

**A deactivated account is still a permanent 401.** `mirror_clerk_user` deliberately never
clears `deactivated_at` (see its comment), and `resolve_mirrored_user` checks the column
BEFORE it considers reconciling, so a revoked account cannot be resurrected by arriving
at a route that reconciles.

**Clerk answering 404 is permanent, not transient.** A verified token for a subject Clerk
says does not exist is not a race; retrying cannot fix it, so it is a 401 rather than an
endless 503 loop.

## Idempotency

There is no fourth mechanism (BACKEND-PATTERNS §4). The reconcile's only write is the
webhook's own `ON CONFLICT (clerk_user_id) DO UPDATE` upsert, so the webhook landing
afterwards updates the row we already made rather than making a second one, and two
concurrent reconciles collapse to one row by the unique index. No inbox row is claimed:
the inbox dedupes EVENTS, and a pull is not an event — claiming a key here would invent a
second owner for `svix-id` and could answer a real Clerk retry with "duplicate".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import httpx
from sqlalchemy import text

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

#: Clerk's Backend API. Base URL and the `Authorization: Bearer $CLERK_SECRET_KEY`
#: scheme are from github.com/clerk/skills `skills/core/clerk-backend-api/SKILL.md`
#: (read 2026-08-15). No SDK: it is one authenticated GET, and hard rule 9 makes every
#: added dependency a decision rather than a convenience.
CLERK_API_BASE = "https://api.clerk.com/v1"

#: One reconcile sits in front of a human waiting on a signup form, so the budget is a
#: person's patience, not a batch job's. Past it the transient refusal is the better
#: answer, because the browser retries it and Clerk may have answered by then.
CLERK_REQUEST_TIMEOUT_S = 3.0

#: The stable machine code the frontend switches on. Distinct from `unauthorized` on
#: purpose: that is the whole defect.
MIRROR_PENDING_CODE = "identity_mirror_pending"

#: What we tell the caller to wait. Svix delivery is sub-second in the normal case, so
#: this is "long enough that the retry is not pointless, short enough that a person does
#: not conclude the product is broken".
MIRROR_RETRY_AFTER_S = 2


@dataclass(frozen=True, slots=True)
class ClerkUserLookup:
    """What Clerk said about a subject — and, crucially, whether it SAID anything.

    Three states rather than `dict | None`, because "Clerk says this user does not
    exist" and "we could not ask Clerk" must produce opposite answers to the caller: the
    first is permanent (401, stop), the second is transient (503, retry). Collapsing them
    is how a deleted user gets an infinite retry loop or a network blip gets somebody
    signed out.
    """

    status: Literal["found", "absent", "unavailable"]
    user: dict[str, Any] | None = None


def _mirror_pending() -> ProblemError:
    """The (b) refusal. WHY it happened is in the caller's log line, never in the body.

    503 + `kind="transient"` puts `retryable: true` on the wire, which is what
    `apps/web/src/lib/api/client.ts` and the TanStack Query defaults both read. It also
    means every occurrence fires the alert path (`core/errors.install_error_handlers`),
    and that is wanted rather than tolerated: with the reconcile in front of it, reaching
    this line means the webhook is late AND Clerk's Backend API is unusable, which is an
    outage in the sign-up path and not a race. Alerts are fingerprint-deduped over 15
    minutes (`core/alerting.py`), so a surge is one page, not thousands.
    """
    return ProblemError(
        kind="transient",
        code=MIRROR_PENDING_CODE,
        title="Your account is still being set up",
        detail=(
            "Your sign-in worked, but this account has not finished being created on our side yet."
        ),
        remediation=(
            "Wait a few seconds and try again — this clears by itself. Do not sign out; "
            "signing in again will not make it faster."
        ),
        headers={"Retry-After": str(MIRROR_RETRY_AFTER_S)},
        failure_stage="CORE_LOGIC",
    )


def _primary_email(payload: dict[str, Any]) -> str | None:
    """The address Clerk marks primary, falling back to the first one it lists.

    Clerk's User object and its `user.created` webhook `data` are the same shape — the
    fields read here (`email_addresses`, `primary_email_address_id`, `first_name`,
    `last_name`) are the User-object fields the Backend API documents — which is what
    lets one mirror function consume a push and a pull without translating either.
    """
    emails = payload.get("email_addresses") or []
    if not isinstance(emails, list):
        return None
    primary_id = payload.get("primary_email_address_id")
    entries = [e for e in emails if isinstance(e, dict)]
    chosen = next(
        (e.get("email_address") for e in entries if e.get("id") == primary_id),
        next((e.get("email_address") for e in entries), None),
    )
    return chosen if isinstance(chosen, str) and chosen else None


async def mirror_clerk_user(payload: dict[str, Any], *, deleted: bool) -> str:
    """THE mirror write. Called by the Svix webhook and by the JIT reconcile alike.

    Returns `mirrored` / `deactivated` / `ignored` — the webhook reports it as the
    event's outcome. One function rather than two so the pull path cannot acquire
    different trust rules from the push path (see the module docstring).
    """
    clerk_id = payload.get("id")
    if not isinstance(clerk_id, str) or not clerk_id:
        return "ignored"

    if deleted:
        # Soft: `deactivated_at` is what the auth guard re-checks on every request, so
        # this takes effect on the very next call. A hard delete would orphan
        # memberships and audit rows that must survive (hard rule 4).
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE users SET deactivated_at = now(), updated_at = now() "
                    "WHERE clerk_user_id = :cid AND deactivated_at IS NULL"
                ),
                {"cid": clerk_id},
            )
        return "deactivated"

    email = _primary_email(payload)
    if not email:
        return "ignored"
    name = " ".join(
        part for part in (payload.get("first_name"), payload.get("last_name")) if part
    ).strip()

    async with untenanted_session() as session:
        # `deactivated_at` is deliberately NOT in the SET list. Svix does not guarantee
        # ordering, so a `user.updated` can land after the `user.deleted` for the same
        # id — and clearing the flag there would restore a revoked account's access to
        # every tenant it belonged to, because the auth guard re-reads exactly this
        # column on every request. Clerk never reuses a user id, so a later event for a
        # deleted one is always stale: the mirror reflects the deletion, it does not
        # get to overrule it. The JIT reconcile inherits the same property, which is why
        # `resolve_mirrored_user` refuses a deactivated row before it ever gets here.
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, name, created_at, updated_at) "
                "VALUES (:id, :cid, :email, :name, now(), now()) "
                "ON CONFLICT (clerk_user_id) DO UPDATE SET email = EXCLUDED.email, "
                "name = COALESCE(EXCLUDED.name, users.name), updated_at = now()"
            ),
            {"id": uuid7(), "cid": clerk_id, "email": email, "name": name or None},
        )
    return "mirrored"


async def fetch_clerk_user(clerk_user_id: str) -> ClerkUserLookup:
    """Ask Clerk who this subject is. The ADAPTER — the only vendor call in this module.

    The CLIENT realm's secret key, always: this function exists for the two routes that
    resolve a client-realm identity, and the admin realm is deliberately not reconciled
    (module docstring). An absent key is `unavailable`, not an error — a local build with
    no Clerk at all is the normal case there, and it must fall through to (b) rather than
    500.

    Every non-404 failure is `unavailable` rather than `absent`, deliberately: reading a
    502 from Clerk as "this user does not exist" would sign a real customer out during
    someone else's outage.
    """
    secret = get_settings().clerk_client_secret_key
    if not secret:
        return ClerkUserLookup(status="unavailable")

    try:
        async with httpx.AsyncClient(
            base_url=CLERK_API_BASE,
            timeout=CLERK_REQUEST_TIMEOUT_S,
            headers={"Authorization": f"Bearer {secret}"},
        ) as client:
            response = await client.get(f"/users/{clerk_user_id}")
    except httpx.HTTPError as exc:
        log.warning(
            "clerk_backend_api_unreachable",
            extra={"clerk_user_id": clerk_user_id, "reason": type(exc).__name__},
        )
        return ClerkUserLookup(status="unavailable")

    if response.status_code == 404:
        return ClerkUserLookup(status="absent")
    if response.status_code != 200:
        log.warning(
            "clerk_backend_api_refused",
            extra={"clerk_user_id": clerk_user_id, "status": response.status_code},
        )
        return ClerkUserLookup(status="unavailable")

    try:
        body = response.json()
    except ValueError:
        log.warning("clerk_backend_api_unparseable", extra={"clerk_user_id": clerk_user_id})
        return ClerkUserLookup(status="unavailable")
    if not isinstance(body, dict):
        return ClerkUserLookup(status="unavailable")
    return ClerkUserLookup(status="found", user=body)


async def _mirrored_row(clerk_user_id: str) -> tuple[UUID, bool] | None:
    """`(user_id, is_deactivated)` for this subject, or None if we have never seen it.

    `users` is a GLOBAL table (identity crosses tenants), so this needs no tenant
    context. It reads `deactivated_at` rather than filtering on it, because "no row" and
    "revoked row" get opposite answers and a filtered query cannot tell them apart —
    which is how a revoked account used to receive the same sentence as a brand-new one.
    """
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT id, deactivated_at FROM users WHERE clerk_user_id = :cid"),
                {"cid": clerk_user_id},
            )
        ).first()
    if row is None:
        return None
    return UUID(str(row[0])), row[1] is not None


async def resolve_mirrored_user(clerk_user_id: str) -> UUID:
    """OUR user id for a VERIFIED client-realm Clerk subject, reconciling if we must.

    The single definition. `core/auth.py::current_identity` and
    `core/auth.py::_load_client_principal` both call it, so "which token is which user"
    is decided once — the same reason `_impersonation_slug` exists (D-119).

    Raises: 401 for a revoked or Clerk-unknown subject (permanent), the
    `identity_mirror_pending` transient refusal when the mirror is absent and Clerk could
    not be asked.
    """
    existing = await _mirrored_row(clerk_user_id)
    if existing is not None:
        user_id, deactivated = existing
        if deactivated:
            # Checked BEFORE any reconcile: a revoked account must not be resurrected by
            # walking into a route that backfills.
            raise ProblemError.unauthorized("This account has been deactivated.")
        return user_id

    lookup = await fetch_clerk_user(clerk_user_id)
    if lookup.status == "absent":
        # Clerk answered, authoritatively, that there is no such user. Retrying cannot
        # change that, so it must not be the transient refusal.
        log.warning("clerk_identity_absent_upstream", extra={"clerk_user_id": clerk_user_id})
        raise ProblemError.unauthorized("This account is not provisioned.")
    if lookup.status == "unavailable" or lookup.user is None:
        log.warning("clerk_identity_mirror_pending", extra={"clerk_user_id": clerk_user_id})
        raise _mirror_pending()

    result = await mirror_clerk_user(lookup.user, deleted=False)
    reconciled = await _mirrored_row(clerk_user_id)
    if reconciled is None or reconciled[1]:
        # `ignored` (Clerk gave us a user with no email address, which our `users` table
        # cannot represent) or a `user.deleted` webhook that won the race with our write.
        # Neither is a state a retry improves, but neither is an authentication failure
        # either — so it is the transient refusal with an operator log line, not silence.
        log.warning(
            "clerk_identity_reconcile_incomplete",
            extra={"clerk_user_id": clerk_user_id, "result": result},
        )
        raise _mirror_pending()
    log.info("clerk_identity_reconciled", extra={"clerk_user_id": clerk_user_id})
    return reconciled[0]


__all__ = [
    "CLERK_API_BASE",
    "CLERK_REQUEST_TIMEOUT_S",
    "MIRROR_PENDING_CODE",
    "MIRROR_RETRY_AFTER_S",
    "ClerkUserLookup",
    "fetch_clerk_user",
    "mirror_clerk_user",
    "resolve_mirrored_user",
]
