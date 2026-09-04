"""Client onboarding (FLOWS §1) — the wizard's server side.

The wizard is 8 steps and every one is idempotent and resumable, because onboarding a
client is a conversation that spans days, not a form submission. This module implements
the steps that create durable state. The test-call gate (step 7) depends on the pilot and
is explicitly not stubbed here, and step 6's number is not ours to obtain at all — the
client takes the connection on their own operator account (Model B, FLOWS §10) and an
operator RECORDS it with `POST /v1/admin/tenants/{tenant_id}/numbers`.

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
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Final
from uuid import UUID

from scripts.seed import DEFAULT_RETENTION_POLICIES, VERTICAL_TEMPLATES
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.holds import NO_HOLDS, read_tenant_holds
from apps.api.agents.lifecycle import create_agent
from apps.api.compliance.disclosure import (
    AI_DISCLOSURE_TEMPLATES,
    RECORDING_NOTICE_TEMPLATES,
    bundled_disclosure_line,
)
from apps.api.compliance.service import SELF_SERVE_TIERS, spend_capped
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.api.tenancy.lifecycle import assert_account_open
from apps.api.tenancy.models import DEFAULT_PLAN_TIER as _DEFAULT_PLAN_TIER

log = get_logger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")
INVITE_TTL = timedelta(hours=72)

# DERIVED, NEVER RETYPED (D-163). This table used to be the literal source of the bundled
# line, and the bundling was the defect: SEC-COMP §2's two invariants — the AI sentence
# and the recording notice — could only ever be switched on and off together because they
# were one string. They are two strings now (`compliance/disclosure`), and this stays as
# the composition of the pair so nothing that quotes "the disclosure line" has to be
# rewritten and no fourth spelling of these sentences can appear.
#
# It is what a NEW agent's `disclosure_line` (the legacy bundle) starts as; the split
# halves and the two toggles are written beside it. FLOWS §1 step 4's "inserted by us"
# still holds for the TEXT — a client cannot author it — while WHETHER each half is
# volunteered is now theirs to decide (D-163).
DISCLOSURE_TEMPLATES = {
    language: bundled_disclosure_line(
        ai_disclosure_line=AI_DISCLOSURE_TEMPLATES[language],
        recording_notice_line=RECORDING_NOTICE_TEMPLATES[language],
    )
    for language in AI_DISCLOSURE_TEMPLATES
}


async def tenant_exists(session: AsyncSession, tenant_id: UUID) -> bool:
    """Is this a live organization? The one definition, so every surface that names a
    tenant in its path answers a mistyped uuid the same way.

    Soft-deleted counts as absent: `deleted_at` is set by the erasure path and a tenant
    on its way out must not be creditable, cappable or dialable. Callers turn a False
    into `ProblemError.not_found("Organization")` — a 404 rather than an FK violation
    rendered as a 500, or worse a cheerful 200 describing a tenant that is not there.

    It lives here, with `create_organization`, because organizations are this module's
    subject; the billing routes that ask it are callers, not owners.
    """
    found = (
        await session.execute(
            text("SELECT 1 FROM organizations WHERE id = :tid AND deleted_at IS NULL"),
            {"tid": tenant_id},
        )
    ).first()
    return found is not None


def slugify(name: str) -> str:
    """The ASCII slug a business name yields, or `""` when it yields none.

    **The empty string is a real answer and callers must handle it** — use
    `derive_slug` rather than this function unless you genuinely want the raw
    derivation. It used to return the constant `"client"` instead, which on a
    Telugu-first product (D-36) was the DEFAULT path and not an edge case: every
    character of `మా క్లినిక్` and `नमस्ते क्लिनिक` is outside `[a-z0-9]`, so the first
    such client silently became `/c/client` and every one after it was refused
    `slug_taken` — a 409 with no remediation, on a name the operator never typed.

    Transliteration was the obvious alternative and is not available: no ASCII-folding
    library is installed (`unidecode`/`text-unidecode`/`python-slugify` are all absent),
    `unicodedata.normalize("NFKD", …)` folds Latin diacritics but reduces Indic scripts
    to nothing, and adding a dependency to the tenant-creation path is a supply-chain
    decision (hard rule 9) rather than a slug fix. Asking is strictly better than
    guessing here anyway: the slug is IMMUTABLE once written, it appears in every client
    URL, and the person creating the account is sitting in front of the form.

    Truncation happens BEFORE the strip so a name cut at 40 characters cannot leave a
    trailing hyphen; `SLUG_RE` would accept `sunrise-clinic-and-diagnostics-centre-hyd-`
    and nobody wants that in a URL.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower())[:40].strip("-")


def derive_slug(name: str) -> str:
    """The slug to use when the caller did not pick one — or an actionable refusal.

    The ONE derivation both motions share (the admin wizard and self-serve signup, via
    `tenancy.signup.derive_slug`), so a business gets the same URL whichever door it
    came through, and gets the same sentence when we cannot build one.

    A refusal rather than a generated `client-7f3a2b`: an opaque URL is permanent, it is
    what the client's staff type every day, and the operator can answer the question in
    two seconds. `fields` names `slug` so the form can focus the input the caller has to
    fill in — which is also why the old behaviour was worse than it looked, since it
    reported `invalid_slug` against a field the caller had left blank on purpose.
    """
    slug = slugify(name)
    if not SLUG_RE.match(slug):
        raise ProblemError(
            kind="validation",
            code="slug_not_derivable",
            title="Choose a web address",
            detail=(
                "We could not build a web address out of that business name, so please choose one."
            ),
            fields=[
                {
                    "field": "slug",
                    "rule": "required",
                    "message": "3-40 characters of a-z, 0-9 and -",
                }
            ],
            remediation=(
                "Enter the web address for this client yourself — for example "
                "'sri-sai-dental'. It appears in every client URL and cannot be changed "
                "later."
            ),
        )
    return slug


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


#: RE-EXPORTED, NOT RESTATED (D-521). The value moved to `tenancy/models.py` beside
#: `PLAN_TIERS`, because `billing.service.plan_tier_of` needs the same answer for a row it
#: cannot see and the money layer may not import an admin module. Every caller that says
#: `admin.service.DEFAULT_PLAN_TIER` still resolves; there is one definition.
DEFAULT_PLAN_TIER = _DEFAULT_PLAN_TIER

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

    The default tier is `DEFAULT_PLAN_TIER` — `prepaid` since D-521, `managed` before
    it. A client an operator creates is now credit-gated like every other account, and
    `managed` is set afterwards, deliberately, for a client genuinely invoiced on a
    retainer (`POST /v1/admin/tenants/{tenant_id}/plan-tier`). The default membership is
    still none — an operator invites the owner afterwards (FLOWS §2), so there is no
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
    schema_id = uuid7()

    # The uniqueness probe MUST see every tenant's slug. Under `untenanted_session`
    # RLS would hide them all and the check would always pass, leaving the unique
    # index as the only line of defence for a case it should catch cleanly here.
    async with admin_session() as probe:
        await assert_slug_available(probe, slug)

    fields = VERTICAL_TEMPLATES.get(vertical_template, VERTICAL_TEMPLATES.get("clinic", []))

    # FORCE RLS derives WITH CHECK from USING, so creating a tenant root requires the
    # new org's own GUC — generate the id first, then insert under it (the pattern the
    # RLS tests pin down).
    try:
        agent_id = await _write_tenant_root(
            tenant_id=tenant_id,
            schema_id=schema_id,
            name=name,
            slug=slug,
            vertical_template=vertical_template,
            billing_email=billing_email,
            language=language,
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
        # Echoed so the wizard's intake step can pick this trade's examples from the
        # SERVER's answer rather than from the radio button it happens to still hold —
        # the same place a resumed wizard reads it from.
        "vertical_template": vertical_template,
        # NOT `plan_tier`: `admin/routes.py` builds an `extra="forbid"` response model
        # straight from this dict, so a new key here is a 500 on the wizard. Signup
        # adds the tier to its own return value, where a caller asked for it.
    }


async def _write_tenant_root(
    *,
    tenant_id: UUID,
    schema_id: UUID,
    name: str,
    slug: str,
    vertical_template: str,
    billing_email: str | None,
    language: str,
    fields: Any,
    created_by: UUID | None,
    plan_tier: str,
    owner_user_id: UUID | None,
    on_created: TenantRootHook | None,
) -> UUID:
    """The single transaction the tenant is born in — see `create_organization`.

    Returns the receptionist's id, which it now MINTS rather than receives: the agent row
    is written by `agents/lifecycle.create_agent`, the one INSERT into `agents` in this
    repository (D-440). It used to be spelled out here, which was fine while a tenant got
    exactly one agent and nobody else could make another — the moment a client can create
    their own, a second INSERT is a second place deciding what a new agent is born with,
    and four of those columns are hard rule 5.
    """
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
        # D-38: the inbound receptionist is the headline capability, so the default agent
        # a new client gets IS the receptionist. Everything else about how it is born —
        # both disclosure sentences, both toggles, the legacy bundle, the platform engine,
        # `status = 'draft'` — belongs to `create_agent`, which is now the only writer of
        # this table (D-440).
        agent_id = await create_agent(
            session,
            tenant_id=tenant_id,
            name=f"{name} receptionist",
            direction="inbound",
            language_primary=language,
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
            # already exist in `users` — the FK says so, and an owner id naming
            # nobody must fail the whole birth rather than create a tenant nobody can
            # enter.
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
    return agent_id


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


async def create_invitation(
    session: AsyncSession, *, tenant_id: UUID, email: str, role: str, created_by: UUID | None
) -> tuple[UUID, str]:
    """Single-use, 72h, HASHED at rest (FLOWS §2). Returns `(id, RAW token)`; the token
    is returned exactly once — it is never stored and never logged, so a leaked database
    does not hand out account access.

    THE TWO REFUSALS LIVE HERE, not in one caller. This is the only statement in the
    system that mints an invitation row, and it had two callers enforcing two different
    rulebooks: `tenancy/members.py` refused an address already on the team and refused a
    second live token for one address, while the wizard's `POST
    /v1/admin/tenants/{id}/invitations` refused neither. So the console's own "Create
    invite" button, pressed twice — which is exactly what an operator does when the
    first token scrolls out of view — put TWO live owner credentials for one client
    account into somebody's inbox, and revoking the one you can see leaves the other
    working. The rule was never realm-specific; it was only ever written down in the
    realm that happened to be built second.

    Both reads run under the caller's tenant session, so they can only answer about THIS
    account: "is this address already here" must not become a way to probe whether an
    address exists on the platform.

    What stays with the CALLER is the authorization question, because it differs
    legitimately: `members.create_team_invitation` checks that an owner may grant the
    role it is handing out, and an admin-realm operator has no membership role to check
    against — they hold `admin:tenants` instead, which the route asserts.

    Returning the id rather than making the caller re-find the row by token hash: the
    hash is the only exact key an outside lookup has, and re-deriving it means hashing
    the secret a second time in a second place.

    THE THIRD REFUSAL, added for the same reason as the first two: the account has to be
    open. See `assert_account_open` — before it, `POST /v1/admin/tenants/{typo}/invitations`
    was a 500 and an invitation into a closed account was a 201.
    """
    await assert_account_open(session, tenant_id=tenant_id)

    already = (
        await session.execute(
            text(
                "SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE lower(u.email) = lower(:e)"
            ),
            {"e": email},
        )
    ).first()
    if already is not None:
        raise ProblemError.business_rule(
            "member_already_on_team",
            "That person is already on this account.",
            remediation="Change their role from the team list instead of inviting them again.",
        )

    pending = (
        await session.execute(
            text(
                "SELECT 1 FROM invitations WHERE lower(email) = lower(:e) "
                "AND used_at IS NULL AND expires_at > now()"
            ),
            {"e": email},
        )
    ).first()
    if pending is not None:
        # Refused rather than silently replaced: issuing a second live token for one
        # address doubles the number of keys to that account in somebody's inbox, and
        # quietly revoking the first would break a link that may already be in transit.
        raise ProblemError.conflict(
            "invitation_already_pending",
            "There is already an unused invitation for that address.",
            remediation="Revoke the pending invitation first if you want to send a new link.",
        )

    invitation_id = uuid7()
    raw = secrets.token_urlsafe(32)
    await session.execute(
        text(
            "INSERT INTO invitations (id, tenant_id, email, role, token_hash, expires_at, "
            "created_by, created_at, updated_at) VALUES (:id, :tid, :email, :role, :hash, "
            # ONE CLOCK PER DEADLINE (D-322). This was `datetime.now(UTC) + INVITE_TTL`,
            # the API process's clock, while BOTH readers of the column compare it with
            # the database's: `expires_at > now()` in the pending-invitation probe above
            # and in `accept_invitation`'s burn. A deadline written by one clock and
            # judged by another is wrong by the skew between them — and by the age of the
            # transaction as well, because `now()` is transaction START time while the
            # Python expression is evaluated when the statement is built, so an invitation
            # created after other work in the same request silently outlived its stated
            # 72 hours by however long that work took.
            "now() + make_interval(secs => :ttl_s), :by, now(), now())"
        ),
        {
            "id": invitation_id,
            "tid": tenant_id,
            "email": email,
            "role": role,
            "hash": sha256(raw.encode()).hexdigest(),
            "ttl_s": INVITE_TTL.total_seconds(),
            "by": created_by,
        },
    )
    return invitation_id, raw


#: The shortest gap between two sends of one invitation. A rate limit rather than a
#: refusal, and a small one: the legitimate motion here is "they say it never arrived,
#: send it again", which happens twice in a minute while an operator is on the telephone
#: with the client. What it is actually stopping is the console's own button being held
#: down and a mailbox being used as an outbound spam relay against an address the operator
#: chose — so it is a floor on the SEND, and the previous link dies on every one of them.
RESEND_MIN_INTERVAL = timedelta(minutes=2)

#: How many times one invitation may be sent before the operator has to stop and do
#: something else. Ten is enough for any honest sequence of "it went to spam, try again"
#: and far short of anything that reads as delivery-by-repetition; past it the answer is a
#: telephone call, which is also the only way to establish that the ADDRESS is wrong.
RESEND_MAX_SENDS = 10


@dataclass(frozen=True, slots=True)
class ResentInvitation:
    """What a resend produced: the row it rotated and the state the console renders."""

    id: UUID
    email: str
    role: str
    token: str
    expires_at: datetime
    last_sent_at: datetime
    send_count: int


#: The fields an operator may edit on a client's own record, and NOTHING else on the row.
#:
#: A whitelist of two rather than "whatever the body carries", because `organizations` also
#: holds `status`, `plan_tier`, `deleted_at`, the closure columns and `default_llm_model` —
#: each of which has its own route, its own permission and, for three of them, its own
#: step-up. A general-purpose PATCH over the table would quietly become a second door to
#: all of them, and the first thing through it would be a lifecycle change with no reason
#: and no confirmation.
#:
#: `slug` is absent and could not be added: it is in client URLs and a trigger makes it
#: immutable (migration 05bba2f3c19c). `billing_email` IS here and is NOT a login
#: identity — the credential is `users.email` and `apps/api/authn/` is the only thing that
#: mints a session from it. What this column decides is where the account's NOTICES go
#: (`workers/notifications`, `workers/account_closure`), which is why the caller notifies
#: the old address as well as writing the new one.
EDITABLE_TENANT_FIELDS: Final = ("name", "billing_email")


@dataclass(frozen=True, slots=True)
class TenantFieldEdit:
    """One field an operator changed, with the value it replaced.

    The OLD value is carried out of the statement that replaced it rather than read
    beforehand, for `set_plan_tier`'s reason: a separate SELECT is a guess about a value
    another operator may have changed between the two statements, and the audit row has to
    name what this write actually replaced.
    """

    field: str
    before: str | None
    after: str | None


_EDIT_TENANT = (
    "UPDATE organizations o SET {assignments}, updated_at = now() "
    "FROM organizations old "
    "WHERE o.id = old.id AND o.id = :tid AND o.deleted_at IS NULL "
    "RETURNING {returning}"
)


async def edit_tenant_profile(
    session: AsyncSession, *, tenant_id: UUID, changes: Mapping[str, str]
) -> list[TenantFieldEdit]:
    """Change a client's own details. Returns ONLY the fields this call actually moved.

    An unchanged field is not an edit and must not produce an audit row: an operator who
    opens the form, changes the name and saves must leave one record saying the name
    changed, not two saying the name changed and the address stayed the same. So the
    comparison is done here, from the values the statement returned, rather than by
    trusting that the caller sent only differences.

    ONE STATEMENT, `FROM organizations old`, exactly as `set_plan_tier` does: the
    pre-UPDATE snapshot of the same row comes back with the write, so the audit row names
    the value this statement replaced instead of a value some other transaction may have
    replaced in between.

    `deleted_at IS NULL` in the WHERE clause and not merely in a preceding check: editing
    the contact details of a client whose data has been erased is editing a record that no
    longer describes anything, and the certificate says so. A closed-but-not-erased account
    IS editable, deliberately — an operator on the telephone with a departing client
    correcting the address their closure notice goes to is exactly the case.

    Raises on a field outside `EDITABLE_TENANT_FIELDS`. That is a programming error rather
    than an operator input — the route's schema is `extra="forbid"` and names the two — so
    it raises rather than rendering a message, the shape `set_plan_tier` uses for the same
    class of defence in depth.
    """
    unknown = sorted(set(changes) - set(EDITABLE_TENANT_FIELDS))
    if unknown:
        raise ValueError(f"{unknown} is not an editable tenant field")
    if not changes:
        return []

    # Column names are interpolated, and they are safe BY CONSTRUCTION rather than by
    # escaping: every one has just been proved a member of a module-level literal tuple.
    # The VALUES are bound. This is the same construction `db/transition.py::_identifier`
    # argues for its own `extra_set`.
    fields = [field for field in EDITABLE_TENANT_FIELDS if field in changes]
    assignments = ", ".join(f"{field} = :{field}" for field in fields)
    returning = ", ".join(f"old.{field}, o.{field}" for field in fields)
    row = (
        await session.execute(
            text(_EDIT_TENANT.format(assignments=assignments, returning=returning)),
            {"tid": tenant_id, **{field: changes[field] for field in fields}},
        )
    ).first()
    if row is None:
        # No visible, un-erased row with that id. The caller owns the 404 for the reason
        # `set_plan_tier` gives — `tenant_exists` is where "this client does not exist"
        # is decided once for every surface.
        raise ProblemError.not_found("Client")

    values = tuple(row)
    edits: list[TenantFieldEdit] = []
    for index, field in enumerate(fields):
        before, after = values[index * 2], values[index * 2 + 1]
        if before != after:
            edits.append(
                TenantFieldEdit(
                    field=field,
                    before=str(before) if before is not None else None,
                    after=str(after) if after is not None else None,
                )
            )
    return edits


async def resend_invitation(
    session: AsyncSession,
    *,
    invitation_id: UUID,
    email: str | None = None,
) -> ResentInvitation:
    """Re-cut the key for an invitation nobody has redeemed. Returns the RAW token once.

    ═══ IT ROTATES THE ROW; IT DOES NOT MINT A SECOND ONE ═══

    The obvious implementation is revoke-then-create, and it is wrong in two ways that
    both matter. It produces two audit lineages for one invitation, so "we have sent this
    five times" is a query nobody writes; and between the DELETE and the INSERT the
    account has NO live invitation, so a failure in the second half leaves an operator
    who pressed "resend" with less than they started with — on the wizard's owner invite,
    that is an account nobody can get into.

    Rotating `token_hash` in place makes the security property structural rather than
    enforced: **the previous link stops working in the same statement that mints the new
    one**, because `accept_invitation` matches on the hash and there is only ever one row.
    `create_invitation`'s `invitation_already_pending` refusal — two live keys to one
    account in somebody's inbox — is left exactly as it is; it now guards a door nobody
    needs to walk through.

    ═══ THE ADDRESS MAY BE CORRECTED, AND WHY THAT IS NOT A HOLE ═══

    `email` re-points the invitation at a different mailbox. That is the founder's actual
    case: a client mistyped their address at signup, so they can receive NOTHING and no
    self-service recovery can reach them — every one of those flows sends a token to the
    address that does not work.

    It is not an account-takeover path, and the reason is that there is no account to take
    over. This acts ONLY on an invitation with `used_at IS NULL`: nobody has redeemed it,
    no `users` row was created from it, no credential exists and no session has ever been
    minted for it. The moment one has, this refuses (the CAS below) and the address is a
    LOGIN IDENTITY — changing that is a different act with a different, stronger flow, and
    this deliberately cannot perform it.

    What it does carry is an operator attestation: an admin typing a corrected address is
    asserting they established it out of band, and the route records it as an attestation
    rather than as a verified fact. The address still starts UNVERIFIED — redemption does
    not mark it proved (D-185), and one `email_verify` round trip the person completes
    themselves is what does.

    ═══ THE FOUR REFUSALS ═══

    * **No such live invitation** (used, expired, revoked, or another tenant's under RLS)
      → 404. One answer for all of them, deliberately: an id that names another tenant's
      row must not be distinguishable from one that names nothing (D-65).
    * **The account is closed** → `assert_account_open`, the same predicate the mint and
      the burn already ask. Re-cutting a key to an account on a retention clock is the
      thing that check exists to stop, and a resend is a mint.
    * **Sent too recently** → `invitation_resend_too_soon`, carrying the seconds to wait.
    * **Sent too many times** → `invitation_resend_exhausted`. Not a lockout: revoking the
      invitation and issuing a fresh one is available and is the honest motion at that
      point, because ten failed sends is evidence about the ADDRESS, not about the link.

    The rate limit is read and written in ONE statement, on the row itself, under the
    database's own clock. A check-then-write against `last_sent_at` read separately is the
    hole two rapid clicks walk through, and comparing an API-process clock with a
    database-written column is wrong by the skew between them (D-322).
    """
    live = (
        await session.execute(
            text(
                # `send_count` and the seconds still to wait, computed by the DATABASE
                # from its own clock — see the docstring on why comparing a column the
                # database wrote against the API process's clock is wrong by the skew.
                "SELECT tenant_id, send_count, "
                "  EXTRACT(EPOCH FROM (last_sent_at + :gap - now()))::int "
                "FROM invitations "
                "WHERE id = :id AND used_at IS NULL AND expires_at > now()"
            ),
            {"id": invitation_id, "gap": RESEND_MIN_INTERVAL},
        )
    ).first()
    if live is None:
        raise ProblemError.not_found("Invitation")
    tenant_id, send_count, wait_s = live

    await assert_account_open(session, tenant_id=UUID(str(tenant_id)))

    if int(send_count) >= RESEND_MAX_SENDS:
        raise ProblemError.business_rule(
            "invitation_resend_exhausted",
            "This invitation has been sent as many times as we will send it.",
            remediation=(
                "Telephone the client to check the address, then revoke this invitation "
                "and issue a new one."
            ),
        )
    if int(wait_s) > 0:
        raise ProblemError.business_rule(
            "invitation_resend_too_soon",
            "That invitation was sent a moment ago.",
            remediation=f"Wait {int(wait_s)} more second(s) before sending it again.",
        )

    raw = secrets.token_urlsafe(32)
    rotated = (
        await session.execute(
            text(
                "UPDATE invitations SET token_hash = :hash, email = COALESCE(:email, email), "
                # THE CLOCK RESTARTS WITH THE LINK. A resend that kept the original
                # `expires_at` would hand somebody a key that expires in four minutes,
                # which is the invitation failing for a second reason after failing once.
                "  expires_at = now() + make_interval(secs => :ttl_s), "
                "  last_sent_at = now(), send_count = send_count + 1, updated_at = now() "
                # The CAS. Re-asserted rather than trusted from the read above: an
                # invitation redeemed between the two statements must lose, because the
                # winner would otherwise be rotating the key of somebody who is now a
                # member — and `used_at IS NULL` is the same predicate the burn itself is
                # a CAS on.
                "WHERE id = :id AND used_at IS NULL "
                "RETURNING email, role, expires_at, last_sent_at, send_count"
            ),
            {
                "id": invitation_id,
                "hash": sha256(raw.encode()).hexdigest(),
                "email": email,
                "ttl_s": INVITE_TTL.total_seconds(),
            },
        )
    ).first()
    if rotated is None:
        # Redeemed underneath us. 404 rather than 409, and the same 404 the read above
        # gives: the person is a member now, so there is no live invitation with that id,
        # which is exactly what this surface is asked about.
        raise ProblemError.not_found("Invitation")

    return ResentInvitation(
        id=invitation_id,
        email=str(rotated[0]),
        role=str(rotated[1]),
        token=raw,
        expires_at=rotated[2],
        last_sent_at=rotated[3],
        send_count=int(rotated[4]),
    )


async def accept_invitation(session: AsyncSession, *, raw_token: str, user_id: UUID) -> UUID:
    """Burn the invitation and create the membership. The burn is a CAS on
    `used_at IS NULL` (BACKEND-PATTERNS §5): two clicks on the same emailed link must
    produce one membership, not two.

    THE ACCOUNT IS CHECKED AFTER THE BURN AND THE BURN IS UNDONE BY THE ROLLBACK, which is
    the point: `assert_account_open` needs a tenant id, and the CAS is what supplies it
    atomically — reading the invitation first to learn the tenant, then burning, is a
    read-then-write of exactly the shape BACKEND-PATTERNS §5 refuses. The caller runs this
    inside `tenant_session`, so the raised refusal rolls the UPDATE back and the invitation
    is still unused; `tests/tenant_birth_test.py` asserts that, because a closed account
    silently eating somebody's single-use link would be a worse defect than the one this
    closes.
    """
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
    await assert_account_open(session, tenant_id=UUID(str(tenant_id)))
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
    """The admin's client DIRECTORY — every account, with the counters that belong beside
    a name.

    NOT the health overview: that is `admin/health.py`, and it answers the other question
    ("which client is about to churn or break") as a ranked exception report. This one is
    the roster, and it stays deliberately dumb — counts, not judgements — because an
    operator looking up a client should not have to read a verdict to find a slug.

    Two passes, deliberately. The DIRECTORY (names, slugs, status) comes from the
    `app.admin` session, which widens `organizations` and nothing else. The COUNTS come
    from a normal tenant-scoped session per client — because `app.admin` does not
    unlock `calls` or `leads`, and it should not: an operator listing clients has no
    business reading call rows in the same query.

    That makes this N+1 by construction. At M1 scale (one to a few dozen clients) it is
    a handful of fast counts, and the alternative is widening RLS across every tenant
    table for a dashboard. Revisit with a materialized `tenant_health` table if the
    client list ever gets long enough to notice — not before.

    **THE N+1 HAS A NUMBER NOW, AND ITS CONSTANT IS SMALLER THAN IT WAS** (D-218). 312
    accounts took 1,027 ms warm — 3.3 ms each — and the per-account cost broke down as
    connection checkout + `set_config` 0.90 ms, the four counts 0.55 ms, `holds` 0.95 ms,
    `capped` 0.45 ms. `holds` being the largest term was the finding: each blocker opens
    by reading the account's plan tier, and **for a `managed` account those two reads are
    the whole call** — both return `None` for any tier outside `SELF_SERVE_TIERS` before
    touching a compliance table. Two round trips per account to re-read a column this loop
    is already holding. It is skipped below for the tiers that cannot be held; measured
    994.3 ms → 701.7 ms over 312 managed accounts.

    What that does NOT do is change the SHAPE, and the shape is what the deferral above
    is about. Closing it needs one of two things this function may not do: widening
    `calls`/`leads`/`kyc_records` for `app.admin` (hard rule 1, and `admin/holds.py`
    rejects it at length — a policy is table-scoped, so widening to count rows also hands
    over the rows), or paging the response, which is an admin-console contract change
    rather than a query change. The materialized `tenant_health` table remains the named
    escape, and the number above is what it should be judged against.

    `holds` rides that SAME per-tenant session (`admin.holds.read_tenant_holds`), so
    the directory says which clients are waiting on a human without a second pass and
    without either compliance table being widened for `app.admin`. This is where
    `compliance/first_campaign_routes.py` said the flag belonged; the work QUEUE at
    `/v1/admin/compliance/holds` is the same predicate, filtered and ordered for triage —
    and it has ALWAYS pre-filtered its candidate set by tier for the reason this function
    now does. The two surfaces disagreeing about which accounts can even be held was the
    older defect underneath the slow one.

    `capped` rides it for the same reason and with the same discipline: it is
    `compliance.spend_capped` — the predicate that REFUSES the dial — not a second
    reading of `spend_state.capped` that happens to be in the same statement as the
    counts. See the call site for what the second reading got wrong and what asking
    properly costs.
    """
    # `tenant_id` narrows the SAME query to one client. The detail screen used to pull
    # the whole list and find its client in the browser, which pays the N+1 above once
    # per page view for a single row.
    directory = (
        await session.execute(
            text(
                # `plan_tier` is selected for the hold pre-filter below. It is already on
                # the row this statement reads, so it costs nothing, and reading it here
                # is what lets the loop decide without a round trip.
                "SELECT id, name, slug, status, vertical_template, plan_tier "
                "FROM organizations "
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
                        "  (SELECT max(started_at) FROM calls)"
                    )
                )
            ).first()
            # THE PRE-FILTER `held_tenants` HAS ALWAYS APPLIED, and this surface did not
            # (D-218). `kyc_blocker` and `first_campaign_hold_blocker` both open with
            # `plan_tier_of(...) not in SELF_SERVE_TIERS -> None`, so for a managed account
            # `read_tenant_holds` issues two `SELECT plan_tier FROM organizations` round
            # trips — one per blocker, for a tier THIS LOOP IS ALREADY HOLDING — to arrive
            # at "nothing holds this client", once per account, on the widest-read screen
            # in the console. Measured: 0.95 ms of a 3.3 ms account, the largest of the
            # four terms. A self-serve account is still asked and still pays, which is
            # correct: there the reads decide something.
            #
            # `SELF_SERVE_TIERS` is IMPORTED, never re-spelled, and it is a filter on the
            # CANDIDATE SET rather than a second copy of the rule — exactly the
            # distinction `admin/holds.py::_DIRECTORY` argues for its own use of the same
            # constant. The blocker still decides for every account this lets through,
            # and an account it excludes is one both blockers would have answered `None`
            # for on their own first line. If the tier line ever moves, it moves in
            # `compliance/service.py` and both surfaces follow it.
            holds = (
                await read_tenant_holds(scoped, tenant_id=tenant_id)
                if org[5] in SELF_SERVE_TIERS
                else NO_HOLDS
            )
            # THE GATE'S OWN PREDICATE, not a copy of it. This column used to be a fifth
            # scalar subquery in the statement above — `(SELECT capped FROM spend_state
            # LIMIT 1)` — which is the same flag but a DIFFERENT QUESTION: `capped` is
            # only ever armed by the post-call meter, and `compliance.spend_capped` reads
            # `month` alongside it because a capped outbound-only tenant meters nothing
            # and so can never clear its own flag (see that function's docstring). Without
            # the month, a tenant capped in July wore a red "capped" badge here all
            # through August while the dial gate happily dialled for them — and the
            # operator reading this screen had no way to tell which of the two was right.
            #
            # Asked through the function rather than by adding `AND month = :month` to the
            # subquery, because a second copy of the predicate is how the first one drifted:
            # `admin/health.py` already calls `spend_capped` for exactly this fact, and two
            # admin surfaces disagreeing about whether a client is capped is worse than
            # either being wrong on its own.
            #
            # THE COST, measured rather than assumed (the standard `admin/health.py` sets):
            # one extra round trip per account on a session that is already open —
            # **0.41 ms median, 0.49 ms p95** on the verification database (500 samples
            # over 5 tenants), which is the same as the four-count statement above it
            # because a primary-key lookup on `spend_state` costs a round trip and nothing
            # else. Against ~2 ms per account for the whole block, and against a directory
            # that is N+1 by construction (see above), it is not the term that decides when
            # this loop has to become the materialized `tenant_health` table.
            capped = await spend_capped(scoped, tenant_id=tenant_id)
        overview.append(
            {
                "id": tenant_id,
                "name": org[1],
                "slug": org[2],
                "status": org[3],
                "vertical_template": org[4],
                # WHICH BILLING MOTION, on the roster (D-521). It was selected here for
                # the hold pre-filter and thrown away, so the console could not show it —
                # survivable while `managed` was the silent default and every account was
                # the same, and not survivable now that `prepaid` is the default and
                # `managed` is a deliberate exception: an operator has to be able to SEE
                # which clients are invoiced before deciding anything about one.
                "plan_tier": org[5],
                "live_agents": int(counts[0] or 0) if counts else 0,
                "calls_7d": int(counts[1] or 0) if counts else 0,
                "leads": int(counts[2] or 0) if counts else 0,
                "last_call_at": counts[3] if counts else None,
                "capped": capped,
                # Which human-action gates hold this client, in the gates' own rule
                # names. Empty, always, for every client an operator created — both
                # controls are about unattended signups (D-521 split that question from
                # the billing one, so `prepaid` is outside them too).
                "holds": list(holds.rules),
            }
        )
    return overview


#: The tiers an OPERATOR may put an account on, and the two the route below refuses.
#:
#: `managed` and `prepaid` are the two BILLING motions, and moving between them is exactly
#: what an operator decides: this client is invoiced on a retainer, or this client pays
#: from a wallet (D-521). `self_serve` and `trial` are not a billing choice — they record
#: that a STRANGER opened the account unattended, which is what the subscriber-KYC dial
#: gate (D-47) and the first-campaign hold (D-51) key on. Writing one of them onto a client
#: an operator created would refuse that client's next dial with `kyc_missing` for a fact
#: that is not true of them, so those two stay writable only by `tenancy/signup.py`, which
#: is the path where the fact is actually established.
OPERATOR_SETTABLE_PLAN_TIERS: Final = ("managed", "prepaid")

#: The previous tier and the new one in ONE statement, rather than SELECT-then-UPDATE.
#:
#: The audit row has to name what the account WAS, and a separate read would be a guess
#: about a value another operator may have changed between the two statements — the CAS
#: doctrine in `docs/BACKEND-PATTERNS.md` applied to a one-column write. `FROM
#: organizations old` sees the pre-UPDATE snapshot of the same row, so `RETURNING` hands
#: back the value this statement actually replaced. `plan_tier <> :tier` makes it
#: idempotent: setting the tier an account is already on matches zero rows and returns
#: nothing, which the caller reports as `changed: false` rather than writing an audit row
#: about a click that changed nothing.
_SET_PLAN_TIER = (
    "UPDATE organizations o SET plan_tier = :tier, updated_at = now() "
    "FROM organizations old "
    "WHERE o.id = old.id AND o.id = :tid AND o.plan_tier <> :tier "
    "RETURNING old.plan_tier"
)


async def set_plan_tier(session: AsyncSession, *, tenant_id: UUID, plan_tier: str) -> str | None:
    """Move one client between billing motions. Returns the tier REPLACED, or None if the
    account was already on this one.

    The caller owns the 404 (`tenant_exists`) and the audit row, for the reason
    `set_tenant_status` owns both: this function is the write, and a service that also
    decided what a missing row means would be a second answer to a question
    `tenant_exists` already answers once for every surface.

    The session must be tenant-scoped — `organizations` is FORCE-RLS, so an unscoped one
    matches zero rows and this returns None, which would read as "already on that tier".
    """
    if plan_tier not in OPERATOR_SETTABLE_PLAN_TIERS:
        # Defence in depth behind the route's own `Literal`. A caller reaching this with a
        # tier from somewhere else is a programming error, not a client input, so it raises
        # rather than rendering a message: the route's schema is what a person sees.
        raise ValueError(f"{plan_tier!r} is not an operator-settable plan tier")
    previous = (
        await session.execute(text(_SET_PLAN_TIER), {"tid": tenant_id, "tier": plan_tier})
    ).scalar()
    return str(previous) if previous is not None else None


__all__ = [
    "DEFAULT_PLAN_TIER",
    "DISCLOSURE_TEMPLATES",
    "EDITABLE_TENANT_FIELDS",
    "INVITE_TTL",
    "OPERATOR_SETTABLE_PLAN_TIERS",
    "RESEND_MAX_SENDS",
    "RESEND_MIN_INTERVAL",
    "ResentInvitation",
    "TenantFieldEdit",
    "TenantRootHook",
    "accept_invitation",
    "assert_account_open",
    "assert_slug_available",
    "create_invitation",
    "create_organization",
    "derive_slug",
    "edit_tenant_profile",
    "resend_invitation",
    "set_plan_tier",
    "slugify",
    "tenant_overview",
]
