"""Client onboarding (FLOWS §1) — the wizard's server side.

The wizard is 8 steps and every one is idempotent and resumable, because onboarding a
client is a conversation that spans days, not a form submission. This module implements
the steps that create durable state; the test-call gate (step 7) and number provisioning
(step 6) depend on the pilot and are explicitly not stubbed here.

Two things happen at creation that are easy to forget later and expensive to retrofit:

- **Retention policies** are written immediately. SEC-COMP §1's 90-day recording floor
  is a legal obligation from the first call, not from whenever someone remembers to
  configure it — and the DB CHECK will reject anything lower.
- **The extraction schema** is seeded from the vertical template, because a tenant with
  no schema produces leads with no columns, and that is what the whole product is.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from scripts.seed import DEFAULT_RETENTION_POLICIES, VERTICAL_TEMPLATES
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session

log = get_logger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")
INVITE_TTL = timedelta(hours=72)

# The disclosure line is inserted by us and cannot be removed by a client (FLOWS §1
# step 4, hard rule 5). It is per-language; Telugu is the default (D-36).
DISCLOSURE_TEMPLATES = {
    "te-IN": "Namaskaram, idi {business} AI assistant. Ee call record avutundi.",
    "hi-IN": "Namaste, main {business} ka AI assistant hoon. Yeh call record ho rahi hai.",
    "en-IN": "Hello, this is the AI assistant for {business}. This call is being recorded.",
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return slug or "client"


async def assert_slug_available(session: AsyncSession, slug: str) -> None:
    """Slugs are IMMUTABLE once set (a DB trigger enforces it) and appear in client
    URLs, so this check is the only chance to get it right."""
    if not SLUG_RE.match(slug):
        raise ProblemError(
            kind="validation",
            code="invalid_slug",
            title="Invalid slug",
            detail="A slug is 3-40 characters of lowercase letters, numbers and hyphens.",
            fields=[{"field": "slug", "rule": "pattern", "message": "a-z, 0-9 and - only"}],
        )
    reserved = (
        await session.execute(
            text("SELECT 1 FROM reserved_slugs WHERE slug = :slug"), {"slug": slug}
        )
    ).first()
    if reserved:
        raise ProblemError.conflict(
            "slug_reserved",
            "That name is reserved by the platform.",
            remediation="Pick a different business name or slug.",
        )
    taken = (
        await session.execute(
            text("SELECT 1 FROM organizations WHERE slug = :slug"), {"slug": slug}
        )
    ).first()
    if taken:
        raise ProblemError.conflict("slug_taken", "That slug is already in use.")


DEFAULT_PLAN_TIER = "managed"

# Extra writes a caller needs INSIDE the tenant's birth transaction. Called with the
# open session and the new tenant id, after every row above has been written.
TenantRootHook = Callable[[AsyncSession, UUID], Awaitable[None]]


async def create_organization(
    *,
    name: str,
    slug: str,
    vertical_template: str,
    billing_email: str | None,
    language: str,
    created_by: UUID | None,
    plan_tier: str | None = None,
    owner_user_id: UUID | None = None,
    on_created: TenantRootHook | None = None,
) -> dict[str, Any]:
    """Wizard steps 1 + 4's skeleton: org, retention defaults, agent draft, schema —
    plus, for the motions that know them at creation time, the PLAN TIER and the OWNER.

    Runs in ONE transaction: a half-created tenant (org but no retention policy, or
    agent but no schema) is worse than no tenant, because the pipeline would happily
    process calls for it. A failure at any statement therefore rolls the whole thing
    back and leaves the slug free for the retry.

    `plan_tier` and `owner_user_id` exist so self-serve signup does not have to open a
    SECOND transaction for the two facts that distinguish its motion (D-34). It used
    to, and paid for it with a compensating soft-delete on failure — a compensation
    that can itself fail, and that when it succeeds leaves a shell holding a slug the
    DB trigger makes immutable. Both facts are ordinary tenant-scoped rows: the tier is
    a column on the org row itself, and `memberships` is FORCE-RLS'd on `tenant_id`
    with `WITH CHECK (tenant_id = app.tenant_id)` (migration 8c31d0f4ab27), which the
    birth transaction's own GUC already satisfies. The USER row lives outside RLS in
    the global `users` table, but nothing here writes it — the FK is checked by the
    RI machinery, which is not subject to row security. So the membership genuinely
    belongs in this transaction; it was never blocked from being here.

    Defaults keep the admin wizard exactly as it was: `managed` tier, and no
    membership — an operator invites the owner afterwards (FLOWS §2), so there is no
    user to point at yet.

    `on_created` is the escape hatch for the caller's OWN last write (signup's audit
    row), so "the tenant exists" and "the tenant's creation was audited" commit or fail
    together instead of the second being a separate, unprotected step.

    The availability probe below runs in its own transaction, one round trip before the
    insert, so two operators creating the same client at once can both pass it. The
    UNIQUE index is the arbiter that cannot be raced, and its violation is translated
    back into the SAME 409 the probe would have produced — see the handler below.
    """
    tenant_id = uuid7()
    agent_id = uuid7()
    schema_id = uuid7()

    # The uniqueness probe MUST see every tenant's slug. Under `untenanted_session`
    # RLS would hide them all and the check would always pass, leaving the unique
    # index as the only line of defence for a case it should catch cleanly here.
    async with admin_session() as probe:
        await assert_slug_available(probe, slug)

    fields = VERTICAL_TEMPLATES.get(vertical_template, VERTICAL_TEMPLATES.get("clinic", []))
    disclosure = DISCLOSURE_TEMPLATES.get(language, DISCLOSURE_TEMPLATES["en-IN"]).format(
        business=name
    )

    # FORCE RLS derives WITH CHECK from USING, so creating a tenant root requires the
    # new org's own GUC — generate the id first, then insert under it (the pattern the
    # RLS tests pin down).
    try:
        await _write_tenant_root(
            tenant_id=tenant_id,
            agent_id=agent_id,
            schema_id=schema_id,
            name=name,
            slug=slug,
            vertical_template=vertical_template,
            billing_email=billing_email,
            language=language,
            disclosure=disclosure,
            fields=fields,
            created_by=created_by,
            plan_tier=plan_tier or DEFAULT_PLAN_TIER,
            owner_user_id=owner_user_id,
            on_created=on_created,
        )
    except IntegrityError as exc:
        # The probe lost a race with a concurrent create. Reaching the wizard as a 500
        # would tell the operator nothing and break the user-safe-message rule; the
        # answer is the one the probe would have given a moment earlier.
        async with admin_session() as probe:
            taken = (
                await probe.execute(
                    text("SELECT 1 FROM organizations WHERE slug = :slug"), {"slug": slug}
                )
            ).first()
        if taken:
            raise ProblemError.conflict("slug_taken", "That slug is already in use.") from exc
        raise

    log.info(
        "org_created",
        extra={"tenant_id": str(tenant_id), "vertical": vertical_template},
    )
    return {
        "id": tenant_id,
        "slug": slug,
        "agent_id": agent_id,
        "extraction_schema_id": schema_id,
        "status": "onboarding",
        # NOT `plan_tier`: `admin/routes.py` builds an `extra="forbid"` response model
        # straight from this dict, so a new key here is a 500 on the wizard. Signup
        # adds the tier to its own return value, where a caller asked for it.
    }


async def _write_tenant_root(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    schema_id: UUID,
    name: str,
    slug: str,
    vertical_template: str,
    billing_email: str | None,
    language: str,
    disclosure: str,
    fields: Any,
    created_by: UUID | None,
    plan_tier: str,
    owner_user_id: UUID | None,
    on_created: TenantRootHook | None,
) -> None:
    """The single transaction the tenant is born in — see `create_organization`."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, vertical_template, "
                "billing_email, plan_tier, created_by, created_at, updated_at) VALUES (:id, "
                ":name, :slug, 'onboarding', :vertical, :email, :tier, :by, now(), now())"
            ),
            {
                "id": tenant_id,
                "name": name,
                "slug": slug,
                "vertical": vertical_template,
                "email": billing_email,
                "tier": plan_tier,
                "by": created_by,
            },
        )
        for policy in DEFAULT_RETENTION_POLICIES:
            await session.execute(
                text(
                    "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, "
                    "action, created_at) VALUES (:id, :tid, :cat, :ttl, :action, now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cat": policy["data_category"],
                    "ttl": policy["ttl_days"],
                    "action": policy["action"],
                },
            )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, language_primary, "
                "disclosure_line, status, engine, created_at, updated_at) VALUES (:id, :tid, "
                ":name, 'inbound', :lang, :disclosure, 'draft', :engine, now(), now())"
            ),
            {
                "id": agent_id,
                "tid": tenant_id,
                # D-38: the inbound receptionist is the headline capability, so the
                # default agent a new client gets IS the receptionist.
                "name": f"{name} receptionist",
                "lang": language,
                "disclosure": disclosure,
                "engine": _default_engine(),
            },
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, 1, CAST(:fields AS jsonb), "
                "now(), now())"
            ),
            {"id": schema_id, "tid": tenant_id, "aid": agent_id, "fields": _json(fields)},
        )
        await session.execute(
            text("UPDATE agents SET extraction_schema_id = :sid WHERE id = :aid"),
            {"sid": schema_id, "aid": agent_id},
        )
        if owner_user_id is not None:
            # `ON CONFLICT DO NOTHING` for the same reason `accept_invitation` has it:
            # one owner per (tenant, user) whatever the caller retries. The user must
            # already exist in `users` — the FK says so, and a signup whose Clerk
            # mirror has not landed yet must fail the whole birth, not create a tenant
            # nobody can enter.
            await session.execute(
                text(
                    "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, "
                    "updated_at) VALUES (:id, :tid, :uid, 'owner', now(), now()) "
                    "ON CONFLICT (tenant_id, user_id) DO NOTHING"
                ),
                {"id": uuid7(), "tid": tenant_id, "uid": owner_user_id},
            )
        if on_created is not None:
            await on_created(session, tenant_id)


def _default_engine() -> str:
    from apps.api.core.settings import get_settings

    return get_settings().engine


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


async def create_invitation(
    session: AsyncSession, *, tenant_id: UUID, email: str, role: str, created_by: UUID | None
) -> str:
    """Single-use, 72h, HASHED at rest (FLOWS §2). Returns the RAW token exactly once —
    it is never stored and never logged, so a leaked database does not hand out
    account access."""
    raw = secrets.token_urlsafe(32)
    await session.execute(
        text(
            "INSERT INTO invitations (id, tenant_id, email, role, token_hash, expires_at, "
            "created_by, created_at, updated_at) VALUES (:id, :tid, :email, :role, :hash, "
            ":expires, :by, now(), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "email": email,
            "role": role,
            "hash": sha256(raw.encode()).hexdigest(),
            "expires": datetime.now(UTC) + INVITE_TTL,
            "by": created_by,
        },
    )
    return raw


async def accept_invitation(session: AsyncSession, *, raw_token: str, user_id: UUID) -> UUID:
    """Burn the invitation and create the membership. The burn is a CAS on
    `used_at IS NULL` (BACKEND-PATTERNS §5): two clicks on the same emailed link must
    produce one membership, not two."""
    token_hash = sha256(raw_token.encode()).hexdigest()
    row = (
        await session.execute(
            text(
                "UPDATE invitations SET used_at = now(), updated_at = now() "
                "WHERE token_hash = :hash AND used_at IS NULL AND expires_at > now() "
                "RETURNING tenant_id, role"
            ),
            {"hash": token_hash},
        )
    ).first()
    if row is None:
        raise ProblemError(
            kind="business_rule",
            code="invitation_invalid",
            title="Invitation is not usable",
            detail="This invitation has already been used or has expired.",
            remediation="Ask your account manager for a fresh invite.",
        )
    tenant_id, role = row
    await session.execute(
        text(
            "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
            "VALUES (:id, :tid, :uid, :role, now(), now()) "
            "ON CONFLICT (tenant_id, user_id) DO NOTHING"
        ),
        {"id": uuid7(), "tid": tenant_id, "uid": user_id, "role": role},
    )
    return UUID(str(tenant_id))


async def tenant_overview(
    session: AsyncSession, *, tenant_id: UUID | None = None
) -> list[dict[str, Any]]:
    """The admin's client-health list.

    Two passes, deliberately. The DIRECTORY (names, slugs, status) comes from the
    `app.admin` session, which widens `organizations` and nothing else. The COUNTS come
    from a normal tenant-scoped session per client — because `app.admin` does not
    unlock `calls` or `leads`, and it should not: an operator listing clients has no
    business reading call rows in the same query.

    That makes this N+1 by construction. At M1 scale (one to a few dozen clients) it is
    a handful of fast counts, and the alternative is widening RLS across every tenant
    table for a dashboard. Revisit with a materialized `tenant_health` table if the
    client list ever gets long enough to notice — not before.
    """
    # `tenant_id` narrows the SAME query to one client. The detail screen used to pull
    # the whole list and find its client in the browser, which pays the N+1 above once
    # per page view for a single row.
    directory = (
        await session.execute(
            text(
                "SELECT id, name, slug, status, vertical_template FROM organizations "
                "WHERE deleted_at IS NULL "
                "  AND (CAST(:tid AS uuid) IS NULL OR id = CAST(:tid AS uuid)) "
                "ORDER BY created_at DESC"
            ),
            {"tid": tenant_id},
        )
    ).all()

    overview: list[dict[str, Any]] = []
    for org in directory:
        tenant_id = org[0]
        async with tenant_session(tenant_id) as scoped:
            counts = (
                await scoped.execute(
                    text(
                        "SELECT "
                        "  (SELECT count(*) FROM agents WHERE status = 'live' "
                        "     AND deleted_at IS NULL), "
                        "  (SELECT count(*) FROM calls "
                        "     WHERE started_at > now() - interval '7 days'), "
                        "  (SELECT count(*) FROM leads WHERE deleted_at IS NULL), "
                        "  (SELECT max(started_at) FROM calls), "
                        "  (SELECT capped FROM spend_state LIMIT 1)"
                    )
                )
            ).first()
        overview.append(
            {
                "id": tenant_id,
                "name": org[1],
                "slug": org[2],
                "status": org[3],
                "vertical_template": org[4],
                "live_agents": int(counts[0] or 0) if counts else 0,
                "calls_7d": int(counts[1] or 0) if counts else 0,
                "leads": int(counts[2] or 0) if counts else 0,
                "last_call_at": counts[3] if counts else None,
                "capped": bool(counts[4]) if counts and counts[4] is not None else False,
            }
        )
    return overview


__all__ = [
    "DEFAULT_PLAN_TIER",
    "DISCLOSURE_TEMPLATES",
    "INVITE_TTL",
    "TenantRootHook",
    "accept_invitation",
    "assert_slug_available",
    "create_invitation",
    "create_organization",
    "slugify",
    "tenant_overview",
]
