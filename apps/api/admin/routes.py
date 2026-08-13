"""Admin-realm endpoints (FLOWS §1, §2; D-22).

Every route here is `realm="admin"`, so a client token cannot reach any of them even
if it somehow carried the permission — the realms are separate Clerk applications and
`verify_token` will not accept one realm's token for the other.

Impersonation (D-22) is READ-ONLY and audited on both halves: this module's start
endpoint records the *intent* ("operator X began viewing tenant Y at T"), and
`core/auth.py::_record_impersonated_read` records the READS — because the start
endpoint mints no credential, so nothing forces an operator through it and its row can
simply be absent. The read-path row is the one that cannot be skipped; this one is what
makes a later "why did you look at this account" question answerable.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import intake, service
from apps.api.agents import service as agents_service
from apps.api.billing import service as billing
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import record_kyc
from apps.api.core.auth import requires
from apps.api.core.context import IMPERSONATE_HEADER, Principal
from apps.api.core.deps import admin_db, db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import ROLE_PERMISSIONS, permission_meta
from apps.api.db.session import tenant_session
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
    # `admin_users.id`, not the Clerk id: the value that appears in `audit_log.actor_id`,
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

    # Returned EXACTLY once — only the hash is stored, so it cannot be re-read later.
    token: str
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
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> CreateOrgOut:
    slug = payload.slug or service.slugify(payload.name)
    created = await service.create_organization(
        name=payload.name,
        slug=slug,
        vertical_template=payload.vertical_template,
        billing_email=str(payload.billing_email) if payload.billing_email else None,
        language=payload.language,
        created_by=principal.user_id,
    )
    await write_audit(
        session,
        action="admin.tenant_created",
        actor=principal,
        tenant_id=UUID(str(created["id"])),
        object_type="organization",
        object_id=str(created["id"]),
        ip=request.client.host if request.client else None,
        summary={"slug": slug, "vertical": payload.vertical_template},
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
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("admin:tenants", realm="admin")),
) -> InviteOut:
    # `global_db` has no tenant GUC, and `invitations` is RLS'd — so scope explicitly
    # to the tenant being invited into rather than reusing the admin's own context.
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as scoped:
        token = await service.create_invitation(
            scoped,
            tenant_id=tenant_id,
            email=str(payload.email),
            role=payload.role,
            created_by=principal.user_id,
        )
    await write_audit(
        session,
        action="admin.invitation_created",
        actor=principal,
        tenant_id=tenant_id,
        object_type="invitation",
        ip=request.client.host if request.client else None,
        # The email is redacted by the audit summary sanitizer; the ROLE is what a
        # later review actually needs.
        summary={"role": payload.role},
    )
    return InviteOut(token=token, expires_in_hours=int(service.INVITE_TTL.total_seconds() // 3600))


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
        ip=request.client.host if request.client else None,
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
        ip=request.client.host if request.client else None,
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


@router.post(
    "/tenants/{tenant_id}/impersonate",
    openapi_extra=permission_meta("admin:impersonate"),
    summary="Begin a READ-ONLY view-as session (D-22) — audited, never acting-as",
)
async def start_impersonation(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("admin:impersonate", realm="admin")),
) -> dict[str, str]:
    await write_audit(
        session,
        action="admin.impersonation_started",
        actor=principal,
        tenant_id=tenant_id,
        object_type="organization",
        object_id=str(tenant_id),
        ip=request.client.host if request.client else None,
    )
    # The header carries the SLUG, matching how the auth layer resolves it (and how
    # client URLs are addressed, D-10) — returning a raw uuid here would look right and
    # fail at the first request.
    from sqlalchemy import text as sql

    slug = (
        await session.execute(
            sql("SELECT slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    if slug is None:
        raise ProblemError.not_found("Organization")

    # NO CREDENTIAL IS MINTED, and that is a NAMED, OPEN GAP rather than a design: the
    # admin keeps their own token and adds the X-Impersonate-Org header, which the auth
    # layer turns into a read-only principal — so an operator can enter a tenant without
    # ever calling this endpoint, and this row will simply be missing for that session.
    # Issuing a *client* credential is the wrong fix (it makes the audit trail ambiguous
    # about who acted); the right one is a short-lived signed grant this endpoint mints
    # and `current_admin` requires, which needs `apps/web` to hold it and a decision-log
    # entry for its lifetime and revocation. Until that lands, the guarantee that an
    # impersonated read is recorded comes from the READ path
    # (`core/auth.py::_record_impersonated_read`), not from this endpoint.
    return {
        "mode": "read_only",
        "header": IMPERSONATE_HEADER,
        "value": str(slug),
        "note": "Mutations are refused while impersonating.",
    }


# --- Knowledge base: the MUTATING half (FLOWS §7) ------------------------------
# These live on the admin router, not the client one, because of D-22: an admin
# reaching a tenant does so by impersonation, and impersonation is read-only. The
# tenant is therefore named in the path rather than inferred from a session, which
# also makes every approval self-documenting in the audit log.


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    version: int
    status: str


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/approve",
    openapi_extra=permission_meta("agents:write"),
    summary="Approval gate (D-28: stays ours whichever RAG provider wins)",
)
async def approve_kb(
    tenant_id: UUID,
    source_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
        await kb_service.approve_source(scoped, source_id=source_id, approved_by=principal.user_id)
    await write_audit(
        session,
        action="kb.approved",
        actor=principal,
        tenant_id=tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
    )
    return {"status": "approved"}


@router.post(
    "/tenants/{tenant_id}/kb/{source_id}/reject",
    openapi_extra=permission_meta("agents:write"),
)
async def reject_kb(
    tenant_id: UUID,
    source_id: UUID,
    payload: RejectIn,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
        await kb_service.reject_source(scoped, source_id=source_id, reason=payload.reason)
    await write_audit(
        session,
        action="kb.rejected",
        actor=principal,
        tenant_id=tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=request.client.host if request.client else None,
        summary={"reason": payload.reason},
    )
    return {"status": "rejected"}


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
        ip=request.client.host if request.client else None,
        summary={"version": version},
    )
    return PublishOut(source_id=source_id, version=version, status="live")


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
        margin = await billing.margin_for_tenant(scoped, tenant_id=tenant_id, month=month)
    del session
    return MarginOut.model_validate(
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in margin.items()}
    )


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


class RegisterTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["promotional", "transactional", "service"]
    body: str = Field(min_length=10, max_length=2000)
    dlt_ref: str | None = Field(default=None, max_length=120)


class TemplateStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "submitted", "approved", "rejected"]
    dlt_ref: str | None = Field(default=None, max_length=120)


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
    async with tenant_session(tenant_id) as scoped:
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
        ip=request.client.host if request.client else None,
        # The series, never the number itself (hard rule 6).
        summary={"series": payload.series},
    )
    return NumberCreatedOut(
        id=number_id, e164=payload.e164, series=payload.series, dlt_status="pending"
    )


@router.post(
    "/tenants/{tenant_id}/numbers/{number_id}/dlt-status",
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
) -> dict[str, str]:
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
        ip=request.client.host if request.client else None,
        summary={"dlt_status": payload.dlt_status},
    )
    return {"dlt_status": payload.dlt_status}


@router.post(
    "/tenants/{tenant_id}/dlt-templates",
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
) -> dict[str, str]:
    async with tenant_session(tenant_id) as scoped:
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
        ip=request.client.host if request.client else None,
        summary={"classification": payload.classification},
    )
    return {"id": str(template_id), "status": "submitted"}


@router.post(
    "/tenants/{tenant_id}/dlt-templates/{template_id}/status",
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
) -> dict[str, str]:
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
        ip=request.client.host if request.client else None,
        summary={"status": payload.status},
    )
    return {"status": payload.status}


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
        ip=request.client.host if request.client else None,
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
        ip=request.client.host if request.client else None,
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


__all__ = ["router"]
