"""Admin-realm endpoints (FLOWS §1, §2; D-22).

Every route here is `realm="admin"`, so a client token cannot reach any of them even
if it somehow carried the permission — the realms are separate credential domains and
`verify_token` will not accept one realm's token for the other.

Impersonation (D-22) is READ-ONLY and audited on both halves, and both halves are now
real. `POST /v1/admin/impersonation-grants` here MINTS the short-lived, tenant-bound
grant without which `core/auth.py` refuses every impersonated request, and writes
`admin.impersonation_started` in the same transaction — so "authority was issued to
operator X for tenant Y at T" cannot be missing for a session that happened.
`core/auth.py::_record_impersonated_read` records the READS, coalesced per minute, and
carries the same `grant_id` so the two halves join. See `core/impersonation.py` for the
grant's shape, its bindings and why it needs no revocation list. STARTING one of those
sessions takes step-up (D-210) — the mint is the single door in front of every tenant-realm
read an operator can reach, including the raw transcript BACKEND-PATTERNS §7 names.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import intake, service
from apps.api.agents import service as agents_service
from apps.api.authn.service import enqueue_invitation_email
from apps.api.billing import service as billing
from apps.api.billing import terms as billing_terms
from apps.api.billing.cap_routes import MAX_CLIENT_CAP_MIN, MAX_CLIENT_CAP_SPEND_INR
from apps.api.billing.plans import IST, ist_billing_month, parse_billing_month
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import record_kyc
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import IMPERSONATE_HEADER, IMPERSONATION_GRANT_HEADER, Principal
from apps.api.core.deps import admin_db, db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.impersonation import (
    GRANT_TTL,
    VIEW_AS_MAX_AGE,
    mint_grant,
    renewable_grant,
)
from apps.api.core.rbac import ROLE_PERMISSIONS, permission_meta, role_has
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session
from apps.api.db.transition import transition_status
from apps.api.kb import service as kb_service

router = APIRouter(prefix="/v1/admin", tags=["admin"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
# Reads the tenant DIRECTORY (organizations) cross-tenant; nothing else.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
TenantSession = Annotated[AsyncSession, Depends(db)]

Vertical = Literal["clinic", "real_estate", "insurance", "education", "custom"]


# --- Identity: who the console is talking as ----------------------------------


class AdminMeOut(BaseModel):
    """The admin realm's own identity document.

    `MeOut` (tenancy/routes.py) minus everything that is a property of a TENANT. There
    is no `organization`, because an admin principal resolved without
    `X-Impersonate-Org` has no tenant at all; and no `impersonating`, because a console
    screen that had to enter a client to ask who it was is precisely the shape this
    route removes. What is left — the role and the permission set — is the whole of what
    the console legitimately needs to preview its own gates.
    """

    model_config = ConfigDict(extra="forbid")

    # Constant by construction, and stated anyway: a component that can receive either
    # identity document must be able to tell them apart without inspecting the URL it
    # happened to call, and `MeOut.realm` is how the client realm already says it.
    realm: Literal["admin"]
    # `admin_users.id`: the value that appears in `audit_log.actor_id`,
    # so an operator reading "who am I" and an auditor reading "who did this" see one id.
    user_id: UUID
    role: str
    # The ROLE's full set, exactly as `/v1/me` reports it for the client realm. It is a
    # PREVIEW — every endpoint still enforces its own permission — and it is what lets a
    # control or a nav entry the session cannot use say so before the click.
    permissions: list[str]


@router.get(
    "/me",
    response_model=AdminMeOut,
    openapi_extra=permission_meta("org:read"),
    summary="Who this operator is — the admin realm's own identity, no tenant involved",
    description=(
        "The admin console's answer to 'who am I and what may I do'. Authenticates an "
        "admin token with NO impersonation header and reads no tenant: the role comes "
        "from `admin_users` and the permission set from the role table, so nothing here "
        "depends on which client happens to be open."
    ),
)
async def admin_me(
    principal: Principal = Depends(requires("org:read", realm="admin")),
) -> AdminMeOut:
    """The admin realm's `/v1/me`, and the reason it had to be its own route.

    `/v1/me` resolves through `current_any`, which consults the ADMIN realm only when
    `X-Impersonate-Org` is present (`core/auth.py`) — so a bare admin token asking it is
    verified as a CLIENT token and refused. The console's only way to learn its own role
    was therefore to impersonate some tenant and read the answer from inside it, which
    needs a slug the cross-tenant screens do not have and spends `admin:impersonate` on a
    client nobody opened. Two admin screens could not do even that and derived their gate
    from their own route's 403 instead: three workarounds for one missing endpoint.

    **`org:read`, not `admin:tenants`.** The rule first: D-22 forbids gating a GET on a
    permission read-only impersonation refuses, `admin:tenants` is in
    `MUTATING_PERMISSIONS`, and `tests/impersonation_reads_test.py` walks the live route
    table for exactly that mistake — the same choice `holds_routes.py` and
    `health_routes.py` argue, and this route does not inherit the exemption list the
    older `/v1/admin/tenants` GETs carry. The reason beyond the rule is stronger: an
    identity read gated on the authority to MANAGE tenants would answer "what may I do"
    only to the accounts that may already do the most, and a narrower role could learn
    its own limits only by collecting 403s — which is the workaround this route deletes.
    `org:read` is the least-privileged permission in the table, every role in either
    realm holds it, and it is what `/v1/me` requires, so both identity endpoints answer
    to the same authority.

    **`realm="admin"` is what separates the realms**, never the permission: client roles
    hold `org:read` too, and it is the dependency's resolution against `admin_users` that
    a client token cannot pass.

    No session dependency on purpose. `Depends(db)` would drag in `tenant_of`, which for
    an admin principal without the header has no tenant to give — the un-callable shape
    `tests/route_shape_test.py` pins. This route touches no tenant table at all.
    """
    if principal.user_id is None or principal.role is None:  # pragma: no cover
        # Unreachable: `requires()` refuses a principal with no role, and
        # `_load_admin_principal` only returns one whose id came from `admin_users`. A
        # refusal rather than a cast, because this response is what the console believes
        # about itself — the one place a silently widened `None` would become a screen.
        raise ProblemError.forbidden("This account has no admin access.")
    return AdminMeOut(
        realm="admin",
        user_id=principal.user_id,
        role=principal.role,
        permissions=sorted(ROLE_PERMISSIONS.get(principal.role, frozenset())),
    )


class TenantSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    status: str
    vertical_template: str | None
    live_agents: int
    calls_7d: int
    leads: int
    last_call_at: datetime | None
    capped: bool
    # The human-action gates holding this client, by the gates' own rule names — the
    # flag `/v1/admin/compliance/holds` turns into a work queue. Empty for a client
    # nobody is waiting on, and for every managed client (both controls are self-serve).
    holds: list[str]


class CreateOrgIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    # Optional: derived from the name when absent. IMMUTABLE once set (DB trigger),
    # because it lives in every client URL.
    slug: str | None = Field(default=None, max_length=40)
    vertical_template: Vertical = "clinic"
    billing_email: EmailStr | None = None
    language: Literal["te-IN", "hi-IN", "en-IN"] = "te-IN"


class CreateOrgOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    agent_id: UUID
    extraction_schema_id: UUID
    status: str


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: Literal["owner", "staff"] = "owner"


class InviteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The row, so the caller can revoke the thing it just created. Without it the wizard
    # could mint an invitation and had no handle on it — and since `create_invitation`
    # refuses a SECOND live token for one address, an operator whose first token was lost
    # would be locked out of that address for 72 hours with no control anywhere in the
    # admin realm (the revoke that existed is client-realm, and the client cannot sign in
    # yet — that is what the invitation is FOR).
    id: UUID
    #: WAS `token: str`, and its removal is the point of D-198 — the same removal D-190
    #: made on the client realm's `POST /v1/tenants/invitations`, which this route is the
    #: twin of and which it was left behind by.
    #:
    #: This handed the raw invitation token back to the OPERATOR and mailed nothing, so the
    #: onboarding wizard rendered a live owner credential on screen for a client account
    #: and the invitee was told by whatever channel the operator chose. D-190 records what
    #: that costs and why it is not a caveat: "the squat is possible for exactly as long as
    #: anyone but the invitee can see the token". D-185 stopped a squatted address becoming
    #: somebody else's account and explicitly could not stop the squat itself, naming the
    #: emailing of the token as the one thing that closes it — and then closed it on one of
    #: the two routes that mint invitations.
    #:
    #: The operator is a narrower attacker than "any tenant owner", which is why this half
    #: survived the first pass. It is not no attacker: `admin:tenants` is held by every
    #: `operator`, an invitation may name any address, and the resulting `users` row is
    #: GLOBAL and unique per address.
    #:
    #: `delivery` replaces it, exactly as on the client realm, so the wizard can say the
    #: link was sent rather than render a secret.
    delivery: str
    expires_in_hours: int


@router.get(
    "/tenants",
    response_model=list[TenantSummary],
    openapi_extra=permission_meta("admin:tenants"),
    # NOT "the client health overview" any more. This is the client DIRECTORY — the
    # roster, with the counters an operator wants beside a name — and it carried that
    # other title while nothing else did. `GET /v1/admin/client-health` is the health
    # overview now (`admin/health.py`), and it answers a different question: not "who are
    # my clients" but "which of them is about to churn or break". Two surfaces sharing
    # one name is how a reader ends up on the wrong one.
    summary="Client directory — every account, with the counters that sit beside a name",
)
async def list_tenants(
    session: AdminSession, _: Principal = Depends(requires("admin:tenants", realm="admin"))
) -> list[TenantSummary]:
    return [TenantSummary.model_validate(row) for row in await service.tenant_overview(session)]


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantSummary,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client's directory record — the detail screen should not fetch the list",
)
async def get_tenant(
    tenant_id: UUID,
    session: AdminSession,
    _: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> TenantSummary:
    rows = await service.tenant_overview(session, tenant_id=tenant_id)
    if not rows:
        raise ProblemError.not_found("Client")
    return TenantSummary.model_validate(rows[0])


@router.post(
    "/tenants",
    response_model=CreateOrgOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="New-client wizard step 1 — org, retention defaults, agent draft, schema",
)
async def create_tenant(
    payload: CreateOrgIn,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> CreateOrgOut:
    """The audit row is the birth transaction's LAST WRITE, not a second transaction.

    `on_created` is the hook `admin/service.py` already exposes for exactly this and
    self-serve signup already uses (`tenancy/signup.py::_audit`); the wizard was writing
    its row afterwards, on a different session, which is a second way of doing one thing
    and — when that write is the one that fails — a client account whose creation nobody
    recorded. Same transaction now: the tenant and the record of who created it commit
    together or not at all.

    The `global_db` dependency this route used to carry went with it: it existed only to
    give the second transaction a session, and a dependency nobody reads is a session
    opened per request for nothing.
    """
    # `derive_slug` REFUSES rather than inventing one when the name yields no ASCII —
    # which on a Telugu-first product is the ordinary case, not an edge one. See it for
    # what the old constant fallback did to the second client with a Telugu name.
    slug = payload.slug or service.derive_slug(payload.name)

    async def _audit(scoped: AsyncSession, tenant_id: UUID) -> None:
        await write_audit(
            scoped,
            action="admin.tenant_created",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"slug": slug, "vertical": payload.vertical_template},
        )

    created = await service.create_organization(
        name=payload.name,
        slug=slug,
        vertical_template=payload.vertical_template,
        billing_email=str(payload.billing_email) if payload.billing_email else None,
        language=payload.language,
        created_by=principal.user_id,
        on_created=_audit,
    )
    return CreateOrgOut.model_validate(created)


@router.post(
    "/tenants/{tenant_id}/invitations",
    response_model=InviteOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Wizard step 8 — single-use 72h invite (token hashed at rest)",
)
async def invite_member(
    tenant_id: UUID,
    payload: InviteIn,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> InviteOut:
    """One transaction: the key and the record of who cut it.

    The audit used to run on a separate `global_db` session AFTER the invitation had
    committed, so the failure mode was a live owner credential for a client account with
    nothing anywhere saying who issued it — the single worst row in this table to be
    missing. It is written last inside the tenant's own transaction now (`write_audit`
    appends in the caller's transaction by design, and `audit_log` is not tenant-RLS'd),
    which is what `tenancy/signup.py` and `create_tenant` above already do.

    The tenant session is not merely a scope: `invitations` is RLS'd, so this is also
    what makes `create_invitation`'s reads answer about THIS account only.

    THE LINK IS MAILED HERE AND NOT HANDED BACK (D-198). This route is the twin of
    `tenancy/routes.py::invite_member`, which D-190 moved onto the mailer; this one kept
    returning the raw token and sending nothing, so the wizard displayed a live owner
    credential and the invitee heard from nobody. The enqueue is in the SAME transaction as
    the invitation row for the reason D-190 gives: an invitation committed without its mail
    is a person who is never told, and a mail sent for a row that rolled back is a link that
    does not work.
    """
    async with tenant_session(tenant_id) as scoped:
        invitation_id, token = await service.create_invitation(
            scoped,
            tenant_id=tenant_id,
            email=str(payload.email),
            role=payload.role,
            created_by=principal.user_id,
        )
        await enqueue_invitation_email(scoped, to=str(payload.email), token=token)
        await write_audit(
            scoped,
            action="admin.invitation_created",
            actor=principal,
            tenant_id=tenant_id,
            object_type="invitation",
            object_id=str(invitation_id),
            ip=client_request_ip(request),
            # The email is redacted by the audit summary sanitizer; the ROLE is what a
            # later review actually needs.
            summary={"role": payload.role},
        )
    return InviteOut(
        id=invitation_id,
        delivery="queued",
        expires_in_hours=int(service.INVITE_TTL.total_seconds() // 3600),
    )


class PendingInviteOut(BaseModel):
    """One live key to a client's account, as the console may see it.

    MASKED, like the client realm's own list: `email` is in
    `scripts/check_redaction_exposure.py`'s `RAW_PII_FIELDS`, and an operator deciding
    which pending invite to cancel needs to RECOGNISE it, not to read it. Same mask, same
    function (`members.mask_email`), so the two realms cannot show a client's staff two
    different renderings of one row.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    email_masked: str
    role: str
    invited_at: datetime
    expires_at: datetime


@router.get(
    "/tenants/{tenant_id}/invitations",
    response_model=list[PendingInviteOut],
    openapi_extra=permission_meta("org:read"),
    summary="Invitations to this account that can still be redeemed",
    description=(
        "The keys to this client's account that exist in somebody's inbox right now. "
        "Addresses are masked. This is what makes the duplicate refusal actionable: "
        "minting a second live token for one address is refused, and an operator who did "
        "not issue the first one needs to be able to see and cancel it."
    ),
)
async def list_tenant_invitations(
    tenant_id: UUID,
    # The same ceiling as the client-realm twin, `GET /v1/invitations` (D-302): one
    # question, one bound, so an operator and the client are reading the same list.
    limit: int = Query(200, ge=1, le=200),
    principal: Principal = Depends(requires("org:read", realm="admin")),
) -> list[PendingInviteOut]:
    """`org:read`, NOT `admin:tenants`, and `tests/impersonation_reads_test.py` is why.

    D-22 forbids gating a GET on a permission read-only impersonation refuses, and
    `admin:tenants` is in `MUTATING_PERMISSIONS` — so gating this read on it would hide
    "who currently holds a key to this account" from a support session looking at exactly
    that. `list_unfinished_onboardings` above states the same rule for the same reason;
    the mint and the cancel keep `admin:tenants`, because handing out or destroying a
    credential is the separate thing.

    The addresses are masked, which is what makes the read safe to widen: an operator
    recognises a row, they do not read it.

    Runs in the tenant's own RLS scope, so a tenant id that names nothing can never see
    another account's invitations — but an empty list is NOT the right answer to one
    either, and it used to be. "No key to this account is outstanding" is the exact claim
    this endpoint exists to make actionable, and on a mistyped id it was made about
    nobody, next to a mint control that answers 404 for the same id
    (`assert_account_open`). One screen, two verdicts on whether the client exists.
    """
    del principal
    from apps.api.db.session import tenant_session
    from apps.api.tenancy import members as members_service

    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        rows = await members_service.list_pending_invitations(scoped, limit=limit)
    return [
        PendingInviteOut(
            id=row.id,
            email_masked=row.email_masked,
            role=row.role,
            invited_at=row.invited_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]


@router.delete(
    "/tenants/{tenant_id}/invitations/{invitation_id}",
    status_code=204,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Revoke an unused invitation from the console (the wizard's way out)",
    description=(
        "Deletes an invitation that has not been redeemed, so a fresh one can be issued "
        "for the same address. An invitation accepted between the click and the request "
        "is NOT deleted — the CAS on `used_at IS NULL` answers 404, because the person is "
        "now a member and removing them is a different act on a different surface."
    ),
)
async def revoke_tenant_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> None:
    """The admin half of `DELETE /v1/invitations/{id}`, which is client-realm.

    It has to exist HERE rather than being reached by impersonation for two reasons that
    both come from decisions already made: D-22 makes an impersonating session read-only,
    so a revoke is refused through it; and the account this matters most for has no
    member yet — the wizard's owner invite is minted before anybody can sign in, so the
    client-realm control has nobody to press it.

    The same `members_service.revoke_invitation` does the work, in the tenant's own RLS
    scope, so an id belonging to another tenant is invisible and answers 404 rather than
    confirming it exists (D-65). 204: there is nothing to say about a row that is gone,
    and the caller already knows which id it asked about.

    The DELETE and its audit row share one transaction, for the reason `invite_member`
    above gives: the row is deleted rather than flagged, so `audit_log` is the ONLY
    record that this key ever existed, and a separate transaction is a way for it not to
    be written.
    """
    from apps.api.tenancy import members as members_service

    async with tenant_session(tenant_id) as scoped:
        role = await members_service.revoke_invitation(scoped, invitation_id)
        await write_audit(
            scoped,
            action=f"admin.invitation_revoked:{role}",
            actor=principal,
            tenant_id=tenant_id,
            object_type="invitation",
            object_id=str(invitation_id),
            ip=client_request_ip(request),
        )


class IntakeOut(BaseModel):
    """What the step did, not what it was told.

    `regenerated=false` means the answers matched what the agent already carries and no
    prompt version was minted — the honest result of an operator reopening the step and
    saving it unchanged, and the one FLOWS §1's "every step idempotent" asks for.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    prompt_version: int | None
    regenerated: bool
    kb_source_id: UUID | None
    # Whether the compiled facts are sitting in the DRAFT script rather than in the one
    # callers hear. True only when a hand-written script edit was already waiting behind
    # "Apply to live calls" — the facts join it there instead of dragging it live
    # (SURFACES §2b, the exception `agents/t0.py` states). NOT optional and NOT
    # defaulted: a field with a default generates an optional TypeScript property, and
    # a screen is then free to omit the one sentence that stops an operator reading
    # `prompt_version` as "these facts are on the phone line now".
    staged_behind_script: bool


class IntakeStateOut(BaseModel):
    """What reopening the step prefills, now that the answers have a durable home
    (`organizations.intake`, migration c1f3a7d92b46).

    `prose_answers` carries the fields the operator typed — branches, services, FAQs,
    staff, booking rules — rather than the sentence compiled out of them; it is `None`
    for an org whose last submit predates the column, where the compiled block is still
    the only record of the prose. Escalation contacts stay in their own key and out of
    `prose_answers`: they are phone numbers, and keeping them in one place keeps the
    two copies from disagreeing."""

    model_config = ConfigDict(extra="forbid")

    business_hours: dict[str, dict[str, str] | None]
    escalation_contacts: list[dict[str, str | None]]
    # The EXTRA languages (DATA-MODEL §3) — never the whole set, which is why
    # `language_primary` sits beside it.
    languages: list[str]
    prose_answers: intake.IntakeProse | None
    compiled_t0_context: str | None
    submitted_at: datetime | None
    # When the sheet was last written by EITHER path. `saved_at > submitted_at` is
    # "there is a draft the agent has not been rebuilt from" — the state FLOWS §1's
    # "resume anytime" is about, and one no other field can express.
    saved_at: datetime | None
    # The agent's own primary. Without it `languages` is unrenderable by anyone who did
    # not just choose the primary themselves — see `read_intake` for the full argument.
    language_primary: str
    # Which agent the stored answers were last written through (provenance, not
    # ownership: the sheet is per-ORG, the compile is per-agent). `None` for a
    # pre-migration org that has no sheet.
    sheet_agent_id: UUID | None


class IntakeDraftOut(BaseModel):
    """What a draft save did: it stored the sheet, and here is what is still missing.

    No `prompt_version` and no `kb_source_id` — not "null", ABSENT — because a draft
    mints neither, and a nullable field would invite a screen to render "prompt version:
    —" beside a save that was never supposed to touch the prompt.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    # `submission_blockers`' codes, in the server's vocabulary, so the sentence beside
    # the Save button and the sentence in a later `intake_incomplete` refusal name one
    # condition. An empty list means the next submit would be accepted — it does NOT
    # mean anything has been compiled.
    blockers: list[str]


@router.post(
    "/tenants/{tenant_id}/agents/{agent_id}/intake",
    response_model=IntakeOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Wizard step 3 — the client's business facts (FLOWS §1 step 3)",
    description=(
        "Compiles the answers into the agent's [T0 FACTS] block, stores the block as "
        "`prompt_versions.compiled_t0_context` (D-39), seeds the knowledge base with "
        "the same facts awaiting approval, and re-publishes a live agent. Idempotent: "
        "unchanged answers mint no new prompt version."
    ),
)
async def record_intake(
    tenant_id: UUID,
    agent_id: UUID,
    payload: intake.IntakeFacts,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> IntakeOut:
    """Admin realm, tenant in the PATH, work inside `tenant_session` — the house
    pattern for an admin mutation (D-22; `route_shape_test` pins the general rule).

    `agents:write` rather than `admin:tenants`: what this endpoint ultimately changes is
    the agent's prompt and knowledge, which is the same authority the publish and KB
    approval routes above carry.
    """
    async with tenant_session(tenant_id) as scoped:
        result = await intake.record_intake(
            scoped,
            tenant_id=tenant_id,
            agent_id=agent_id,
            facts=payload,
            recorded_by=principal.user_id,
        )
    await write_audit(
        session,
        action="agent.intake_recorded",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        # COUNTS, never the answers: services and FAQs are the client's business detail
        # and the escalation contacts are phone numbers (hard rule 6).
        summary={
            "regenerated": result["regenerated"],
            "prompt_version": result["prompt_version"],
            "services": len(payload.services),
            "faqs": len(payload.faqs),
        },
    )
    return IntakeOut.model_validate(result)


@router.post(
    "/tenants/{tenant_id}/agents/{agent_id}/intake/draft",
    response_model=IntakeDraftOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Wizard step 3 — save the answers as they stand (FLOWS §1, 'resume anytime')",
    description=(
        "Stores a PARTIAL intake sheet and does nothing else: no compiled block, no "
        "prompt version, no knowledge-base seed, no publish. Answers a half-filled form "
        "with 200 and the list of what still blocks a submit; answers a malformed one "
        "with 422, the same way the submit does. Saving a draft never makes an agent "
        "ready — the submit is still gated on the full set."
    ),
)
async def save_intake_draft(
    tenant_id: UUID,
    agent_id: UUID,
    payload: intake.IntakeFacts,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> IntakeDraftOut:
    """FLOWS §1's "draft state saved at every step (resume anytime)", which had a service
    function and no way in from a browser — so the only reachable write ran the
    submission gate first and a half-finished intake could not be persisted at all.

    **The line between STRUCTURAL and COMPLETENESS validation, which is the whole design
    of this route.** It takes the SAME `intake.IntakeFacts` body model as the submit, so
    every structural rule still applies to a draft: `extra="forbid"`, the `HH:MM` and
    E.164 and price patterns, the length caps, the list maxima. A draft is a form
    half-filled, never a form filled in wrongly — and the reason is not tidiness, it is
    that `read_intake` parses the stored sheet back through this same model on the way
    out. A sheet that went in unvalidated comes back as `intake_sheet_unreadable` and
    the resume silently degrades to a blank form, which is the exact §52 failure this
    slice exists to prevent: the operator retypes and overwrites.
    What is NOT applied is `submission_blockers` — missing hours, no address, no service,
    no escalation contact. Those are completeness, they are what a draft is FOR, and
    gating on them would make the route useless for its only purpose. They come back in
    the response instead, as information.

    **`agents:write`, matching the submit and the rest of the wizard**, because this
    writes the client's answers onto their org row; there is no weaker authority under
    which a partial write is more acceptable than a whole one.

    **Audited.** The submit's row records what was compiled; this one records that an
    operator wrote a client's answers, which is a change to tenant data whoever made it.
    Counts only, never the answers (hard rule 6). This is affordable because the console
    saves DELIBERATELY — one press, not one per keystroke. An autosave landing on this
    route would grow the hash-chained log per debounce interval, and the choice to audit
    would have to be revisited with it.
    """
    async with tenant_session(tenant_id) as scoped:
        result = await intake.save_intake_draft(
            scoped, tenant_id=tenant_id, agent_id=agent_id, facts=payload
        )
    await write_audit(
        session,
        action="agent.intake_drafted",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        # COUNTS and CODES, never the answers: the same rule the submit's row follows,
        # and the escalation contacts on this sheet are phone numbers.
        summary={
            "blockers": len(result["blockers"]),
            "services": len(payload.services),
            "faqs": len(payload.faqs),
        },
    )
    return IntakeDraftOut.model_validate(result)


@router.get(
    "/tenants/{tenant_id}/agents/{agent_id}/intake",
    response_model=IntakeStateOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Reopen the intake step — what is durably stored, and only that",
)
async def read_intake(
    tenant_id: UUID,
    agent_id: UUID,
    _: Principal = Depends(requires("agents:read", realm="admin")),
) -> IntakeStateOut:
    """No `AdminSession`: this reads one tenant's own rows, so it enters that tenant's
    scope directly rather than opening the cross-tenant directory it does not need."""
    async with tenant_session(tenant_id) as scoped:
        state = await intake.read_intake(scoped, agent_id=agent_id)
    return IntakeStateOut.model_validate(state)


class UnfinishedOnboardingOut(BaseModel):
    """One account the wizard can be resumed on — the account, never anyone at it."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str
    slug: str
    # Where to resume: the agent the answers were written through, or the account's
    # draft receptionist. The wizard addresses step 3 by (tenant, agent), so a row
    # without this would be a link the operator has to complete by guessing.
    agent_id: UUID
    created_at: datetime
    # `null` = the intake step was never opened. Distinct from "opened and left partly
    # answered", which is what a timestamp here means, and the two want different
    # actions — so no zero, no "—", no invented "never".
    draft_saved_at: datetime | None
    # `submission_blockers`' codes for what IS stored. The evidence for the word
    # "unfinished", in the same vocabulary the step itself prints.
    blockers: list[str]


@router.get(
    "/onboarding/unfinished",
    response_model=list[UnfinishedOnboardingOut],
    openapi_extra=permission_meta("org:read"),
    summary="Onboardings started and not finished — where a wizard resumes (FLOWS §1)",
    description=(
        "Every account still in onboarding whose intake has never been submitted, most "
        "recently worked on first, with the agent to resume at and what is still "
        "missing. Read-only: resuming is a draft save or a submit on the account's own "
        "route."
    ),
)
async def list_unfinished_onboardings(
    session: AdminSession,
    principal: Principal = Depends(requires("org:read", realm="admin")),
) -> list[UnfinishedOnboardingOut]:
    """The other half of "draft state saved at every step (resume anytime)".

    A draft that can be written and not FOUND is resumable only by an operator who
    still has the tab open, which is the one case a draft is not for. This is where
    "which onboardings are unfinished" is answerable without opening a database.

    **Why here and not on the tenant directory.** The directory (`/v1/admin/tenants`)
    is the roster — every account, with counters beside a name — and it deliberately
    "stays dumb: counts, not judgements" (`admin.service.tenant_overview`). Unfinished
    onboardings are a WORK LIST: a small, shrinking set, ordered by recency of work,
    carrying per-row blockers that mean nothing to the other 90% of the roster. Putting
    them on the directory would either add four columns every finished client renders
    empty, or hide them behind a filter nobody sets. It is also the wrong PLACE: the
    operator resuming an onboarding is doing the thing "New client" does, so this list
    is rendered on `/admin/new` itself and the wizard picks up from the row's ids — one
    screen for starting and continuing the same task, rather than a fourth place to
    look. The precedent is `holds_routes.py`, which is the same shape (a bounded ops
    work list with its own rule codes) for the same reason.

    **`org:read`, not `admin:tenants`.** D-22 forbids gating a GET on a permission
    read-only impersonation refuses, and this is a read. Resuming still requires
    `agents:write` at the routes that write.
    """
    del principal  # the dependency IS the authorization; the identity is not needed
    return [
        UnfinishedOnboardingOut(
            tenant_id=row.tenant_id,
            name=row.name,
            slug=row.slug,
            agent_id=row.agent_id,
            created_at=row.created_at,
            draft_saved_at=row.draft_saved_at,
            blockers=list(row.blockers),
        )
        for row in await intake.unfinished_onboardings(session)
    ]


def view_as_confirmation(slug: str) -> str:
    """The step-up string for ENTERING one client's account (D-210).

    A named function for the reason `spend_ceiling_confirmation` gives: it is part of an
    operator procedure, so changing its shape has to be a deliberate edit that fails a
    test rather than a reformat that leaves the console sending a header the API refuses.

    Bound to the SLUG rather than the tenant id, which is the one place this differs from
    its siblings, and the route's own reasoning is why: the mint is addressed by slug
    precisely so the console never has to resolve an id it does not hold, and building the
    confirmation from the id would reintroduce that lookup on the one caller the route was
    shaped around. What the binding has to stop is a confirmation captured while entering
    one client being replayed against another, and the slug is unique among live tenants
    (`uq_organizations_slug`), so it does that. The IMMUTABLE id remains what the grant
    itself is bound to — a five-minute echo and a fifteen-minute authorisation do not need
    the same handle.
    """
    return f"view_as:{slug}"


class ImpersonationGrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The tenant to view, by SLUG — the same handle `X-Impersonate-Org` carries, the
    #: same one client URLs use (D-10), and the only one every console call site holds.
    #: See the route for why the grant is addressed by slug and bound to the id.
    slug: str = Field(min_length=1, max_length=100)

    #: The grant this one CONTINUES, if the console already holds a live one for this
    #: tenant (D-210). Present it and no second factor is asked for; omit it, or present
    #: one that has run out of window, and the step-up gate applies.
    #:
    #: IN THE BODY RATHER THAN IN `X-Impersonation-Grant`, deliberately. That header means
    #: "this request is being made INSIDE the named tenant" and `core/auth.py` reads it
    #: with `X-Impersonate-Org` beside it; a mint is made from the operator's own admin
    #: session and is not inside anything. Reusing the header would make the mint the one
    #: request where it means something else. RFC 8693, whose claim shape this grant
    #: already borrows, carries the token being exchanged in the request body for the same
    #: reason — it is an input to the exchange, not a credential for it.
    renew: str | None = Field(default=None, max_length=4096)


class ImpersonationGrantOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Echoed so the caller can be sure the session it caches is the one it asked for.
    slug: str
    #: The wire form of the grant, for `X-Impersonation-Grant`. Opaque to the console.
    grant: str
    #: When it stops being accepted. The console re-mints shortly before this rather
    #: than discovering the expiry as a failed request in front of an operator.
    expires_at: datetime


@router.post(
    "/impersonation-grants",
    openapi_extra=permission_meta("admin:impersonate"),
    summary="Mint the short-lived grant a READ-ONLY view-as session needs (D-22)",
    description=(
        "Begins a read-only 'view as client' session and returns the grant that "
        f"authorises it. Send it as `{IMPERSONATION_GRANT_HEADER}` alongside "
        f"`{IMPERSONATE_HEADER}: <slug>` on every request into that account; without it "
        "the request is refused. The grant is bound to this operator and this tenant, "
        "expires in minutes, and never authorises a mutation — an impersonating session "
        "is read-only, and writes go through the admin surfaces with the tenant in the "
        "path.\n\n"
        "STARTING a view-as session needs step-up: a second factor proved in the last "
        "five minutes AND the header `X-Confirm-Action: view_as:<slug>`. EXTENDING one "
        "does not — send the grant currently held as `renew` and it is continued, for up "
        "to an hour from the second factor that started it."
    ),
)
async def mint_impersonation_grant(
    payload: ImpersonationGrantIn,
    session: AdminSession,
    request: Request,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    principal: Principal = Depends(requires("admin:impersonate", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> ImpersonationGrantOut:
    """Issue one grant, and record that authority was issued.

    **This route replaced `POST /tenants/{tenant_id}/impersonate`, which minted nothing.**
    That endpoint wrote `admin.impersonation_started` and handed back the header name;
    entry to a tenant was the header alone, so nothing forced an operator through it and
    the console never called it. The row was therefore absent for every real session —
    D-22's "session start ... audit-logged" was decorative. `core/auth.py` now refuses
    any impersonated request without a grant, so the row cannot be skipped: a grant
    cannot exist without it.

    **Addressed by SLUG, bound to the ID.** The tenant-in-the-path convention exists so
    an admin WRITE names its target unambiguously in the audit log; this creates no
    tenant data, and its caller is the browser, which holds a slug everywhere view-as is
    initiated (including `/c/<slug>?view=admin`, where no id is in scope at all). Making
    the console resolve an id to ask for a grant that resolves it back would be a lookup
    invented for one caller. What matters for safety is the BINDING, and that is the
    immutable id: `core/impersonation.py` puts `organizations.id` in the grant and
    compares it against the id the request's slug resolves to.

    **An impersonating session may not mint.** RFC 8693 allows chained delegation
    (nested `act`); we do not, and this is where that is refused rather than merely
    unimplemented. `admin:impersonate` is deliberately not a mutating permission — D-22
    forbids gating reads on one — so `requires()` would not have caught it.

    ═══ STEP-UP, AND WHY IT IS ON THE DOOR RATHER THAN ON EACH READ (D-210) ═══

    BACKEND-PATTERNS §7 names raw-transcript access a step-up action. The route that
    serves it is `GET /v1/calls/{id}/transcript/raw` on the CLIENT realm, and the only way
    an operator reaches it is through here — `_load_admin_principal` refuses every
    impersonated request without a grant, and grants exist only at this endpoint. So this
    is where the second factor belongs: one gate on the door an operator walks through,
    rather than a freshness check bolted onto each of the tenant-realm reads behind it,
    which would put an admin-realm concern in a module that has no admin-realm session to
    read it from (`authn/stepup.py::STEP_UP_REALM`).

    **This does not gate a read on a mutating permission.** D-22's rule is about
    PERMISSIONS — `admin:impersonate` stays out of `MUTATING_PERMISSIONS`, so a view-as
    session still buys nothing but reads. Step-up is orthogonal to that: it asks who is at
    the keyboard, not what they may do.

    **Renewal rides, entry does not.** A console holding a live grant for this tenant
    sends it back as `renew` and is not challenged again; `core/impersonation.py`'s
    `VIEW_AS_MAX_AGE` bounds the whole chain at an hour from the ONE step-up that started
    it. Demanding a fresh factor on every mint instead would mean an emailed code roughly
    every fourteen minutes — see `VIEW_AS_MAX_AGE` for why that is the design that gets
    switched off, and for the AWS STS precedent this follows instead.

    **The refusal executes nothing.** Both refusals happen before `mint_grant` and before
    `write_audit`, so a caller that is sent away to prove a factor has changed no state and
    left no start row — which is what lets the console retry the identical request once the
    operator has answered the code.
    """
    if principal.impersonating:
        raise ProblemError.forbidden(
            "Start view-as from the operator console, not from inside another account."
        )
    admin_id = principal.user_id
    if admin_id is None:
        # Unreachable: `current_admin` resolves an `admin_users` row or refuses. Stated
        # rather than asserted so a future change to Principal cannot make it silent.
        raise ProblemError.forbidden("This account has no admin access.")

    tenant_id = (
        await session.execute(
            text("SELECT id FROM organizations WHERE slug = :slug AND deleted_at IS NULL"),
            {"slug": payload.slug},
        )
    ).scalar()
    if tenant_id is None:
        raise ProblemError.not_found("Organization")

    now = datetime.now(UTC)
    renewed = renewable_grant(
        payload.renew, admin_id=admin_id, tenant_id=UUID(str(tenant_id)), now=now
    )
    if renewed is not None:
        auth_time = renewed.auth_time
    else:
        step_up.require(x_confirm_action, view_as_confirmation(payload.slug))
        # `verified_at` is the instant the second factor was proved, and `require` has just
        # established it is inside `REAUTH_MAX_AGE`. It is `None` only on the local
        # `dev:` branch that `require` waves through (`APP_ENV=local` with no
        # `PLATFORM_KEK`), where there is no session row to carry one — `now` there means
        # the window starts at this request, which is the strictest reading available.
        auth_time = step_up.verified_at or now

    token, grant = mint_grant(
        tenant_id=UUID(str(tenant_id)), admin_id=admin_id, auth_time=auth_time
    )
    # In the SAME transaction as nothing else: the row is the whole side effect, and it
    # commits with the response. A grant handed out whose start row rolled back is the
    # exact defect this route exists to remove.
    await write_audit(
        session,
        action="admin.impersonation_started",
        actor=principal,
        tenant_id=grant.tenant_id,
        object_type="organization",
        object_id=str(grant.tenant_id),
        ip=client_request_ip(request),
        # `grant_id` is what joins this row to the `admin.impersonation_read` rows the
        # session goes on to produce (`core/auth.py`). Ids and instants only.
        #
        # `renews` carries the PREDECESSOR'S grant id, so the ledger says which start rows
        # are one view-as session extending itself and which are an operator walking
        # through the door again — the difference between four entries an hour and four
        # entries an hour that each cost a second factor. `auth_time` dates the step-up
        # the whole chain rests on, which is the field an auditor asking "was this
        # session ever re-authenticated?" actually needs.
        summary={
            "grant_id": str(grant.grant_id),
            "expires_at": grant.expires_at.isoformat(),
            "ttl_s": int(GRANT_TTL.total_seconds()),
            "auth_time": grant.auth_time.isoformat(),
            "renews": str(renewed.grant_id) if renewed is not None else None,
            "window_s": int(VIEW_AS_MAX_AGE.total_seconds()),
        },
    )
    return ImpersonationGrantOut(slug=payload.slug, grant=token, expires_at=grant.expires_at)


# --- Knowledge base: the MUTATING half (FLOWS §7) ------------------------------
# These live on the admin router, not the client one, because of D-22: an admin
# reaching a tenant does so by impersonation, and impersonation is read-only. The
# tenant is therefore named in the path rather than inferred from a session, which
# also makes every approval self-documenting in the audit log.


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class KbReviewOut(BaseModel):
    """The review verdict, as a DECLARED model rather than a `dict[str, str]` (D-303).

    These two handlers returned a bare mapping, which is not a shape — it is the absence
    of one. Three things read a response model and none of them can read a mapping:
    `scripts/check_redaction_exposure.py` walks response models and is structurally blind
    to a route that declares none, the generated TypeScript client renders it as an index
    signature so the frontend hand-writes its own interface, and BACKEND-PATTERNS §1's
    "the response model IS the output whitelist" has nothing to whitelist. Nothing leaked
    here — the value is a literal three lines below — but the guardrail could not have
    said so, which is the same argument `tests/response_shape_test.py` already made for
    the panels.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected"]


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    version: int
    status: str


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/approve",
    response_model=KbReviewOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Approval gate (D-28: stays ours whichever RAG provider wins)",
    description=(
        "Approve a submitted knowledge source. Idempotent: approving a source that is "
        "already approved returns 200 and changes nothing — the first reviewer stays "
        "the recorded approver. 409 means the source is in another state (rejected, "
        "archived) and the response names it. 404 means this tenant has no source with "
        "that id."
    ),
)
async def approve_kb(
    tenant_id: UUID,
    source_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> KbReviewOut:
    """Approve, and audit ONLY a real approval.

    A repeat is a success but not a second `kb.approved` row: the audit log answers
    "who let this text reach the agent, and when", and a row per button press makes
    that question harder to answer, not easier. `integrations/routes.py::
    deactivate_endpoint` and `tenancy.members` make the same call for the same reason.
    """
    async with tenant_session(tenant_id) as scoped:
        approved = await kb_service.approve_source(
            scoped, source_id=source_id, approved_by=principal.user_id
        )
    if approved:
        await write_audit(
            session,
            action="kb.approved",
            actor=principal,
            tenant_id=tenant_id,
            object_type="kb_source",
            object_id=str(source_id),
            ip=client_request_ip(request),
        )
    return KbReviewOut(status="approved")


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/reject",
    response_model=KbReviewOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Refuse a submitted source, with a reason the client can act on",
    description=(
        "Reject a submitted knowledge source. Idempotent: rejecting an already-rejected "
        "source returns 200 and keeps the reason the first reviewer gave. 409 means the "
        "source is in another state (approved, archived) and the response names it. 404 "
        "means this tenant has no source with that id."
    ),
)
async def reject_kb(
    tenant_id: UUID,
    source_id: UUID,
    payload: RejectIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> KbReviewOut:
    """Reject, and audit ONLY a real rejection — see `approve_kb` for why."""
    async with tenant_session(tenant_id) as scoped:
        rejected = await kb_service.reject_source(
            scoped, source_id=source_id, reason=payload.reason
        )
    if rejected:
        await write_audit(
            session,
            action="kb.rejected",
            actor=principal,
            tenant_id=tenant_id,
            object_type="kb_source",
            object_id=str(source_id),
            ip=client_request_ip(request),
            summary={"reason": payload.reason},
        )
    return KbReviewOut(status="rejected")


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/publish",
    response_model=PublishOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Push to the engine KB and make this the active version",
    description="Rollback is republishing an earlier version (FLOWS §7).",
)
async def publish_kb(
    tenant_id: UUID,
    source_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> PublishOut:
    async with tenant_session(tenant_id) as scoped:
        version = await kb_service.publish_source(scoped, tenant_id=tenant_id, source_id=source_id)
    await write_audit(
        session,
        action="kb.published",
        actor=principal,
        tenant_id=tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=client_request_ip(request),
        summary={"version": version},
    )
    return PublishOut(source_id=source_id, version=version, status="live")


class TierSplitOut(BaseModel):
    """The margin's cost side, split by the TTS rung each minute was metered on (D-36).

    Nested inside the margin card rather than mounted as its own route because it answers
    a question about THAT card's `cost_inr`: an operator seeing a thin margin needs to
    know whether the cost is premium voice or the value rung before they can act on it,
    and a second endpoint means a second round trip to learn one number's composition.
    `billing.tier_usage` sums to the same `_tier_totals` the margin does, so the rungs
    add up to `cost_inr` exactly — they are a partition of it, not a parallel estimate.

    `unattributed` is the honest third bucket: rows a path could not attribute a rung to.
    It is reported separately because "we know this ran on the value rung" and "we never
    knew" are different facts, and a bill resolves that ambiguity in the CLIENT's favour
    (`minutes_billable_value` folds it in) while this report must not.

    Every field is required on the wire. A Pydantic default here would generate an
    OPTIONAL TypeScript property and the screen would have to branch on a case the
    server never emits — a trap this repo has now been bitten by four times.
    """

    model_config = ConfigDict(extra="forbid")

    minutes_premium: str
    minutes_value: str
    minutes_unattributed: str
    cost_premium_inr: str
    cost_value_inr: str
    cost_unattributed_inr: str


class MarginOut(BaseModel):
    """Per-client margin (D-12).

    Every money field is a STRING: the values are `Decimal` (hard rule 7) and the route
    stringifies them at the boundary, because a JSON float cannot hold a rupee amount
    exactly. They must stay strings all the way to the screen.
    """

    model_config = ConfigDict(extra="forbid")

    month: str
    minutes_used: str
    calls: int
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    # None rather than "0.0" when nothing has been billed: "0% margin" and "nothing
    # billed yet" are different facts, and an operator acts differently on each.
    margin_pct: str | None
    tiers: TierSplitOut


@router.get(
    "/tenants/{tenant_id}/margin",
    response_model=MarginOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Revenue vs OUR cost for one client (D-12) — the number G2 gates on",
)
async def tenant_margin(
    tenant_id: UUID,
    session: AdminSession,
    month: str | None = None,
    _: Principal = Depends(requires("billing:read", realm="admin")),
) -> MarginOut:
    """Admin realm only. `unit_cost_paid` is our supplier pricing — it is the reason
    this lives here and not beside the client's usage panel.

    Runs under a tenant-scoped session because `usage_events` is RLS'd and stays that
    way: `app.admin` opens the client DIRECTORY, never their data (migration
    b57e2f9c4a13). An operator reads one client's numbers by entering that client's
    scope deliberately, exactly like impersonation does for pages.
    """
    async with tenant_session(tenant_id) as scoped:
        # A tenant with no usage and a tenant that does not exist both aggregate to
        # zero, so without this the mistyped id came back as a clean ₹0 margin card —
        # a number about a client, computed from nothing, on the read D-12 says G2
        # gates on. `read_credits` and `tenant_invoice`, the other two money reads on
        # this screen, already answer 404 here.
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        margin = await billing.margin_for_tenant(scoped, tenant_id=tenant_id, month=month)
        # Asked for the month the MARGIN resolved, never the request's `month` — that
        # argument is None on the common call and the two reads would then be free to
        # land either side of a month boundary, publishing a cost total and a rung split
        # for different months on one card.
        tiers = await billing.tier_usage(scoped, tenant_id=tenant_id, month=str(margin["month"]))
    del session
    flat = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in margin.items()}
    # Projected through the response model's OWN field list rather than a prefix filter:
    # `tier_usage` also returns `month` (already on the card) and the two
    # `minutes_billable_*` figures, which are a PRICING rule and not a partition of
    # `cost_inr` — publishing them beside it would invite a reader to reconcile two
    # things that are not meant to add up. Naming the fields once means a field added to
    # either side is a KeyError here, not a silently missing tile.
    flat["tiers"] = {name: str(tiers[name]) for name in TierSplitOut.model_fields}
    return MarginOut.model_validate(flat)


# --------------------------------------------------------- campaign prerequisites
#
# Numbers and DLT templates are what the campaign launch gate checks (SEC-COMP §3),
# and both are OUR operational work: we buy the number, we file the template with the
# registrar under the client's PE. The client realm can read them (to pick one) but
# never write them — a client who could mark their own template "approved" would be
# launching under a registration that does not exist.


class ProvisionNumberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    e164: str = Field(min_length=8, max_length=20, pattern=r"^\+[1-9]\d{7,18}$")
    # The series decides what the number may lawfully dial (DATA-MODEL §6).
    series: Literal["140", "160", "standard"]
    agent_id: UUID | None = None
    provider: str | None = Field(default=None, max_length=60)
    purpose: str | None = Field(default=None, max_length=120)


class NumberCreatedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    e164: str
    series: str
    dlt_status: str


class DltStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dlt_status: Literal["pending", "registered", "blocked"]


class NumberDltStatusOut(BaseModel):
    """What the number's DLT status is now — declared, for `KbReviewOut`'s reasons."""

    model_config = ConfigDict(extra="forbid")

    dlt_status: Literal["pending", "registered", "blocked"]


class RegisterTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["promotional", "transactional", "service"]
    body: str = Field(min_length=10, max_length=2000)
    dlt_ref: str | None = Field(default=None, max_length=120)


class TemplateStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "submitted", "approved", "rejected"]
    dlt_ref: str | None = Field(default=None, max_length=120)


class TemplateRegisteredOut(BaseModel):
    """The template we just filed, and the ONE status a registration may start in."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: Literal["submitted"]


class TemplateStatusOut(BaseModel):
    """The registrar's verdict as recorded — declared, for `KbReviewOut`'s reasons."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "submitted", "approved", "rejected"]


class DltRegistrationIn(BaseModel):
    """What the registrar says about THIS CLIENT's Principal Entity (SEC-COMP §3).

    Two statuses rather than one `ready` flag, because they fail separately and the
    next action differs: an unregistered entity is a ₹5,900 registration we execute for
    them, a missing TM link is an authorisation only they can grant. The launch gate
    names them separately for the same reason.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_started", "submitted", "active", "suspended", "rejected"]
    tm_link_status: Literal["not_linked", "pending", "active", "revoked"]
    # The registrar's PE id. Required for `active` by a DB CHECK — an active
    # registration that cannot say which registration it is, is a claim, not a fact.
    pe_id: str | None = Field(default=None, max_length=120)
    entity_name: str | None = Field(default=None, max_length=200)
    registered_at: datetime | None = None


class KycRecordIn(BaseModel):
    """What an operator recorded after verifying a business's identity (R-11).

    Deliberately NOT a document upload. Indian business-connection KYC is satisfied
    against the entity's registry documents (DoT's Aug-2023/May-2024 business-connection
    instructions — see `apps/api/compliance/kyc.py` for the sources), and the documents
    themselves belong with the licensee's Customer Acquisition Form, not in our
    database. What we keep is the REFERENCE: which registry, which identifier, who
    signed, and where the pack is filed. There is no field here that could carry an
    Aadhaar or a personal PAN, and a DB CHECK stands behind that.

    `verified_at` is absent on purpose and is stamped by the database. An operator who
    could supply the date a verification happened could supply any date, and the whole
    value of that column to an auditor is that it records when the system observed the
    fact — `dlt_registrations.verified_at` means the same thing for the same reason.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_started", "submitted", "in_review", "verified", "rejected", "expired"]
    entity_type: (
        Literal[
            "sole_proprietorship",
            "partnership",
            "llp",
            "private_limited",
            "public_limited",
            "trust_or_society",
            "huf",
        ]
        | None
    ) = None
    # Entity registries only. Aadhaar and personal PAN are not members and never will
    # be: this record must not become a store of natural persons' identity documents.
    document_kind: (
        Literal["cin", "llpin", "gstin", "udyam", "shop_establishment", "trade_licence"] | None
    ) = None
    document_ref: str | None = Field(default=None, max_length=64)
    signatory_name: str | None = Field(default=None, max_length=200)
    # Where the verification pack lives — a ticket id or an object key, never a
    # credential and never a document.
    evidence_ref: str | None = Field(default=None, max_length=200)
    rejection_reason: str | None = Field(default=None, max_length=500)


class KycRecordOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    status: str
    document_kind: str | None
    document_ref: str | None


class DltRegistrationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    status: str
    tm_link_status: str
    pe_id: str | None


@router.post(
    "/tenants/{tenant_id}/numbers",
    response_model=NumberCreatedOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Provision a calling number — the series is the compliance-bearing field",
)
async def provision_number(
    tenant_id: UUID,
    payload: ProvisionNumberIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> NumberCreatedOut:
    """A mistyped tenant uuid is a 404, and it used to be a 409 about a NUMBER.

    `provision_number` maps every `IntegrityError` to `number_taken` ("This number is
    already provisioned — it may belong to another account"), which is the right answer
    for the UNIQUE index it was written for and the wrong one for the tenant foreign
    key. An operator who mistyped the client id was told to go looking for whoever
    holds a number nobody holds. `service.tenant_exists` is the ONE definition of "is
    this a live organization" and exists so every surface naming a tenant in its path
    answers a mistyped uuid the same way — asked here rather than the predicate copied,
    exactly as `set_tenant_status` and `record_commercial_terms` ask it.
    """
    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        number_id = await agents_service.provision_number(
            scoped,
            tenant_id=tenant_id,
            e164=payload.e164,
            series=payload.series,
            agent_id=payload.agent_id,
            provider=payload.provider,
            purpose=payload.purpose,
        )
    await write_audit(
        session,
        action="number.provisioned",
        actor=principal,
        tenant_id=tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=client_request_ip(request),
        # The series, never the number itself (hard rule 6).
        summary={"series": payload.series},
    )
    return NumberCreatedOut(
        id=number_id, e164=payload.e164, series=payload.series, dlt_status="pending"
    )


@router.post(
    "/tenants/{tenant_id}/numbers/{number_id}/dlt-status",
    response_model=NumberDltStatusOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record what the DLT registrar decided about this number",
)
async def set_number_dlt_status(
    tenant_id: UUID,
    number_id: UUID,
    payload: DltStatusIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> NumberDltStatusOut:
    async with tenant_session(tenant_id) as scoped:
        await agents_service.set_number_dlt_status(
            scoped, number_id=number_id, dlt_status=payload.dlt_status
        )
    await write_audit(
        session,
        action="number.dlt_status_set",
        actor=principal,
        tenant_id=tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=client_request_ip(request),
        summary={"dlt_status": payload.dlt_status},
    )
    return NumberDltStatusOut(dlt_status=payload.dlt_status)


@router.post(
    "/tenants/{tenant_id}/dlt-templates",
    response_model=TemplateRegisteredOut,
    openapi_extra=permission_meta("admin:tenants"),
    status_code=201,
    summary="Register a voice template — created `submitted`, never `approved`",
)
async def register_template(
    tenant_id: UUID,
    payload: RegisterTemplateIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> TemplateRegisteredOut:
    """A mistyped tenant uuid is a 404 here, and it used to be a 500.

    `dlt_templates.tenant_id` has an FK, so an id no organization holds reached the
    INSERT and came back as `internal_error` — an operator was told "the team has been
    alerted" for a typo they could fix themselves, and the team was alerted for it.
    Same guard, same predicate and same reason as `record_commercial_terms` above.
    """
    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        template_id = await campaigns_service.register_dlt_template(
            scoped,
            tenant_id=tenant_id,
            classification=payload.classification,
            body=payload.body,
            dlt_ref=payload.dlt_ref,
        )
    await write_audit(
        session,
        action="dlt_template.registered",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dlt_template",
        object_id=str(template_id),
        ip=client_request_ip(request),
        summary={"classification": payload.classification},
    )
    return TemplateRegisteredOut(id=template_id, status="submitted")


@router.post(
    "/tenants/{tenant_id}/dlt-templates/{template_id}/status",
    response_model=TemplateStatusOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Approve or reject per the registrar — `approved` unlocks the launch gate",
)
async def set_template_status(
    tenant_id: UUID,
    template_id: UUID,
    payload: TemplateStatusIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> TemplateStatusOut:
    """AUDITED, and deliberately NOT a `transition_status` state machine. Checked 2026-08.

    This is a registrar-fact RECORDER, the same species as `set_number_dlt_status` above
    and `ops.service.record_tm_registration` ("deliberately a full overwrite: there is
    one registration and this is its current state"), and it is the reason those two are
    not on `db/transition.py::transition_status` either. The three answers that module
    discriminates are already the three this endpoint gives, but the middle one is
    reached from the opposite direction and must stay that way:

    * **A different status is not a conflict — it is the news.** The registrar moves a
      template both ways, and `approved -> rejected` is a WITHDRAWAL. Constraining this
      to a `from_statuses` set would make a revocation unrecordable and leave
      `campaigns.service.launch_blockers` reading `approved` for a template the
      registrar has pulled, which is SEC-COMP §1's most common registration failure
      dialling on. `tests/campaign_dispatch_audit_test.py::
      test_a_revoked_dlt_template_stops_the_campaign_before_the_next_dial` pins exactly
      that move, and the gate's behaviour is what it pins.
    * **Absent is already a 404, never a 409.** The service raises
      `ProblemError.not_found` on `rowcount == 0`, and the UPDATE runs inside
      `tenant_session(tenant_id)`, so another tenant's template id updates no row and
      gets the same 404 an id that never existed gets (hard rule 1).
    * **Re-recording the same status is a 200 AND a real audit row**, which is the one
      place this diverges from `set_tenant_status`'s `changed` guard and does so on
      purpose: there is no state machine here to be already-satisfied. A second POST is
      an operator asserting "I checked with the registrar again just now, and it still
      says submitted". `dlt_templates` has no `verified_at` to hold that, so the audit
      row IS the record of the re-verification — the same fact `record_tm_registration`
      stamps on the row it owns.

    A single conditional UPDATE, so there is no read-then-write to race: two operators
    recording two registrar verdicts is last-writer-wins over an external fact, and the
    audit log carries both readings in order.
    """
    async with tenant_session(tenant_id) as scoped:
        await campaigns_service.set_template_status(
            scoped, template_id=template_id, status=payload.status, dlt_ref=payload.dlt_ref
        )
    await write_audit(
        session,
        action="dlt_template.status_set",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dlt_template",
        object_id=str(template_id),
        ip=client_request_ip(request),
        summary={"status": payload.status},
    )
    return TemplateStatusOut(status=payload.status)


@router.post(
    "/tenants/{tenant_id}/dlt-registration",
    response_model=DltRegistrationOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record the client's DLT Principal Entity registration and its Calevate TM link",
    description=(
        "The third registration in the same family as the number header and the voice "
        "template, and the one the campaign launch gate reads as `pe_registration_*` / "
        "`tm_link_not_active`. Upserts: re-recording is what happens every time we "
        "re-verify with the registrar."
    ),
)
async def record_dlt_registration(
    tenant_id: UUID,
    payload: DltRegistrationIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> DltRegistrationOut:
    """The operator surface `campaigns.service.record_dlt_registration` was written for.

    It shipped with no route at all — deliberately none for CLIENTS, since a client who
    could mark their own PE registration `active` would be marking the launch gate green
    on a registration that does not exist — but with nothing for OPS either, which left
    the fact settable only by hand-written SQL against production. Same family, same
    permission and same shape as `set_number_dlt_status` and `set_template_status`
    above: `admin:tenants`, tenant named in the PATH, work done inside
    `tenant_session(tenant_id)` so RLS is what isolates it.

    The tenant-in-path form is not a style choice. An admin-realm mutation that infers
    its tenant from the session is un-callable by construction (D-22 refuses every
    mutating permission while impersonating, and without the header an admin principal
    has no tenant at all) — the failure this repo has already hit twice, now pinned by
    `tests/route_shape_test.py::test_no_admin_realm_mutation_infers_its_tenant_from_the_session`.
    """
    if payload.status == "active" and not (payload.pe_id or "").strip():
        # `ck_dlt_registrations_active_registration_names_its_pe` would refuse this in
        # the database; caught here so the operator gets a problem+json naming the
        # missing field instead of a 500 out of an IntegrityError.
        raise ProblemError(
            kind="validation",
            code="pe_registration_id_required",
            title="A registration number is required",
            detail="Recording a PE registration as active needs the registrar's PE id.",
            remediation="Send pe_id with the registration number the registrar issued.",
        )
    async with tenant_session(tenant_id) as scoped:
        # A mistyped tenant uuid is a 404, not a 500 — the third member of the family
        # `register_template` and `record_kyc_verification` were fixed in (D-133), and
        # the one that was missed because it is an UPSERT rather than an INSERT and so
        # reads like a write that cannot fail. `dlt_registrations.tenant_id` carries
        # `fk_dlt_registrations_tenant_id_organizations`, and `ON CONFLICT` does not
        # excuse a foreign key: an id no organization holds reached the statement and
        # came back as `internal_error` with an operator alert attached, for a typo the
        # operator could have fixed themselves.
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        await campaigns_service.record_dlt_registration(
            scoped,
            tenant_id=tenant_id,
            pe_id=payload.pe_id,
            entity_name=payload.entity_name,
            status=payload.status,
            tm_link_status=payload.tm_link_status,
            registered_at=payload.registered_at,
        )
    await write_audit(
        session,
        action="dlt_registration.recorded",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dlt_registration",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        # The registrar's identifiers are the client's own business identity, not PII
        # under hard rule 6 — and the PE id is the whole point of the audit row: it is
        # what a regulator asks us to evidence.
        summary={
            "status": payload.status,
            "tm_link_status": payload.tm_link_status,
            "pe_id": payload.pe_id,
        },
    )
    return DltRegistrationOut(
        tenant_id=tenant_id,
        status=payload.status,
        tm_link_status=payload.tm_link_status,
        pe_id=payload.pe_id,
    )


@router.post(
    "/tenants/{tenant_id}/kyc",
    response_model=KycRecordOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record the outcome of verifying this business's identity (R-11's last gate)",
    description=(
        "Records what Calevate verified about a client's business, against which "
        "registry document, and who verified it. Upserts: re-recording is what happens "
        "on every re-verification. Only a `verified` record opens number provisioning "
        "(every plan tier) and outbound dialling for a self-serve account. There is "
        "deliberately no client-facing twin — a business that could mark its own "
        "identity verified would be marking the telecom gate green on a check nobody "
        "performed."
    ),
)
async def record_kyc_verification(
    tenant_id: UUID,
    payload: KycRecordIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> KycRecordOut:
    """Ops's half of SURFACES §2b's "Number purchase + KYC: gated".

    Same family, same permission and same shape as `record_dlt_registration` above:
    `admin:tenants`, tenant named in the PATH — an admin-realm mutation that infers its
    tenant from the session is un-callable by construction under D-22 — and the work
    done inside `tenant_session(tenant_id)` so RLS is what isolates it.

    The two pre-emptive validations below duplicate CHECK constraints on purpose: the
    database is the enforcement, and these exist so an operator gets a problem+json
    naming the missing field instead of a 500 out of an IntegrityError. Same device
    `record_dlt_registration` uses for `pe_registration_id_required`.
    """
    if payload.status == "verified" and not (payload.document_ref or "").strip():
        raise ProblemError(
            kind="validation",
            code="kyc_document_required",
            title="A verified record must name what was verified",
            detail=(
                "Recording a business as verified needs the registry document it was "
                "verified against."
            ),
            remediation="Send document_kind and document_ref (e.g. the CIN or GSTIN).",
        )
    if payload.status == "rejected" and not (payload.rejection_reason or "").strip():
        raise ProblemError(
            kind="validation",
            code="kyc_rejection_reason_required",
            title="A rejection must say why",
            detail=(
                "A rejected verification with no reason recorded is a support ticket "
                "nobody can close."
            ),
            remediation="Send rejection_reason describing what was missing or wrong.",
        )

    async with tenant_session(tenant_id) as scoped:
        # A mistyped tenant uuid is a 404, not a 500: `kyc_records.tenant_id` has an FK,
        # so an id no organization holds reached the upsert and surfaced as
        # `internal_error`. The two validations above exist so an operator gets a
        # problem+json naming the missing field instead of an IntegrityError; this is
        # the same argument for the field they are most likely to get wrong, since it is
        # the only one they copy rather than type.
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        await record_kyc(
            scoped,
            tenant_id=tenant_id,
            status=payload.status,
            entity_type=payload.entity_type,
            document_kind=payload.document_kind,
            document_ref=payload.document_ref,
            signatory_name=payload.signatory_name,
            evidence_ref=payload.evidence_ref,
            rejection_reason=payload.rejection_reason,
            verified_by_admin_id=principal.user_id,
        )
    await write_audit(
        session,
        action="kyc.recorded",
        actor=principal,
        tenant_id=tenant_id,
        object_type="kyc_record",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        # The registry identifier is the client's own business identity, published in a
        # public register — not PII under hard rule 6, and it is the whole point of the
        # audit row: it is what a regulator asks us to evidence. `signatory_name` is
        # deliberately NOT copied here; the name of a natural person adds nothing an
        # auditor needs and the audit log is read cross-tenant.
        summary={
            "status": payload.status,
            "document_kind": payload.document_kind,
            "document_ref": payload.document_ref,
        },
    )
    return KycRecordOut(
        tenant_id=tenant_id,
        status=payload.status,
        document_kind=payload.document_kind,
        document_ref=payload.document_ref,
    )


# ------------------------------------------------------------ commercial terms
#
# SURFACES §1 "Commercials" and "Controlled mutations with audit: plan changes … cap
# raises". `plans` has held the whole commercial relationship since the first migration
# and NOTHING in this product wrote one: every invoice, margin figure, dispatch ceiling
# and setup-fee charge resolved a row an operator had to INSERT by hand against
# production. `billing/terms.py` is the writer; this is the surface over it.


# The floor and ceiling on every amount. Rupee ceilings are shared verbatim with the
# CLIENT's own cap route rather than re-picked here — a client may never set a cap
# looser than the admin's, so two different maxima would mean an admin ceiling a client
# could not match. Raise them together or not at all.
MAX_RATE_INR = Decimal("1000.0000")
MAX_FEE_INR = MAX_CLIENT_CAP_SPEND_INR
MAX_INCLUDED_MIN = 1_000_000
# Concurrency is engine capacity, not money. 10 is the column's own default and the
# number `campaign_dispatch` falls back to; the ceiling here is a typo guard.
MAX_CONCURRENCY = 500


def spend_ceiling_confirmation(tenant_id: UUID) -> str:
    """The step-up string for LOOSENING one tenant's spend ceiling.

    A named function rather than an inline f-string, for the reason
    `ops/routes.py::spend_cap_confirmation` gives: the value is part of an operator
    procedure, so changing its shape has to be a deliberate edit that fails a test
    rather than a reformat that leaves a console sending a header the API refuses.

    Bound to the TENANT, so a confirmation captured while raising one client's ceiling
    cannot be replayed against another's.
    """
    return f"raise_spend_ceiling:{tenant_id}"


def _current_month_start() -> datetime:
    """The first instant of the CURRENT IST billing month, in UTC.

    The floor under both window bounds below. A closed month is priced at its own last
    instant (`billing/plans.month_pricing_instant`), so a row dated INTO a closed month
    wins the resolver's total order there and silently re-prices an invoice the client
    has already been sent — the same defect as editing the row, arrived at from the
    other side. The floor is what makes "a plan change is a new dated row" honest
    rather than merely insert-shaped.
    """
    year, mon = parse_billing_month(ist_billing_month(datetime.now(UTC)))
    return datetime(year, mon, 1, tzinfo=IST).astimezone(UTC)


class CommercialTermsIn(BaseModel):
    """The terms an operator agreed, as they cross the wire.

    **Every amount is a STRING** (`"9999.00"`), never a JSON number: `2500.10` has
    already been through a binary float by the time Pydantic sees it, and these are
    exact NUMERIC rupee amounts (hard rule 7). The two rate fields carry FOUR decimal
    places and the fees two, matching their columns and the invoice's own arithmetic —
    `qty x unit = amount` only holds if the rate is published unrounded.

    **`null` means UNSET on every field, and unset is not zero.** An `overage_rate` of
    0 is free minutes; an absent one is a plan that quotes no overage at all. Nothing
    here is defaulted to a number: this endpoint refuses to invent a price.
    """

    model_config = ConfigDict(extra="forbid")

    setup_fee_inr: Decimal | None = Field(
        default=None, ge=0, le=MAX_FEE_INR, max_digits=12, decimal_places=2
    )
    monthly_fee_inr: Decimal | None = Field(
        default=None, ge=0, le=MAX_FEE_INR, max_digits=12, decimal_places=2
    )
    included_minutes: int | None = Field(default=None, ge=0, le=MAX_INCLUDED_MIN)
    overage_rate_inr: Decimal | None = Field(
        default=None, ge=0, le=MAX_RATE_INR, max_digits=12, decimal_places=4
    )
    # THE OPEN FOUNDER DECISION, and the surface is not blocked on it: the field is
    # settable and stays NULL until somebody decides the number. No default is offered
    # here or anywhere else — TRD §10.1's cost bands are unmeasured pilot gates, so a
    # retail value-tier rate derived from them would be invention wearing a citation
    # (`billing/models.py::Plan.overage_rate_value` carries the full argument).
    overage_rate_value_inr: Decimal | None = Field(
        default=None, ge=0, le=MAX_RATE_INR, max_digits=12, decimal_places=4
    )
    hard_cap_minutes: int | None = Field(default=None, ge=0, le=MAX_CLIENT_CAP_MIN)
    hard_cap_spend_inr: Decimal | None = Field(
        default=None, ge=0, le=MAX_CLIENT_CAP_SPEND_INR, max_digits=12, decimal_places=2
    )
    concurrency_ceiling: int = Field(default=10, ge=1, le=MAX_CONCURRENCY)
    # The row's VALID TIME, half-open `[from, to)` (DATA-MODEL §8, `billing/plans.py`).
    # `null` from = "since forever", `null` to = "until further notice" — which is what
    # an open-ended retainer is, and what every plan row in the database already looks
    # like.
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    @field_validator(
        "setup_fee_inr",
        "monthly_fee_inr",
        "overage_rate_inr",
        "overage_rate_value_inr",
        "hard_cap_spend_inr",
        mode="before",
    )
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        """Hard rule 7 at the boundary, identical to the cap and top-up routes."""
        if isinstance(value, float):
            raise ValueError(
                'money crosses the wire as a string ("9999.00"), never as a JSON float'
            )
        return value

    @model_validator(mode="after")
    def _window_is_a_window(self) -> CommercialTermsIn:
        """A window that ends before it starts is in effect never; a window that starts
        in a CLOSED billing month re-prices a statement the client already has.

        Both are refused here AND by `ck_plans_window_ordered` in the database for the
        first of them — this exists so an operator gets a problem+json naming the field
        instead of a 500 out of an IntegrityError, the same device `record_kyc` uses.
        """
        floor = _current_month_start()
        for name, moment in (
            ("effective_from", self.effective_from),
            ("effective_to", self.effective_to),
        ):
            if moment is not None and moment < floor:
                raise ValueError(
                    f"{name} cannot fall in a closed billing month — a statement that "
                    "has already been rendered must not be re-priced"
                )
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to <= self.effective_from
        ):
            raise ValueError("effective_to must be after effective_from")
        return self


class PlanRowOut(BaseModel):
    """One dated agreement, as an operator reads it. Money as exact strings throughout."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    setup_fee_inr: str | None
    monthly_fee_inr: str | None
    included_minutes: int | None
    overage_rate_inr: str | None
    overage_rate_value_inr: str | None
    hard_cap_minutes: int | None
    hard_cap_spend_inr: str | None
    # The CLIENT's own ceilings on this row, read-only here. Shown because the cap in
    # force is the stricter of the pair (`billing/caps.py`) and a panel without this
    # half cannot explain why a client is capped below their plan.
    client_cap_minutes: int | None
    client_cap_spend_inr: str | None
    concurrency_ceiling: int
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime
    # Does this row actually say what the client pays? False for the cap-only row the
    # client's own stop button mints — in effect for every reader, agreeing no price.
    states_pricing: bool


class CommercialTermsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    # `none` | `unpriced` | `lapsed` | `set` — the server's own name for what an
    # operator is looking at, never re-derived on the screen (`billing/terms.py`).
    state: str
    in_effect: PlanRowOut | None
    # Every row, newest agreement first by VALID time — the resolver's own order, so the
    # row at the top of the screen is the row the invoice would pick.
    history: list[PlanRowOut]
    # The step-up header a LOOSENING write must carry. Served rather than hardcoded in
    # the console, so the string an operator is asked for cannot drift from the one the
    # API compares against.
    loosening_confirmation: str


class RecordTermsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    # False when the submitted terms were already the terms in effect and nothing was
    # written. The console reports it rather than claiming a change it did not make.
    changed: bool
    superseded_plan_id: UUID | None
    state: str


def _plan_out(record: billing_terms.PlanRecord) -> PlanRowOut:
    terms = record.terms
    return PlanRowOut(
        id=record.id,
        setup_fee_inr=_amount(terms.setup_fee),
        monthly_fee_inr=_amount(terms.monthly_fee),
        included_minutes=terms.included_min,
        overage_rate_inr=_amount(terms.overage_rate),
        overage_rate_value_inr=_amount(terms.overage_rate_value),
        hard_cap_minutes=terms.hard_cap_min,
        hard_cap_spend_inr=_amount(terms.hard_cap_spend),
        client_cap_minutes=record.client_cap_min,
        client_cap_spend_inr=_amount(record.client_cap_spend),
        concurrency_ceiling=terms.concurrency_ceiling,
        effective_from=terms.effective_from,
        effective_to=terms.effective_to,
        created_at=record.created_at,
        states_pricing=record.states_pricing,
    )


def _amount(value: Decimal | None) -> str | None:
    """A rupee amount as its exact digits, or absent. Never a float, never a zero
    standing in for "unset" (hard rule 7, and `MarginOut` makes the same call)."""
    return None if value is None else str(value)


@router.get(
    "/tenants/{tenant_id}/commercial-terms",
    response_model=CommercialTermsOut,
    openapi_extra=permission_meta("billing:read"),
    summary="What this client pays, and every dated agreement behind it (SURFACES §1)",
    description=(
        "The `plans` rows for one client, newest agreement first by valid time, with the "
        "one in effect now resolved by the same expression the invoice uses. `state` "
        "names what an operator is looking at: `none` (no terms have ever been set — the "
        "state every new tenant is in), `unpriced` (a row is in effect but states no "
        "price), `lapsed` (rows exist and none is in effect, which is a "
        "misconfiguration), or `set`."
    ),
)
async def read_commercial_terms(
    tenant_id: UUID,
    _: Principal = Depends(requires("billing:read", realm="admin")),
) -> CommercialTermsOut:
    """`billing:read`, matching the margin route — commercial terms are the same class
    of fact and an operator who may see one may see the other. It is not
    `admin:tenants`: D-22 forbids gating a GET on a permission read-only impersonation
    refuses, and this is a read.

    **WHY ONBOARDING DOES NOT SEED A PLAN ROW, AND THIS STATE EXISTS INSTEAD.**
    `admin.service.create_organization` writes `organizations.plan_tier` and stops, so a
    new tenant has NO `plans` row and `state` is `none`. The rejected alternative was to
    seed one during the wizard, and it was rejected on two grounds:

    - **a seeded row would have to carry numbers nobody agreed.** Every amount would be
      NULL (we must not invent prices) or invented. An all-NULL row is, for every reader
      in this codebase, EXACTLY equivalent to no row at all — `caps.read_caps` returns
      the same all-NULL view, `usage_summary` prices the same nothing, the setup-fee
      cron charges the same nothing — so it would buy no correctness at all, only the
      APPEARANCE of a configured account;
    - **and it would destroy a distinction the platform already relies on.**
      `plans.warn_no_plan_in_effect` logs only when a tenant HAS plan rows and none is
      in effect, precisely because "never priced" and "priced, and the window closed" are
      different failures with different remedies. Seeding makes every new tenant look
      like the second one forever.

    So the absence is SURFACED instead: an explicit state with an operator's name on it,
    which the console renders as a refusal to be resolved rather than as an empty panel
    or a zero. The cost, stated: a tenant can go live unpriced. That is already true
    today and is now visible on the screen that can fix it, rather than discoverable
    from a ₹0.00 invoice at the end of the month.
    """
    async with tenant_session(tenant_id) as scoped:
        # 404 BEFORE `state` is computed, because `none` is a claim about a client. An
        # absent tenant has no plan rows either, so this read answered 200 `state: none`
        # — "no terms have ever been set" — for an id that names nobody, and the console
        # offered the form to price them. Its own POST (and `read_credits`,
        # `tenant_invoice`, `read_feature_flags`, `get_tenant`) already answer 404 here,
        # so the two halves of one screen disagreed about whether the client exists.
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        view = await billing_terms.read_terms(scoped, tenant_id=tenant_id)
    return CommercialTermsOut(
        tenant_id=tenant_id,
        state=view.state,
        in_effect=_plan_out(view.in_effect) if view.in_effect else None,
        history=[_plan_out(record) for record in view.history],
        loosening_confirmation=spend_ceiling_confirmation(tenant_id),
    )


@router.post(
    "/tenants/{tenant_id}/commercial-terms",
    response_model=RecordTermsOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Agree new commercial terms — a NEW dated row, never an edit to an old one",
    description=(
        "Records what this client pays from a given instant. Always an INSERT: the row "
        "that priced a month the client has already been billed for is never touched, "
        "because an invoice here is derived and re-rendering it reads `plans` again. "
        "Leave `effective_from` null for terms that apply now and until further notice; "
        "set it to a future instant to prepare a change, which takes effect on that "
        "instant and not before. Idempotent — submitting the terms already in effect "
        "writes nothing, returns `changed: false` and records no audit row. Raising or "
        "REMOVING a spend ceiling additionally needs a superadmin and the "
        "`X-Confirm-Action` header the read publishes."
    ),
)
async def record_commercial_terms(
    tenant_id: UUID,
    payload: CommercialTermsIn,
    session: AdminSession,
    request: Request,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> RecordTermsOut:
    """The write SURFACES §1 promises, and the reasons for each of its three refusals.

    **`admin:tenants`, tenant in the PATH, work inside `tenant_session`** — the house
    pattern every other mutation in this module follows, and not a style choice: an
    admin-realm mutation that inferred its tenant from the session would be un-callable
    by construction under D-22, which `tests/route_shape_test.py` pins.

    **A LOOSENING needs a superadmin AND a step-up.** `core/rbac.py`'s role table
    reserves "cap raises" for `superadmin` and says each such switch "additionally needs
    step-up confirmation", and `plans.hard_cap_*` is the ceiling the dispatch gate
    enforces — there is no way to write terms without writing it. The rule is applied to
    the CHANGE rather than to the route, because gating the whole endpoint on
    `ops:manage` would stop an operator completing an onboarding, which is their job:
    tightening a ceiling, or setting the first ceiling a tenant has ever had, is
    ordinary work; raising one, or removing it, is the dangerous direction and the only
    one that needs the second key (`terms.loosened_ceilings` defines it, and states why
    a tenant with no ceiling today cannot be "loosened").

    **Audited on a REAL change only.** `record_terms` returns `changed=False` when the
    submitted terms already are the terms in effect, and no audit row is written for it —
    the convention `approve_kb` and `integrations.deactivate_endpoint` established. The
    audit log answers "who changed what this client pays"; a row per button press makes
    that question harder to answer, not easier.

    The summary carries the plan ids and the SHAPE of the change, never the amounts. A
    client's commercial terms are not PII under hard rule 6, but `audit_log` is read
    cross-tenant and the row the amounts are on is the durable record of them — the id
    is what an auditor needs to reach it.
    """
    terms = billing_terms.CommercialTerms(
        setup_fee=payload.setup_fee_inr,
        monthly_fee=payload.monthly_fee_inr,
        included_min=payload.included_minutes,
        overage_rate=payload.overage_rate_inr,
        overage_rate_value=payload.overage_rate_value_inr,
        hard_cap_min=payload.hard_cap_minutes,
        hard_cap_spend=payload.hard_cap_spend_inr,
        concurrency_ceiling=payload.concurrency_ceiling,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
    )

    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            # A mistyped uuid must not mint a plan row for a tenant that is not there —
            # `plans.tenant_id` has an FK, so it would fail as a 500 rather than a 404.
            raise ProblemError.not_found("Client")

        current = await billing_terms.plan_in_effect(
            scoped, tenant_id=tenant_id, at=terms.effective_from
        )
        loosened = billing_terms.loosened_ceilings(current, terms)
        if loosened:
            # Both keys, and the ROLE check first: a step-up header is a confirmation,
            # not an authorisation, so an operator who may not do this at all should be
            # told that rather than being asked to confirm.
            if principal.role is None or not role_has(principal.role, "ops:manage"):
                raise ProblemError.forbidden(
                    "Raising or removing a client's spend ceiling needs a superadmin. "
                    "Tightening one, or setting a first ceiling, does not."
                )
            step_up.require(x_confirm_action, spend_ceiling_confirmation(tenant_id))

        result = await billing_terms.record_terms(scoped, tenant_id=tenant_id, terms=terms)
        view = await billing_terms.read_terms(scoped, tenant_id=tenant_id)

    if result.changed:
        await write_audit(
            session,
            action="plan.terms_recorded",
            actor=principal,
            tenant_id=tenant_id,
            object_type="plan",
            object_id=str(result.plan_id),
            ip=client_request_ip(request),
            summary={
                "supersedes": str(result.superseded.id) if result.superseded else None,
                "effective_from": (
                    payload.effective_from.isoformat() if payload.effective_from else None
                ),
                "effective_to": (
                    payload.effective_to.isoformat() if payload.effective_to else None
                ),
                # Which ceilings this write loosened, by name. The one fact a later
                # review of a cap raise is actually looking for.
                "loosened": list(loosened),
                # And whether the write TIGHTENED one far enough to stop this client's
                # outbound calling on the spot. `record_terms` re-arms the gate in the
                # same transaction as the insert (a ceiling accepted whose gate is not
                # armed is a ceiling that does nothing until the next call meters), so
                # this row is the record of an operator having done that.
                "capped_now": result.capped_now,
            },
        )
    return RecordTermsOut(
        plan_id=result.plan_id,
        changed=result.changed,
        superseded_plan_id=result.superseded.id if result.superseded else None,
        state=view.state,
    )


# ------------------------------------------------------------- account lifecycle
#
# `organizations.status` carried a five-value CHECK from the first migration, was READ
# by the health board's ended-account filter, and was WRITTEN by nothing anywhere. This
# is SURFACES §1's "suspend/reactivate, offboarding trigger", and the reason it is not
# merely a colour on a screen is `compliance.service.account_stopped_blocker`: the dial
# gate now refuses a suspended account, so suspending stops the campaigns.


# The transitions an OPERATOR may make, and what each may come from.
#
# `prospect` and `onboarding` are absent as TARGETS on purpose: they are wizard states
# the tenant is born into and moves out of, not switches. `churned` is absent as a
# SOURCE from every entry — it is terminal here, and deliberately so: `core/auth.py`
# already excludes a churned org from every membership resolution, so its users are
# locked out and its data is on the retention clock. Re-opening that account is a new
# agreement, which means a new tenant with its own commercial terms rather than a button
# that silently un-ends an offboarding. A request to leave `churned` therefore gets the
# 409 `transition_status` raises, naming the state it found.
_LIFECYCLE_FROM: dict[str, tuple[str, ...]] = {
    "active": ("prospect", "onboarding", "suspended"),
    "suspended": ("prospect", "onboarding", "active"),
    "churned": ("prospect", "onboarding", "active", "suspended"),
}

# The states an operator must explain. Stopping a client's outbound calling is a support
# fact somebody will have to answer for later, and "why is this account suspended" with
# no answer is the ticket nobody can close (`record_kyc` refuses a reasonless rejection
# for the same reason).
_NEEDS_REASON = ("suspended", "churned")


class LifecycleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "suspended", "churned"]
    # Goes into the audit row verbatim. Required for the two stopping states.
    reason: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def _stopping_states_explain_themselves(self) -> LifecycleIn:
        if self.status in _NEEDS_REASON and not (self.reason or "").strip():
            raise ValueError(f"a reason is required when setting an account {self.status}")
        return self


class LifecycleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    status: str
    # False when the account was ALREADY in this state — a success (RFC 9110 §9.2.2),
    # and the flag that keeps the audit log a record of transitions rather than clicks.
    changed: bool


@router.post(
    "/tenants/{tenant_id}/status",
    response_model=LifecycleOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Suspend, reactivate or close a client account — the switch that stops dialling",
    description=(
        "Moves `organizations.status`. Suspending or closing an account stops its "
        "OUTBOUND calling at the next dial: `compliance.check_dispatch` refuses "
        "`account_suspended` / `account_closed`, so the campaign tick, the 'call this "
        "lead' button and the lead-callback webhook all stop, and the campaign launch "
        "gate names the same rule. Inbound answering is deliberately unaffected — the "
        "caller initiated it, and dropping it punishes them rather than the account. "
        "Idempotent: setting the state an account is already in returns 200 and writes "
        "no audit row. 409 names the state found when the move is not allowed from it "
        "— `churned` is terminal. 404 means no such client."
    ),
)
async def set_tenant_status(
    tenant_id: UUID,
    payload: LifecycleIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> LifecycleOut:
    """The repo's shared state-transition primitive, not a second discriminator.

    `db/transition.py::transition_status` answers the three questions a transition has:
    already-in-state is a SUCCESS, a different state is a 409 naming what was found, and
    an absent (or, under RLS, another tenant's) row is a 404. Writing a fourth copy of
    that CAS-then-name-the-zero-row shape is the drift that module exists to stop.

    **This route deliberately does not touch `plans`.** Closing an account does NOT end
    its commercial terms, and that is a money decision rather than an omission: the final
    invoice for the month a client churned in is still derived, and a window closed at
    the moment of churn would leave that month with no plan in effect and render their
    last statement at ₹0.00 (`billing/plans.py` — an ended window prices nothing, on
    purpose). Terms are ended where terms are agreed: a dated row on the commercials
    surface, whose `effective_to` an operator sets knowing what it costs.

    **A soft-deleted client is a 404 here, and that had to be said explicitly.**
    `transition_status` keys on the id alone, and `organizations.deleted_at` is not part
    of any status: an offboarded tenant therefore answered 200 `changed: true` to a
    suspend, while `GET /v1/admin/tenants/{id}` — which filters `deleted_at IS NULL` —
    answered 404 for that same id on the screen the operator was looking at.
    `service.tenant_exists` is the ONE definition of "is this a live organization" (it
    exists precisely so every surface naming a tenant in its path answers a mistyped uuid
    the same way), so it is asked here rather than having the predicate copied. `churned`
    still reaches the transition and still gets the 409 that names it: closed and deleted
    are different facts and only one of them is reversible.
    """
    async with tenant_session(tenant_id) as scoped:
        if not await service.tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        changed = await transition_status(
            scoped,
            table="organizations",
            entity="Client",
            row_id=tenant_id,
            to_status=payload.status,
            from_statuses=_LIFECYCLE_FROM[payload.status],
        )
    if changed:
        await write_audit(
            session,
            action=f"tenant.{payload.status}",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            # The reason verbatim — it is why somebody stopped a business's calls, and
            # the whole value of the row. No prior status: `from_statuses` is a SET and
            # the CAS does not report which member it matched, so any "from" here would
            # be a second read's guess rather than the transition's own fact.
            summary={"status": payload.status, "reason": payload.reason},
        )
    return LifecycleOut(tenant_id=tenant_id, status=payload.status, changed=changed)


__all__ = ["router"]
