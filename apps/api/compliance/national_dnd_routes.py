"""The operator surface for the NATIONAL half of SEC-COMP §3's DNC promise.

Two routers, because the two facts have different scopes and belong on different
sessions:

- `global_router` (`/v1/ops/dnc/global`) writes `dnc_list` rows with `scope='global'` —
  a platform-wide ABSOLUTE suppression, true for every tenant at once, so it runs on
  `global_db` (no tenant GUC) exactly like the big red switch and the TM registration.
  This is the writer `dnc_list.scope='global'` never had: everything downstream of it
  was built — the gate ranks a global entry above a tenant one, `is_removable` refuses
  it, `remove_entry` has a dedicated `dnc_global_entry` refusal telling clients that
  "global suppressions are removed by operations" — and operations had no route.
- `campaign_router` (`/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/
  preference-scrub`) records one national preference scrub of one campaign's list. That
  is TENANT data (evidence about one client's list), so it names its tenant in the path
  and does its work inside `tenant_session` — the house pattern for an admin-realm
  mutation (`first_campaign_routes.decide`, `kyc_routes.record_kyc_verification`), and
  the shape `tests/route_shape_test.py` enforces: an admin-realm mutation that resolved
  its tenant through `tenant_of` would be un-callable by construction (D-22).

**Step-up confirmation on every write** (BACKEND-PATTERNS §7), and each string names its
target. A global suppression stops every tenant dialling one number and lifting one
un-stops it; recording a scrub is what turns a promotional campaign's launch gate green.
None of the three should be reachable by a single POST from a session someone left open.

**Neither router is admin-realm decoration over a client feature.** A client cannot
perform either action and must not be able to: `add_global_numbers` writes a row that
binds every other tenant, and a preference scrub can only be run by the holder of the
Registered Telemarketer relationship with an access provider, which is Calevate. What a
client sees is the RESULT — a global entry appears in their `GET /v1/dnc` list marked
`removable: false`, and the scrub shows up on `GET /v1/campaigns/{id}` beside our own
scrub timestamp.

**What is external.** Running a scrub at all needs a DLT-platform login from an access
provider, which comes with the Registered Telemarketer registration Calevate is still
obtaining (R-01, `platform_state.tm_registration_status`). Until that exists these
routes have nothing true to record — which is the correct state, not a gap: the same
missing registration already refuses every campaign through `tm_registration_missing`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import dnc, preference_scrub
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, global_db
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import require_step_up
from apps.api.db.session import tenant_session

global_router = APIRouter(prefix="/v1/ops/dnc/global", tags=["ops"])
campaign_router = APIRouter(
    prefix="/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub",
    tags=["admin"],
)

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `national_dnd_routes.py` — the same situation and
# the same resolution as `dnc_routes.py`.
GlobalSession = Annotated[AsyncSession, Depends(global_db)]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
Operator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]
TenantOperator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: The step-up string for adding platform-wide suppressions. A named constant for the
#: reason `spend_cap_confirmation` is one: it is an ops procedure quoted in
#: `runbooks/dnc-complaint.md`, and changing it has to be a deliberate edit that fails a
#: test rather than a reformat that leaves a runbook printing a header the API refuses.
SUPPRESS_GLOBALLY_CONFIRMATION = "suppress_number_platform_wide"
#: ...and for taking one back off.
RELEASE_GLOBALLY_CONFIRMATION = "release_number_platform_wide"


def preference_scrub_confirmation(campaign_id: UUID) -> str:
    """The step-up string for recording one campaign's scrub, bound to that campaign.

    The suffix is not decoration: this is the write that turns a promotional campaign's
    launch gate green, and a confirmation captured for one campaign must not be
    replayable against another one whose list nobody scrubbed.
    """
    return f"record_preference_scrub:{campaign_id}"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GlobalSuppressIn(Strict):
    # Raw as pasted, like `/v1/dnc`: `normalize_phone` decides, and what it cannot read
    # is counted malformed rather than suppressed on a guess.
    numbers: list[str] = Field(min_length=1, max_length=dnc.MAX_NUMBERS_PER_ADD)
    source: Literal["regulator", "platform_block"]
    # WHY, in an operator's own words. Not a column — `dnc_list` has no note field and
    # this is not the place to add one — but it travels into the audit log stream, which
    # is where "who blocked this number for the whole platform, and on whose
    # instruction" has to be answerable a year later.
    reason: str = Field(min_length=3, max_length=500)


class GlobalSuppressOut(Strict):
    """Counts, never numbers — `compliance/dnc.py`'s module docstring argues it."""

    added: int
    already_suppressed: int
    malformed: int


class GlobalEntryOut(Strict):
    id: UUID
    phone_masked: str
    scope: str
    source: str | None
    added_at: datetime
    # Always False here: a global entry is not removable through the CLIENT surface,
    # which is what `is_removable` answers. Ops removes it through this router.
    removable: bool


class PreferenceScrubIn(Strict):
    """One scrub, as an access provider's DLT platform reported it.

    `submitted_count` is deliberately NOT a field. The count that matters is how many
    contacts were pending when the run was recorded, and that is something we can read
    rather than something an operator can mistype — see `record_scrub_run`.
    """

    provider: str = Field(min_length=2, max_length=80)
    scrub_ref: str = Field(min_length=3, max_length=120)
    # `AwareDatetime`, so the generated TypeScript client cannot send a bare local
    # string and leave the server guessing which midnight the validity window ends at.
    # The window is IST and the difference is a whole day of dialling.
    scrubbed_at: AwareDatetime
    # The numbers the register suppressed — the ones to take OUT of the campaign. Named
    # for what they are so nobody pastes the surviving list here: `blocked` and
    # `survivors` are the two files a DLT portal hands back, and the wrong one would
    # suppress everybody the scrub cleared.
    blocked_numbers: list[str] = Field(
        default_factory=list, max_length=preference_scrub.MAX_BLOCKED_NUMBERS
    )


class PreferenceScrubOut(Strict):
    """What the recording did, and whether the gate is now satisfied.

    `is_current` is returned rather than left to the caller to derive from `expires_at`,
    because the answer an operator needs is "will this campaign launch now" and a run
    recorded after its own day has ended is a legitimate historical record that does not
    satisfy the gate. Counts only; no number comes back.
    """

    recorded: bool
    submitted: int
    suppressed: int
    unmatched: int
    malformed: int
    provider: str | None
    scrub_ref: str | None
    scrubbed_at: datetime | None
    expires_at: datetime | None
    is_current: bool


@global_router.post(
    "",
    response_model=GlobalSuppressOut,
    status_code=201,
    openapi_extra=permission_meta("ops:manage"),
    summary="Suppress numbers for EVERY tenant (step-up confirmed, audited)",
    description=(
        "Writes `dnc_list` rows with `scope='global'` — an absolute platform-wide "
        "refusal to dial, honoured by every tenant's compliance gate on the next "
        "dispatch decision and removable by no client. Use it for a regulator, TSP or "
        "registrar instruction naming a number, or for a number this platform must "
        "never call again. It is NOT the national customer preference register: that "
        "is a per-list scrub run on an access provider's DLT platform and recorded "
        "against the campaign it covers."
    ),
)
async def suppress_globally(
    payload: GlobalSuppressIn,
    session: GlobalSession,
    request: Request,
    principal: Operator,
    x_confirm_action: str | None = Header(default=None),
) -> GlobalSuppressOut:
    require_step_up(x_confirm_action, SUPPRESS_GLOBALLY_CONFIRMATION)
    result = await dnc.add_global_numbers(
        session, raw_numbers=payload.numbers, source=payload.source
    )
    # Same transaction as the write (`global_db` commits at the end of the request), so
    # a suppression and the record of who made it cannot come apart.
    await write_audit(
        session,
        action="ops.dnc_global_added",
        actor=principal,
        object_type="dnc_list",
        object_id=None,
        ip=client_request_ip(request),
        # Counts, the source and the operator's reason. The numbers are the sensitive
        # part of this request and the audit stream is read by more people than the
        # endpoint (hard rule 6).
        summary={
            "added": result.added,
            "already_suppressed": result.already_suppressed,
            "malformed": result.malformed,
            "source": payload.source,
            "reason": payload.reason.strip(),
        },
    )
    return GlobalSuppressOut(
        added=result.added,
        already_suppressed=result.already_suppressed,
        malformed=result.malformed,
    )


@global_router.get(
    "",
    response_model=list[GlobalEntryOut],
    openapi_extra=permission_meta("ops:manage"),
    summary="Every platform-wide suppression, masked — what we refuse to dial for anyone",
)
async def list_global(
    session: GlobalSession,
    _: Operator,
    limit: int = Query(default=100, ge=1, le=dnc.MAX_LIST),
) -> list[GlobalEntryOut]:
    entries = await dnc.list_global_entries(session, limit=limit)
    return [
        GlobalEntryOut(
            id=entry.id,
            phone_masked=entry.phone_masked,
            scope=entry.scope,
            source=entry.source,
            added_at=entry.added_at,
            removable=entry.removable,
        )
        for entry in entries
    ]


@global_router.delete(
    "/{entry_id}",
    status_code=204,
    openapi_extra=permission_meta("ops:manage"),
    summary="Lift a platform-wide suppression (step-up confirmed, audited)",
)
async def release_globally(
    entry_id: UUID,
    session: GlobalSession,
    request: Request,
    principal: Operator,
    x_confirm_action: str | None = Header(default=None),
) -> None:
    """204 with no body, for `DELETE /v1/dnc/{entry_id}`'s reason: the row just deleted
    holds a phone number, and the response to "stop suppressing this" is not the place
    to repeat it. The `source` this reads is for the audit row."""
    require_step_up(x_confirm_action, RELEASE_GLOBALLY_CONFIRMATION)
    source = await dnc.remove_global_entry(session, entry_id=entry_id)
    await write_audit(
        session,
        action="ops.dnc_global_removed",
        actor=principal,
        object_type="dnc_list",
        object_id=str(entry_id),
        ip=client_request_ip(request),
        summary={"source": source},
    )


@campaign_router.post(
    "",
    response_model=PreferenceScrubOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record a national DND (NCPR) scrub of this campaign's list (step-up, audited)",
    description=(
        "The national half of SEC-COMP §3's DNC bullet. An access provider's DLT "
        "platform scrubs a submitted list against the customer preference register and "
        "returns a reference, a report and a verdict valid until 23:59:59 IST that day; "
        "this records the run and marks the numbers it blocked as `dnc_blocked` on the "
        "campaign. Until a current run exists, `launch_blockers` and `dispatch_blockers` "
        "refuse promotional campaigns with `national_dnd_scrub_missing` or "
        "`national_dnd_scrub_expired`."
    ),
)
async def record_preference_scrub(
    tenant_id: UUID,
    campaign_id: UUID,
    payload: PreferenceScrubIn,
    session: AdminSession,
    request: Request,
    principal: TenantOperator,
    x_confirm_action: str | None = Header(default=None),
) -> PreferenceScrubOut:
    """Tenant in the PATH, work inside `tenant_session` — the house pattern.

    The audit row goes on the ADMIN session and the scrub on the tenant one, matching
    `first_campaign_routes.decide`: the two sessions commit independently, and the order
    here (scrub first, audit second) is the one that can only ever under-report. An
    audit entry for a scrub that failed to commit would be a compliance record of
    something that did not happen.
    """
    require_step_up(x_confirm_action, preference_scrub_confirmation(campaign_id))

    async with tenant_session(tenant_id) as scoped:
        recorded = await preference_scrub.record_scrub_run(
            scoped,
            campaign_id=campaign_id,
            provider=payload.provider,
            scrub_ref=payload.scrub_ref,
            scrubbed_at=payload.scrubbed_at,
            blocked_numbers=payload.blocked_numbers,
            # `requires(..., realm="admin")` resolved this principal against
            # `admin_users`, so the id is present and the FK will find it.
            recorded_by_admin_id=principal.user_id,
        )

    await write_audit(
        session,
        action="compliance.preference_scrub_recorded",
        actor=principal,
        tenant_id=tenant_id,
        object_type="preference_scrub_run",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        # Counts and the provider's reference — the handle that makes this entry
        # checkable against the portal — and never a number (hard rule 6).
        summary={
            "provider": payload.provider.strip(),
            "scrub_ref": payload.scrub_ref.strip(),
            "first_time": recorded.first_time,
            "submitted": recorded.submitted,
            "suppressed": recorded.suppressed,
            "unmatched": recorded.unmatched,
            "malformed": recorded.malformed,
        },
    )
    state = recorded.state
    return PreferenceScrubOut(
        recorded=recorded.first_time,
        submitted=recorded.submitted,
        suppressed=recorded.suppressed,
        unmatched=recorded.unmatched,
        malformed=recorded.malformed,
        provider=state.provider,
        scrub_ref=state.scrub_ref,
        scrubbed_at=state.scrubbed_at,
        expires_at=state.expires_at,
        is_current=state.is_current,
    )


__all__ = [
    "RELEASE_GLOBALLY_CONFIRMATION",
    "SUPPRESS_GLOBALLY_CONFIRMATION",
    "campaign_router",
    "global_router",
    "preference_scrub_confirmation",
]
