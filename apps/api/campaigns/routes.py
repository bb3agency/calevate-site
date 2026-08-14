"""Campaign endpoints (FLOWS §5, SURFACES §2).

The route worth reading is `/launch-check`: it exists so the UI can render the launch
button DISABLED WITH REASONS before anyone clicks it. `POST /launch` re-runs the same
check and refuses with the same names — the check endpoint is a preview of the gate,
never a substitute for it.

D-21's boundary applies: campaign creation and launch are OWNER actions in the client
realm (`leads:dispatch` — they place calls, so they carry the dispatch permission, not
a new one). `/launch-check` deliberately does NOT: reading why you cannot dial is not
the authority to dial, and gating the explanation on the mutating permission hides it
from read-only impersonation (D-22) — support would see the same disabled button the
client is phoning about, with no reason next to it. `leads:read` it is; the rule is
asserted over the whole route table in tests/impersonation_reads_test.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import scheduling, service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])

Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


_HHMM = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


class CallingHoursIn(Strict):
    """A per-campaign calling window (IST). The service enforces the substantive
    rule — narrowing-only, inside the platform's 09:00-21:00 window — so this model
    only pins the wire shape to two well-formed HH:MM strings."""

    start: str = Field(pattern=_HHMM)
    end: str = Field(pattern=_HHMM)


class ConsentProvenanceIn(Strict):
    """Where this list's consent came from, and when (SEC-COMP §3).

    `source` is a Literal, not a string: the wire type IS the enum, so the generated
    TypeScript client offers a client the five real answers instead of a free-text box
    somebody types "yes" into. `purchased_list` is offered because the gate has to be
    able to refuse it by name — see campaigns/models.py.
    """

    source: Literal[
        "existing_customer",
        "inbound_enquiry",
        "web_form_optin",
        "offline_form_optin",
        "purchased_list",
    ]
    collected_at: datetime


class CreateCampaignIn(Strict):
    agent_id: UUID
    name: str = Field(min_length=2, max_length=120)
    classification: Literal["promotional", "transactional", "service"]
    number_id: UUID | None = None
    dlt_template_id: UUID | None = None
    concurrency: int = Field(default=3, ge=1, le=10)
    # None = "the platform window" — clients narrow it, never widen it.
    calling_hours: CallingHoursIn | None = None
    # Optional to CREATE, mandatory to LAUNCH. An older frontend can still draft a
    # campaign; nothing it drafts can dial until the provenance question is answered,
    # because the gate — not this schema — is where the requirement is enforced.
    consent_provenance: ConsentProvenanceIn | None = None


class CreateCampaignOut(Strict):
    id: UUID
    status: str


class ContactIn(Strict):
    phone: str = Field(min_length=8, max_length=20)
    name: str | None = Field(default=None, max_length=120)
    # Extra per-contact variables rendered into the agent prompt (Bolna user_data).
    custom: dict[str, str] = Field(default_factory=dict)


class AddContactsIn(Strict):
    contacts: list[ContactIn] = Field(min_length=1, max_length=5000)


class AddContactsOut(Strict):
    added: int
    malformed: int
    duplicate: int


class BlockerOut(Strict):
    rule: str
    reason: str


class LaunchCheckOut(Strict):
    ready: bool
    blockers: list[BlockerOut]


class LaunchOut(Strict):
    status: str
    dialable: int
    dnc_scrubbed: int


class ScheduleIn(Strict):
    """When a one-time start should happen.

    `AwareDatetime`, not `datetime`: the wire type itself refuses a bare local string,
    so the generated TypeScript client cannot send "2026-08-17T10:00" and have the
    server decide which 10 o'clock it meant. A client picking 10am IST sends
    `2026-08-17T10:00:00+05:30`; the service converts to UTC for storage, and the screen
    renders IST again. Getting this wrong dials households at 15:30 or 02:30, so it is
    pinned at the type level and re-checked in `scheduling.schedule_campaign` for
    callers that are not HTTP requests.
    """

    start_at: AwareDatetime


class ScheduleOut(Strict):
    """The start we recorded, and when dialling can actually begin.

    Both fields, always, because they differ whenever the client picks a time outside
    the calling window — and that difference is the answer to the most natural
    misreading of this feature. A 22:00 start is accepted (starting a campaign is not
    dialling it) and `first_dial_not_before` says 09:00 the next morning, which is what
    TRAI's window means for that choice.
    """

    start_at: datetime
    first_dial_not_before: datetime


class ProgressOut(Strict):
    status: str
    launched_at: datetime | None
    concurrency: int
    contacts: dict[str, int]
    total: int
    # The pending start, echoed from `campaigns.schedule`, so a `scheduled` campaign can
    # say WHEN rather than just that it is waiting. None for every other status.
    scheduled_start_at: datetime | None = None
    # The rules the gate refused this start with on its last attempt, if any. A
    # scheduled campaign whose start keeps being blocked otherwise sits on screen saying
    # "scheduled" until it silently returns to draft a day later.
    schedule_blocked_rules: list[str] = Field(default_factory=list)


class CampaignSummaryOut(Strict):
    """One row of the campaign list.

    `consent_provenance_blocker` is the only DERIVED field here, and it is derived on
    purpose (see `service.list_campaigns` for the full argument): it answers "what does
    this row need" rather than "what did they answer", so the list cannot mistake a
    purchased list — recorded, refused, unfixable — for an answered one. It is a named
    rule rather than a boolean because the two values have different remedies: the
    client can clear `consent_provenance_missing` in the provenance form, and nobody can
    clear `consent_source_refused`. The names are the launch gate's own, so the list and
    `/launch-check` explain the same fact with the same words.

    NULL means "nothing to do here", which covers both an answered draft and every
    campaign past the point where provenance can still be recorded.
    """

    id: UUID
    name: str
    classification: str
    status: str
    contacts: int
    connected: int
    launched_at: datetime | None
    created_at: datetime
    # A Literal, not `str | None`: the generated TypeScript client then offers the two
    # real values, and a screen switching on them cannot invent a third.
    consent_provenance_blocker: (
        Literal["consent_provenance_missing", "consent_source_refused"] | None
    ) = None


class NumberOut(Strict):
    id: UUID
    e164: str
    series: str
    dlt_status: str


class TemplateOut(Strict):
    id: UUID
    classification: str
    status: str
    body: str


@router.get(
    "",
    response_model=list[CampaignSummaryOut],
    openapi_extra=permission_meta("leads:read"),
    summary="Every campaign, newest first — a launched campaign must be findable later",
)
async def list_campaigns(
    session: Session,
    _: Principal = Depends(requires("leads:read")),
) -> list[CampaignSummaryOut]:
    rows = await service.list_campaigns(session)
    return [CampaignSummaryOut.model_validate(row) for row in rows]


# NOTE: these two are declared BEFORE `/{campaign_id}` on purpose — FastAPI matches in
# declaration order, and `/numbers` would otherwise be parsed as a campaign id.
@router.get(
    "/numbers",
    response_model=list[NumberOut],
    openapi_extra=permission_meta("org:read"),
    summary="Numbers this tenant may dial from, with their series (140/160/standard)",
)
async def list_numbers(
    session: Session,
    _: Principal = Depends(requires("org:read")),
) -> list[NumberOut]:
    rows = (
        await session.execute(
            text("SELECT id, e164, series, dlt_status FROM phone_numbers ORDER BY created_at")
        )
    ).all()
    return [NumberOut(id=r[0], e164=r[1], series=r[2], dlt_status=r[3]) for r in rows]


@router.get(
    "/templates",
    response_model=list[TemplateOut],
    openapi_extra=permission_meta("org:read"),
    summary="DLT voice templates, so the launch gate's requirement is selectable",
)
async def list_templates(
    session: Session,
    _: Principal = Depends(requires("org:read")),
) -> list[TemplateOut]:
    rows = (
        await session.execute(
            text(
                "SELECT id, classification, status, body FROM dlt_templates "
                "WHERE kind = 'voice' ORDER BY created_at"
            )
        )
    ).all()
    return [TemplateOut(id=r[0], classification=r[1], status=r[2], body=r[3]) for r in rows]


@router.post(
    "",
    response_model=CreateCampaignOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
)
async def create_campaign(
    payload: CreateCampaignIn,
    session: Session,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CreateCampaignOut:
    assert principal.tenant_id is not None
    campaign_id = await service.create_campaign(
        session,
        tenant_id=principal.tenant_id,
        agent_id=payload.agent_id,
        name=payload.name,
        classification=payload.classification,
        number_id=payload.number_id,
        dlt_template_id=payload.dlt_template_id,
        concurrency=payload.concurrency,
        calling_hours=payload.calling_hours.model_dump() if payload.calling_hours else None,
        consent_source=payload.consent_provenance.source if payload.consent_provenance else None,
        consent_collected_at=(
            payload.consent_provenance.collected_at if payload.consent_provenance else None
        ),
    )
    return CreateCampaignOut(id=campaign_id, status="draft")


@router.post(
    "/{campaign_id}/consent-provenance",
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Where this list's consent came from (SEC-COMP §3) — draft campaigns only",
)
async def declare_consent_provenance(
    campaign_id: UUID,
    payload: ConsentProvenanceIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> dict[str, str]:
    """The answer path for a draft created before the provenance columns existed.

    Audited: a client's assertion about where five thousand phone numbers came from is
    exactly the kind of statement that has to be attributable later — it is the record
    §3's "refused, in writing" refers to. `leads:dispatch`, not a read permission,
    because declaring provenance is what unlocks dialling.
    """
    assert principal.tenant_id is not None
    await service.declare_consent_provenance(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        consent_source=payload.source,
        consent_collected_at=payload.collected_at,
    )
    await write_audit(
        session,
        action="campaign.consent_provenance_declared",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=request.client.host if request.client else None,
        summary={"source": payload.source, "collected_at": payload.collected_at.isoformat()},
    )
    return {"status": "recorded"}


@router.post(
    "/{campaign_id}/contacts",
    response_model=AddContactsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="CSV rows in — deduped, validated, malformed numbers counted not guessed",
)
async def add_contacts(
    campaign_id: UUID,
    payload: AddContactsIn,
    session: Session,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> AddContactsOut:
    assert principal.tenant_id is not None
    result = await service.add_contacts(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        contacts=[{"phone": c.phone, "name": c.name, **c.custom} for c in payload.contacts],
    )
    return AddContactsOut.model_validate(result)


@router.get(
    "/{campaign_id}/launch-check",
    response_model=LaunchCheckOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Why the launch button is disabled, by name (SEC-COMP §3)",
)
async def launch_check(
    campaign_id: UUID,
    session: Session,
    principal: Principal = Depends(requires("leads:read")),
) -> LaunchCheckOut:
    assert principal.tenant_id is not None
    blockers = await service.launch_blockers(
        session, tenant_id=principal.tenant_id, campaign_id=campaign_id
    )
    return LaunchCheckOut(
        ready=not blockers,
        blockers=[BlockerOut(rule=b.rule, reason=b.reason) for b in blockers],
    )


@router.post(
    "/{campaign_id}/launch",
    response_model=LaunchOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="The compliance gate, then the DNC scrub, then running (hard rule 5)",
)
async def launch(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> LaunchOut:
    assert principal.tenant_id is not None
    result = await service.launch_campaign(
        session, tenant_id=principal.tenant_id, campaign_id=campaign_id
    )
    await write_audit(
        session,
        action="campaign.launched",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=request.client.host if request.client else None,
        summary={"dialable": result["dialable"], "dnc_scrubbed": result["dnc_scrubbed"]},
    )
    return LaunchOut.model_validate(result)


@router.post(
    "/{campaign_id}/schedule",
    response_model=ScheduleOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Start this campaign later — the gate runs when it FIRES, not now",
)
async def schedule(
    campaign_id: UUID,
    payload: ScheduleIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> ScheduleOut:
    """Record a one-time start.

    `leads:dispatch`, the same permission as `POST /launch`, because this IS a launch —
    one with a delay on it. Anything weaker would be a way to cause dialling without the
    authority to dial.

    **No compliance gate here, and that is the design, not an omission.** The gate runs
    inside `launch_campaign` when the dispatch tick fires this schedule (hard rule 5,
    `campaigns/scheduling.py` decision 2): a campaign scheduled on Friday and started on
    Monday may have crossed a DNC addition, a spend cap, a KYC expiry or the platform
    halt in between, so a gate at THIS moment would prove nothing about the moment that
    matters. `GET /launch-check` remains available and answers "would it launch right
    now" for a scheduled campaign exactly as for a draft.

    Audited: "who told this campaign to start dialling, and when for" is the same
    question `campaign.launched` exists to answer.
    """
    assert principal.tenant_id is not None
    result = await scheduling.schedule_campaign(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        start_at=payload.start_at,
    )
    await write_audit(
        session,
        action="campaign.scheduled",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=request.client.host if request.client else None,
        summary={"start_at": result.start_at.isoformat()},
    )
    return ScheduleOut(start_at=result.start_at, first_dial_not_before=result.first_dial_not_before)


@router.delete(
    "/{campaign_id}/schedule",
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Cancel a pending start — the campaign goes back to draft",
)
async def unschedule(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> dict[str, str]:
    assert principal.tenant_id is not None
    await scheduling.unschedule_campaign(
        session, tenant_id=principal.tenant_id, campaign_id=campaign_id
    )
    await write_audit(
        session,
        action="campaign.schedule_cancelled",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=request.client.host if request.client else None,
    )
    return {"status": "draft"}


@router.post(
    "/{campaign_id}/pause",
    openapi_extra=permission_meta("leads:dispatch"),
)
async def pause(
    campaign_id: UUID,
    session: Session,
    _: Principal = Depends(requires("leads:dispatch")),
) -> dict[str, str]:
    await service.set_campaign_status(
        session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
    )
    return {"status": "paused"}


@router.post(
    "/{campaign_id}/resume",
    openapi_extra=permission_meta("leads:dispatch"),
)
async def resume(
    campaign_id: UUID,
    session: Session,
    _: Principal = Depends(requires("leads:dispatch")),
) -> dict[str, str]:
    await service.set_campaign_status(
        session, campaign_id=campaign_id, to_status="running", from_statuses=("paused",)
    )
    return {"status": "running"}


@router.get(
    "/{campaign_id}",
    response_model=ProgressOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Live progress: dispatched / connected / failed / no-answer (FLOWS §5)",
)
async def progress(
    campaign_id: UUID,
    session: Session,
    _: Principal = Depends(requires("leads:read")),
) -> ProgressOut:
    result: dict[str, Any] = await service.campaign_progress(session, campaign_id)
    return ProgressOut.model_validate(result)


__all__ = ["router"]
