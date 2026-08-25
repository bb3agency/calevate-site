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

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import scheduling, service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
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


#: How much per-contact variable text one row may carry, and why there is a number
#: at all (D-302).
#:
#: `custom` is stored as `campaign_contacts.custom` jsonb AND rendered into the agent's
#: prompt as engine `user_data`. Both halves were bounded only by the 2 MiB body cap, so
#: one `POST` of 5,000 contacts could durably store — and later speak from — megabytes of
#: caller-authored text. Storage growth decided by a caller is the same defect the list
#: ceilings above answer, seen from the write side; text that reaches a PROMPT is the
#: worse half, because an unbounded value is the most useful shape an injection can take.
#:
#: The numbers follow the house precedent for the other caller-supplied map in this repo
#: (`ingest.service.MAX_MAPPING_ENTRIES` / `MAX_MAPPING_FIELD_LEN`), sized for what these
#: variables ARE: "appointment_time", "doctor_name", "property_address". Ten of them, a
#: name no longer than a mapping field, and a value that is a phrase rather than a
#: paragraph. Expressed on the MODEL rather than in the service so the ceilings reach the
#: OpenAPI schema and the generated client, where a form can refuse before sending.
MAX_CONTACT_CUSTOM_FIELDS = 10
MAX_CONTACT_CUSTOM_KEY_LEN = 128
MAX_CONTACT_CUSTOM_VALUE_LEN = 200


class ContactIn(Strict):
    phone: str = Field(min_length=8, max_length=20)
    name: str | None = Field(default=None, max_length=120)
    # Extra per-contact variables rendered into the agent prompt (Bolna user_data),
    # bounded in all three dimensions — see the constants above.
    custom: dict[
        Annotated[str, StringConstraints(max_length=MAX_CONTACT_CUSTOM_KEY_LEN)],
        Annotated[str, StringConstraints(max_length=MAX_CONTACT_CUSTOM_VALUE_LEN)],
    ] = Field(default_factory=dict, max_length=MAX_CONTACT_CUSTOM_FIELDS)


class AddContactsIn(Strict):
    contacts: list[ContactIn] = Field(min_length=1, max_length=5000)


class AddContactsOut(Strict):
    added: int
    malformed: int
    duplicate: int
    # Well-formed but non-Indian (+91) numbers, dropped at upload under the India-only
    # freeze (LEGAL-OPS-PLAYBOOK §14/§18) rather than stored as un-dialable contacts.
    foreign: int = 0


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


class ScheduleCancelledOut(Strict):
    """What was stopped, and what the campaign is NOW.

    Two facts, and the caller can derive neither from the request it sent. `cancelled`
    because ONE button stops both kinds of promise: "I stopped the weekly repeat" and "I
    cancelled Monday's start" are different answers, and the screen that rendered the
    button is guessing which one it got. `status` because stopping a repeat on a RUNNING
    campaign leaves it running — this route once answered the constant "draft" for every
    cancellation, which reported a state the campaign was not in.

    `status` stays `str`, matching `ProgressOut.status` and `CampaignSummaryOut.status`:
    one spelling of campaign status across the API, and adding a member to
    `campaigns.models.CAMPAIGN_STATUSES` must not turn a cancel that already committed
    into a 500 out of response validation (D-75's lesson, in the direction that costs
    least). `cancelled` is a Literal because its two values are written by
    `campaigns/scheduling.py` and by nothing else.
    """

    cancelled: Literal["one_time", "recurring"]
    status: str


class RecurrenceIn(Strict):
    """A standing instruction: which weekdays, at what IST time, until when.

    `days` are ISO weekday numbers (1 = Monday), the same vocabulary
    `datetime.isoweekday()` and the service use — one numbering across the wire, the rule
    and the UI, because a second one is an off-by-one that dials on the wrong day.

    `at` is an IST wall-clock "HH:MM", NOT an instant, and that is the whole difference
    between a repeat and a start. "10am every Tuesday" means ten o'clock on each of those
    Tuesdays; an instant would freeze one particular Tuesday's ten o'clock and the
    schedule would have to re-derive the intent from it. The pattern is enforced here so
    the generated TypeScript client cannot send "10" or "10:00 AM".

    `until` is optional and offset-carrying for the same reason `ScheduleIn.start_at` is:
    a bare local date on the wire is a date the server has to guess the zone of.
    """

    days: list[int] = Field(min_length=1, max_length=7)
    at: str = Field(pattern=_HHMM)
    until: AwareDatetime | None = None


class RecurrenceOut(Strict):
    """A repeat as the screen renders it — the RULE and the NEXT OCCURRENCE together.

    The next occurrence is here because a repeat a client cannot read is a repeat they
    cannot trust: "every Tuesday" with no date beside it leaves them to work out whether
    tomorrow counts. `last_skipped_at`/`last_skipped_reason` answer the other question
    the word "scheduled" cannot — why last Tuesday did not run (`campaigns/scheduling.py`
    decision 2: a missed occurrence is skipped, never caught up).
    """

    days: list[int]
    at: str
    until: datetime | None = None
    next_occurrence_at: datetime
    last_skipped_at: datetime | None = None
    last_skipped_reason: str | None = None


class RecurrenceSetOut(RecurrenceOut):
    """What `POST /recurrence` answers with: the repeat, plus when it can first dial.

    Both, for `ScheduleOut`'s reason — they differ whenever the campaign narrowed its own
    calling hours, and a screen showing only the occurrence would promise a 10:00 dial on
    a campaign that only dials from noon.
    """

    first_dial_not_before: datetime


class NationalDndScrubOut(Strict):
    """The national preference scrub of this campaign's list, as evidence.

    Counts and a provider reference; never a number (hard rule 6) — the provider's own
    report returns counts too. `is_current` is computed by
    `compliance.preference_scrub.ScrubState`, the same property the launch gate and the
    dispatch tick read, so a screen can never say "scrubbed" about a run the gate is
    refusing.
    """

    provider: str | None
    scrub_ref: str | None
    scrubbed_at: datetime | None
    expires_at: datetime | None
    suppressed_count: int | None
    is_current: bool


class ProgressOut(Strict):
    status: str
    launched_at: datetime | None
    concurrency: int
    contacts: dict[str, int]
    total: int
    # BOTH halves of SEC-COMP §3's DNC bullet, side by side. `dnc_scrubbed_at` is when
    # OUR tenant-list scrub ran (stamped by `launch_campaign`); `national_dnd_scrub` is
    # what an access provider's DLT platform did and when. Two fields rather than one
    # "scrubbed" flag because the two are run by different parties at different times,
    # and a client reading a single green tick could not tell which one it stood for.
    # Both None on a campaign that has never launched and never been scrubbed.
    dnc_scrubbed_at: datetime | None = None
    national_dnd_scrub: NationalDndScrubOut | None = None
    # The pending start, echoed from `campaigns.schedule`, so a `scheduled` campaign can
    # say WHEN rather than just that it is waiting. None for every other status.
    scheduled_start_at: datetime | None = None
    # The rules the gate refused this start with on its last attempt, if any. A
    # scheduled campaign whose start keeps being blocked otherwise sits on screen saying
    # "scheduled" until it silently returns to draft a day later.
    schedule_blocked_rules: list[str] = Field(default_factory=list)
    # The repeat, if this campaign has one — at ANY status, unlike `scheduled_start_at`.
    # A one-time start is spent when it fires; a repeat outlives every occurrence, so a
    # campaign that is dialling right now still has a next Tuesday to show and a repeat
    # to offer stopping.
    recurrence: RecurrenceOut | None = None
    # THE TWO FACTS A LAUNCH CONFIRMATION HAS TO STATE (P7.4), and both were write-only
    # until this pair landed: set in the create form, held as local state, returned by no
    # endpoint. So `LaunchConfirm.tsx` — the panel asking a client to authorise ringing N
    # strangers, irreversibly — could not tell them WHEN it would ring or WHICH number
    # would appear on the handset.
    #
    # `calling_hours` is the campaign's own NARROWING, null when it chose none; the
    # platform's 09:00-21:00 IST bound is true of every campaign and the screen states it
    # unconditionally. `number_e164` is null when the campaign has no number, which the
    # screen says rather than rendering blank.
    calling_hours: CallingHoursIn | None = None
    number_e164: str | None = None


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
    # The ceiling was already 100 — as a literal inside `service.list_campaigns`'s SQL,
    # where no caller could see it and no caller could get past it (D-302). A cap the
    # contract does not state is indistinguishable, from the outside, from a client who
    # has 100 campaigns; the same number is now the DEFAULT and the schema says so.
    limit: int = Query(100, ge=1, le=200),
    _: Principal = Depends(requires("leads:read")),
) -> list[CampaignSummaryOut]:
    rows = await service.list_campaigns(session, limit=limit)
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
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Where this list's consent came from (SEC-COMP §3) — before the campaign starts",
)
async def declare_consent_provenance(
    campaign_id: UUID,
    payload: ConsentProvenanceIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> None:
    """The answer path for a draft created before the provenance columns existed.

    Audited: a client's assertion about where five thousand phone numbers came from is
    exactly the kind of statement that has to be attributable later — it is the record
    §3's "refused, in writing" refers to. `leads:dispatch`, not a read permission,
    because declaring provenance is what unlocks dialling.

    **204, and the alternative considered was a body naming the resulting blocker.** The
    interesting half of this answer is that `purchased_list` is recorded and then refused
    (`consent_source_refused`), and a client deserves to see that — but `GET
    /launch-check` is the one authority on what blocks a launch, and the screen re-reads
    it the moment this returns. A second copy of that verdict here would be a second
    thing to keep in step with the gate, which is how the list and the check come to
    disagree. `{"status": "recorded"}` was the third option and the worst of them: a
    constant the caller already knows, shaped like a model, invisible to the generated
    client and to the redaction guardrail alike.
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
        ip=client_request_ip(request),
        summary={"source": payload.source, "collected_at": payload.collected_at.isoformat()},
    )


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
        ip=client_request_ip(request),
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
        ip=client_request_ip(request),
        summary={"start_at": result.start_at.isoformat()},
    )
    return ScheduleOut(start_at=result.start_at, first_dial_not_before=result.first_dial_not_before)


@router.post(
    "/{campaign_id}/recurrence",
    response_model=RecurrenceSetOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Repeat this campaign weekly — the gate runs on EVERY occurrence",
)
async def set_recurrence(
    campaign_id: UUID,
    payload: RecurrenceIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> RecurrenceSetOut:
    """Record a standing instruction to start this campaign on given weekdays.

    `leads:dispatch`, the same permission as `POST /launch` and `POST /schedule`, and for
    the stronger version of the same reason: this is not one launch with a delay on it,
    it is every launch from now until somebody stops it.

    **No compliance gate here, and that is the design** (`campaigns/scheduling.py`
    decision 3). The gate runs inside `launch_campaign` when the dispatch tick fires each
    occurrence, so a DLT registration that lapses in week three refuses week three — a
    gate at THIS moment would be a claim about a Tuesday six weeks away.

    Audited: "who told this campaign to dial every Tuesday, and when" is precisely the
    question `audit_log` exists to answer, and a repeat nobody remembers creating is the
    version of that question that gets asked after a complaint.
    """
    assert principal.tenant_id is not None
    result = await scheduling.schedule_recurrence(
        session,
        tenant_id=principal.tenant_id,
        campaign_id=campaign_id,
        days=payload.days,
        at=datetime.strptime(payload.at, "%H:%M").time(),
        until=payload.until,
    )
    await write_audit(
        session,
        action="campaign.recurrence_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={
            "days": list(result.days),
            "at_ist": payload.at,
            "until": result.until.isoformat() if result.until else None,
            "next_occurrence": result.next_occurrence_at.isoformat(),
        },
    )
    return RecurrenceSetOut(
        days=list(result.days),
        at=f"{result.at:%H:%M}",
        until=result.until,
        next_occurrence_at=result.next_occurrence_at,
        first_dial_not_before=result.first_dial_not_before,
    )


@router.delete(
    "/{campaign_id}/schedule",
    response_model=ScheduleCancelledOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Cancel a pending start or stop a repeat — one button for both",
)
async def unschedule(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> ScheduleCancelledOut:
    """One stop for one column, whichever kind of promise it held.

    The response is the status the campaign is ACTUALLY in afterwards, not the constant
    "draft" this used to return: a campaign that was waiting goes back to draft, and a
    campaign that is dialling keeps dialling — stopping a repeat means "do not start this
    again", never "abandon the calls going out now" (`scheduling.unschedule_campaign`).

    This one keeps a body where its neighbours became 204, and the two facts it carries
    are why: both are answers the caller cannot derive from the request it sent.
    """
    assert principal.tenant_id is not None
    stopped = await scheduling.unschedule_campaign(
        session, tenant_id=principal.tenant_id, campaign_id=campaign_id
    )
    await write_audit(
        session,
        action="campaign.schedule_cancelled",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={"kind": stopped.kind},
    )
    return ScheduleCancelledOut(
        # The stored vocabulary becomes the wire vocabulary here, the same shape
        # `IngestActivityItemOut.outcome` uses. Anything that is not the recurrence
        # marker is a one-time start — which is the call `unschedule_campaign` has
        # already made for a NULL `kind`, kept in one direction rather than two.
        cancelled="recurring" if stopped.kind == scheduling.RECURRING else "one_time",
        status=stopped.status,
    )


@router.post(
    "/{campaign_id}/pause",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Stop dialling now — idempotent, so a panicked double-click is not an error",
    description=(
        "Pause a running campaign. Idempotent: pausing a campaign that is already "
        "paused returns 204, so a second click and the retry of a request whose "
        "response was lost are both safe. 409 means the campaign is in some other "
        "state (cancelled, or still a draft) and the response names it. 404 means no "
        "campaign of yours has that id."
    ),
)
async def pause(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> None:
    """Stated on the decorator as well as here because `/docs` is public and this is a
    contract a client cannot guess: pause is the button someone presses when calls are
    going out that should not be, and answering the second press with an error is how
    an operator comes to believe the first one did not work.

    **204, not `{"status": "paused"}`.** That body was a constant — the same string on
    the press that stopped the calls and on the second press that found them already
    stopped — so it told a caller only what the URL it had just posted to already said.
    Reporting WHICH of the two happened was the alternative and it is deliberately not
    taken: `set_campaign_status` returning `True` is what the audit row is written from,
    and publishing it as well would invite a screen to render "already paused" as
    something the client must act on. The state afterwards is one field of
    `GET /v1/campaigns/{id}`, which this screen re-reads anyway. An empty 204 is also
    the shape `DELETE /v1/integrations/endpoints/{id}` and `DELETE /v1/lead-sources/{id}`
    already use for exactly this: an idempotent transition with nothing to say.

    **Audited, and ONLY on a real transition.** "Who stopped the calls, and when" is a
    question that gets asked after a complaint, and until now the answer was nowhere —
    this was the one campaign state change with no ledger entry at all. It is written on
    `True` alone (D-65 made that answer available): a second click, or the retry of a
    request whose response was lost, is the same request as the first and must not appear
    in an append-only ledger as a second act by a second person. Same call, same reason,
    as `integrations/routes.py::deactivate_endpoint`.
    """
    assert principal.tenant_id is not None
    if await service.set_campaign_status(
        session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
    ):
        await write_audit(
            session,
            action="campaign.paused",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
        )


@router.post(
    "/{campaign_id}/resume",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Dial again from where it stopped — the compliance re-check is at dial time",
    description=(
        "Resume a paused campaign. Idempotent: resuming a campaign that is already "
        "running returns 204. 409 means the campaign is in some other state and the "
        "response names it. 404 means no campaign of yours has that id. Resuming does "
        "not re-run the launch gate — the per-dial compliance check does, on every "
        "contact, which is what catches paperwork that lapsed while it was paused.\n\n"
        "One exception: a campaign whose agent has been ARCHIVED is refused with "
        "`agent_archived`, because that is the one condition the per-dial check can "
        "never clear — it would refuse every contact for ever while the campaign said "
        "it was running. Restore the agent, or point the campaign at another one."
    ),
)
async def resume(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> None:
    """NO COMPLIANCE GATE HERE, and that is the design (`service.dispatch_blockers` argues
    it in full): a campaign can sit paused for a week, so a gate at the moment of resuming
    proves nothing about the moment it dials. The dial-time check is the enforcement.

    THE ONE REFUSAL THAT ARGUMENT DOES NOT COVER IS AN ARCHIVED AGENT (D-440), because it
    is the one fact here that cannot become true again by itself.
    `service.assert_agent_still_assignable` carries the full reasoning; the short version
    is that resuming behind a retired agent produces a campaign that says "running" and
    dials nobody for ever, refused contact by contact with nothing on the screen to say
    why — the state `agents/lifecycle.archive_agent` refuses to manufacture from its own
    side, reached through this door instead.

    Audited on a real transition only, exactly like `pause` above — and this is the half
    of the pair that matters most after an incident: "calls started going out again at
    16:40, and this is who pressed it".

    204 for `pause`'s reason, and the pair must answer alike: two idempotent transitions
    on the same screen that differed in shape would be a difference the next reader has
    to explain.
    """
    assert principal.tenant_id is not None
    await service.assert_agent_still_assignable(session, campaign_id=campaign_id)
    if await service.set_campaign_status(
        session, campaign_id=campaign_id, to_status="running", from_statuses=("paused",)
    ):
        await write_audit(
            session,
            action="campaign.resumed",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
        )


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
