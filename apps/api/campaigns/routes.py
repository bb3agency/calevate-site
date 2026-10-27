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
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import controls, engine_numbers, number_holds, results, scheduling, service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta, role_has
from apps.api.crm.schemas import LeadLensIn
from apps.api.tenancy.engine_workspace import engine_has_workspaces, read_workspace_state

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


#: What a client may file a campaign as. `transactional` is not offered (D-773): a campaign
#: can never be one (`service.TRANSACTIONAL_CAMPAIGN_REASON`), and the launch gate still
#: refuses any older row that says it is.
ClientClassification = Literal["promotional", "service"]


class RetryPolicyIn(Strict):
    """How many times to try each person, and how long to wait between tries (D-773).

    `gaps_minutes` has one entry per retry (`max_attempts - 1`), each one of
    `service.RETRY_GAP_CHOICES`; the service refuses anything else by name.
    """

    max_attempts: int = Field(ge=1, le=5)
    gaps_minutes: list[int] = Field(default_factory=list, max_length=4)


class RetryPolicyOut(Strict):
    max_attempts: int
    gaps_minutes: list[int]


def _retry_policy(payload: RetryPolicyIn | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return service.validated_retry_policy(payload.max_attempts, payload.gaps_minutes)


class CreateCampaignIn(Strict):
    agent_id: UUID
    name: str = Field(min_length=2, max_length=120)
    classification: ClientClassification
    number_id: UUID | None = None
    dlt_template_id: UUID | None = None
    concurrency: int = Field(default=3, ge=1, le=10)
    # None = "the platform window" — clients narrow it, never widen it.
    calling_hours: CallingHoursIn | None = None
    # Optional to CREATE, mandatory to LAUNCH. An older frontend can still draft a
    # campaign; nothing it drafts can dial until the provenance question is answered,
    # because the gate — not this schema — is where the requirement is enforced.
    consent_provenance: ConsentProvenanceIn | None = None
    # None = three tries, 30 then 120 minutes apart (`service.DEFAULT_RETRY_POLICY`).
    retry_policy: RetryPolicyIn | None = None


class CreateCampaignOut(Strict):
    id: UUID
    status: str


class UpdateCampaignIn(Strict):
    """A draft's settings, each optional. An absent field is left alone; `number_id` and
    `calling_hours` may be sent as null to clear them. Consent provenance has its own route,
    because it is a declaration with its own audit row."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    agent_id: UUID | None = None
    number_id: UUID | None = None
    classification: ClientClassification | None = None
    concurrency: int | None = Field(default=None, ge=1, le=10)
    calling_hours: CallingHoursIn | None = None
    retry_policy: RetryPolicyIn | None = None


#: Fields that cannot be cleared: sending null for one is a 422, not an erase.
_REQUIRED_ON_EDIT = ("name", "agent_id", "classification", "concurrency", "retry_policy")


class DeleteCampaignOut(Strict):
    """`deleted` when the draft is gone; `stopped` when it was kept as a stopped campaign
    because calls or compliance records already name it."""

    outcome: Literal["deleted", "stopped"]


class DuplicateCampaignIn(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    #: Also copy the people the source never reached. Needs the source finished or stopped.
    with_unreached: bool = False


class DuplicateCampaignOut(Strict):
    id: UUID
    status: str
    contacts_added: int


class AddLeadsIn(Strict):
    """Exactly one of: named leads (a selection) or a `lens` (D-893 F2: the one lead
    definition the Leads table, its exports, the campaign's own picker and Pip read)."""

    lead_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=5000)
    lens: LeadLensIn | None = None
    #: Required with `lens`: the count the person confirmed. A set that moved since is refused
    #: (`campaign_leads_set_moved`) rather than spending the confirmation on other leads.
    expected_count: int | None = Field(default=None, ge=0)


class RemoveContactsIn(Strict):
    contact_ids: list[UUID] = Field(min_length=1, max_length=1000)


class RemoveContactsOut(Strict):
    removed: int


class ComplaintReviewIn(Strict):
    """The client's confirmation that they read the opt-outs. A literal `true`, so the
    request states the act rather than toggling a flag."""

    reviewed: Literal[True]


class ContactResultOut(Strict):
    id: UUID
    name: str | None
    phone_e164: str
    outcome: results.ContactOutcome
    attempts: int
    last_attempt_at: datetime | None
    will_retry: bool
    next_attempt_at: datetime | None
    #: The last call to this person, for the link to the call's own page.
    call_id: UUID | None


class ContactResultsOut(Strict):
    items: list[ContactResultOut]
    total: int
    #: Every outcome's count for the whole campaign, whatever the filter.
    counts: dict[str, int]


class CampaignLeadOut(Strict):
    id: UUID
    name: str | None
    status: str
    updated_at: datetime


class CampaignResultsOut(Strict):
    """A campaign's totals (FLOWS §5): reach, conversations, leads, spend."""

    contacts: int
    outcomes: dict[str, int]
    tried: int
    #: Connected people over people tried at least once; None before anyone was tried.
    pickup_rate: float | None
    calls: int
    connected_calls: int
    average_call_s: int | None
    talk_seconds: int
    outcome_tags: dict[str, int]
    sentiment: dict[str, int]
    leads: int
    hot_leads: int
    recent_leads: list[CampaignLeadOut]
    opt_outs: int
    #: What these calls took from the credit balance, in rupees (NUMERIC). None for a role
    #: that may not see billing.
    credits_spent_inr: Decimal | None


class OptOutOut(Strict):
    call_id: UUID | None
    at: datetime
    #: What the caller said, as the consent ledger stored it: redacted at capture.
    words_redacted: str | None
    contact_name: str | None


class CampaignPageOut(Strict):
    items: list[CampaignSummaryOut]
    total: int
    #: Every status's count under the same search, whatever the status filter.
    status_counts: dict[str, int]


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
    #: Set when a `lens` matched more than one request adds: the leads are added by an
    #: approved plan in the background (D-893 F3) and the counts above are all zero.
    plan_id: UUID | None = None


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


PauseReason = Literal[
    "person", "maintenance", "healer", "complaint_spike", "out_of_credit", "spend_cap"
]


class ProgressOut(Strict):
    id: UUID
    name: str
    classification: str
    agent_id: UUID
    agent_name: str
    number_id: UUID | None
    consent_source: str | None
    consent_collected_at: datetime | None
    created_at: datetime
    retry_policy: RetryPolicyOut
    #: Why a paused campaign is paused (`service.PAUSE_REASON_SQL`); None unless paused.
    pause_reason: PauseReason | None
    #: True while Resume is refused until the client confirms they read the opt-outs.
    complaint_review_required: bool
    complaint_reviewed_at: datetime | None
    #: Why a RUNNING campaign is ringing nobody, by the gate's rule names
    #: (`service.not_calling_reasons`). Empty when it can call, and for every other status.
    not_calling: list[BlockerOut]
    #: A running campaign outside the platform's or its own calling hours.
    waiting_for_calling_hours: bool
    #: The most calls at once this campaign can have now: its setting, under the plan's
    #: ceiling and the shared line pool (`service.effective_concurrency`).
    effective_concurrency: int
    status: str
    launched_at: datetime | None
    concurrency: int
    contacts: dict[str, int]
    total: int
    #: People already tried once and due another try (`pending` with attempts). Zero
    #: unless the campaign is running or paused, because nothing else retries anyone.
    retries_waiting: int = 0
    #: The earliest of those next tries; None when nobody is waiting for one.
    next_retry_at: datetime | None = None
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
    pause_reason: PauseReason | None = None


class NumberOut(Strict):
    """One number this account may dial from, or be answered on.

    **`supplied_by_us` IS WHAT THE CLIENT-FACING SENTENCE HANGS OFF (D-537).** A number we
    bought for them is one they FORWARD their published number to — "point your existing
    phone at this number" — and their own connection is one they already publish. Those
    are opposite instructions, and a screen that cannot tell them apart gives the wrong
    one to somebody about to reconfigure their clinic's phone.

    NO COST FIELD, deliberately. What a number costs CALEVATE is on the admin-realm view
    (`/v1/admin/numbers/tenants/{tenant_id}`); whether that cost is absorbed, passed
    through or an add-on is a pricing decision nobody has taken (OPERATIONS §2 gate 26),
    and publishing our cost on a client's screen would take it for them.

    `inr_per_month` IS NOT THAT, AND THE DISTINCTION IS THE WHOLE REASON IT MAY BE HERE.
    It is what THIS client agreed to pay for THIS number, frozen on the row at purchase
    (`phone_numbers.client_inr_per_month`) so a later change to the attested rate cannot
    silently re-price a number somebody already bought. Showing someone the price they
    agreed to is not publishing our margin, and a recurring charge a client cannot see on
    the thing it is charged for is the defect the other direction.
    """

    id: UUID
    e164: str
    series: str
    dlt_status: str
    #: Did Calevate supply this number, or did the client bring their own connection?
    supplied_by_us: bool = False
    #: Will a call to this number reach an agent? Every link of the chain: an agent on it,
    #: the voice platform's record of the number (`engine_number_ref`), and the routing of
    #: the number to that agent, which the voice platform holding the number does from the
    #: answering agent our record gives it (`engine_numbers.answers_calls`). A number the
    #: voice platform does not hold rings nothing of ours.
    answerable: bool = False
    #: WHICH AGENT IS ON IT (`phone_numbers.agent_id`). Null means nothing rings: the
    #: outbound caller ID and the inbound answer are both resolved from this binding
    #: (D-420), so a panel that cannot show it can only report its own last action.
    agent_id: UUID | None = None
    #: What the number is FOR (`phone_numbers.direction`). It records an intent and
    #: authorises nothing.
    direction: Literal["inbound", "outbound", "both"] = "inbound"
    #: What this client pays for this number each month, frozen at purchase. None for a
    #: connection they brought themselves — we charge nothing for a line we did not supply.
    inr_per_month: Decimal | None = None
    #: Is the connection usable? `phone_numbers.activated_at IS NOT NULL` — the column,
    #: not a re-derivation of the holder's KYC state, so this screen and the assign route
    #: cannot disagree about one number. False means bought and held: it cannot be given
    #: to an agent until the holder's identity is verified
    #: (`campaigns/number_catalog.assign_number_to_agent`).
    activated: bool = False
    #: Will `POST /v1/numbers/own/{id}/release` accept it from this account? Only a number
    #: rented in this account's own calling account; one we lent it for testing, or a line
    #: on another carrier, is not the client's to give up.
    releasable: bool = False
    #: Can this number carry the platform's outgoing calls? The launch gate's own predicate
    #: (`service.number_dial_refusal`), so the campaign picker offers only numbers a launch
    #: will accept — with the agent binding, which the picker checks against its agent.
    places_calls: bool = False
    #: HELD (D-860): this account stopped (its credit below zero for too long, or the account
    #: closed), so nobody answers the number, no rent is charged for it, and it is given up
    #: at `release_at` unless the account is back in order first. A held number neither
    #: answers nor places calls.
    held: bool = False
    #: When a held number is given up; null while it is not held, and for the moment
    #: between a hold starting and its date being worked out.
    release_at: AwareDatetime | None = None


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


CampaignStatus = Literal["draft", "scheduled", "running", "paused", "completed", "cancelled"]


@router.get(
    "/page",
    response_model=CampaignPageOut,
    openapi_extra=permission_meta("leads:read"),
    summary="One page of campaigns, filtered by status and searched by name, with counts",
)
async def campaign_page(
    session: Session,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: CampaignStatus | None = None,
    q: str | None = Query(None, max_length=120),
    _: Principal = Depends(requires("leads:read")),
) -> CampaignPageOut:
    """The Campaigns screen's list. `GET /v1/campaigns` stays the plain newest-first list the
    dashboard and the copilot read; both run `service.list_campaigns`."""
    search = q.strip() if q else None
    counts = await service.campaign_status_counts(session, search=search)
    rows = await service.list_campaigns(
        session, limit=limit, offset=offset, status=status, search=search
    )
    return CampaignPageOut(
        items=[CampaignSummaryOut.model_validate(row) for row in rows],
        total=counts[status] if status else sum(counts.values()),
        status_counts=counts,
    )


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
    principal: Principal = Depends(requires("org:read")),
) -> list[NumberOut]:
    assert principal.tenant_id is not None
    rows = (
        await session.execute(
            text(
                "SELECT n.id, n.e164, n.series, n.dlt_status, n.engine_owned, "
                "n.agent_id, n.direction, n.client_inr_per_month, "
                "n.activated_at IS NOT NULL, n.provider, n.engine_number_ref, "
                "a.engine_agent_ref, a.status, a.direction, a.deleted_at IS NOT NULL "
                "FROM phone_numbers n LEFT JOIN agents a ON a.id = n.agent_id "
                # A released number is not one this account may dial from or be answered
                # on: the vendor has it back. The ROW survives because a closed month's
                # costs still refer to it, which is exactly why this list has to exclude
                # it rather than relying on the row being gone.
                "WHERE n.released_at IS NULL ORDER BY n.created_at"
            )
        )
    ).all()
    engine = engine_numbers.engine_number_provider()
    own_workspace: str | None = None
    if engine_has_workspaces() and any(r[9] == engine for r in rows):
        own_workspace = (await read_workspace_state(session, principal.tenant_id)).workspace_id
    held = await number_holds.held_numbers(session)
    out: list[NumberOut] = []
    for r in rows:
        on_engine = engine is not None and r[9] == engine
        on_hold = r[0] in held
        # Only a number the voice platform holds can be answered: it routes the number to
        # the answering agent our record gives it.
        answerable = on_engine and engine_numbers.answers_calls(
            engine_number_ref=r[10],
            agent_ref=r[11],
            agent_status=r[12],
            agent_direction=r[13],
            agent_deleted=bool(r[14]),
            held=on_hold,
        )
        out.append(
            NumberOut(
                id=r[0],
                e164=r[1],
                series=r[2],
                dlt_status=r[3],
                supplied_by_us=r[4],
                answerable=answerable,
                agent_id=r[5],
                direction=r[6],
                inr_per_month=r[7],
                activated=r[8],
                places_calls=not on_hold and service.number_dial_refusal(r[9], r[6]) is None,
                held=on_hold,
                release_at=held.get(r[0]),
                releasable=(
                    on_engine
                    and bool(r[10])
                    and engine_numbers.releasable_by(
                        str(r[10]), own_workspace=own_workspace, by_admin=False
                    )
                ),
            )
        )
    return out


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
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> CreateCampaignOut:
    """Create a draft, recording a consent declaration made with it.

    The new-campaign flow asks where the list came from in the same step as the list, so
    this is where most declarations now arrive. It writes the same audit row as
    `declare_consent_provenance`, because the attributability that route argues for does
    not depend on which request carried the answer.
    """
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
        retry_policy=_retry_policy(payload.retry_policy),
    )
    if payload.consent_provenance is not None:
        provenance = payload.consent_provenance
        await write_audit(
            session,
            action="campaign.consent_provenance_declared",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
            summary={
                "source": provenance.source,
                "collected_at": provenance.collected_at.isoformat(),
            },
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
        # `custom` first, so a variable named `phone` or `name` cannot replace the
        # validated fields; the service keeps neither name as a variable.
        contacts=[{**c.custom, "phone": c.phone, "name": c.name} for c in payload.contacts],
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
    # After the agent lock, in the order launch takes them. Refuses while the cause of an
    # automatic pause still holds, and a complaint-spike pause until it was reviewed.
    await controls.assert_resumable(session, tenant_id=principal.tenant_id, campaign_id=campaign_id)
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


@router.patch(
    "/{campaign_id}",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Change a draft's settings: name, agent, number, hours, calls at once, retries",
)
async def update_campaign(
    campaign_id: UUID,
    payload: UpdateCampaignIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> None:
    """Drafts only (`controls.update_draft`). Audited with the names of the fields changed,
    not their values: who changed which setting is the question an audit answers."""
    assert principal.tenant_id is not None
    sent = payload.model_fields_set
    cleared = [
        field for field in _REQUIRED_ON_EDIT if field in sent and getattr(payload, field) is None
    ]
    if cleared:
        raise ProblemError(
            kind="validation",
            code="campaign_field_required",
            title="That setting cannot be empty",
            detail=f"Leave out {', '.join(cleared)} to keep the current value.",
        )
    changes: dict[str, Any] = {}
    for field in sent:
        value = getattr(payload, field)
        if field == "calling_hours":
            changes[field] = value.model_dump() if value is not None else None
        elif field == "retry_policy":
            changes[field] = _retry_policy(value)
        else:
            changes[field] = value
    written = await controls.update_draft(session, campaign_id=campaign_id, changes=changes)
    if written:
        await write_audit(
            session,
            action="campaign.updated",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
            summary={"fields": written},
        )


@router.delete(
    "/{campaign_id}",
    response_model=DeleteCampaignOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Delete a draft (kept as stopped when calls or compliance records name it)",
)
async def delete_campaign(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> DeleteCampaignOut:
    assert principal.tenant_id is not None
    outcome = await controls.delete_draft(session, campaign_id=campaign_id)
    await write_audit(
        session,
        action="campaign.deleted" if outcome == "deleted" else "campaign.stopped",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={"from": "draft"},
    )
    return DeleteCampaignOut(outcome=outcome)


@router.post(
    "/{campaign_id}/stop",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Stop for good: nobody else on the list is called. Idempotent.",
)
async def stop(
    campaign_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> None:
    """Running, paused or scheduled → cancelled (`controls.stop_campaign`). Audited on a real
    transition only, for `pause`'s reason."""
    assert principal.tenant_id is not None
    if await controls.stop_campaign(session, campaign_id=campaign_id):
        await write_audit(
            session,
            action="campaign.stopped",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
        )


@router.post(
    "/{campaign_id}/duplicate",
    response_model=DuplicateCampaignOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="A new draft from this campaign's settings, optionally with the people it missed",
)
async def duplicate(
    campaign_id: UUID,
    payload: DuplicateCampaignIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> DuplicateCampaignOut:
    assert principal.tenant_id is not None
    new_id, added = await controls.duplicate_campaign(
        session,
        tenant_id=principal.tenant_id,
        source_id=campaign_id,
        name=payload.name,
        with_unreached=payload.with_unreached,
    )
    await write_audit(
        session,
        action="campaign.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(new_id),
        ip=client_request_ip(request),
        summary={
            "source_campaign_id": str(campaign_id),
            "with_unreached": payload.with_unreached,
            "contacts": added,
        },
    )
    return DuplicateCampaignOut(id=new_id, status="draft", contacts_added=added)


async def _add_leads_as_plan(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    campaign_id: UUID,
    chosen: LeadLensIn,
) -> AddContactsOut:
    """The `campaign_add_leads` plan Pip makes, built and approved in this request, as
    `crm/routes._bulk_as_plan` does for a large leads change."""
    from apps.api.copilot import plans
    from apps.api.copilot.actions import actor_for
    from apps.api.copilot.set_actions import ADD_TO_CAMPAIGN

    actor = actor_for(principal)
    if actor is None:
        raise ProblemError.forbidden("Adding leads belongs to a signed-in user of this account.")
    built = await plans.build_plan(
        session,
        actor,
        tool="campaign_add_leads",
        action=ADD_TO_CAMPAIGN,
        args={
            "campaign_id": str(campaign_id),
            "lens": chosen.model_dump(mode="json", exclude_defaults=True),
        },
        origin="console",
    )
    approved = await plans.approve(session, actor, plan_id=built.id, expected_hash=built.plan_hash)
    await write_audit(
        session,
        action="copilot.plan_approved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="copilot_plan",
        object_id=str(approved.id),
        ip=client_request_ip(request),
        summary={
            "tool": approved.tool,
            "origin": approved.origin,
            "targets": approved.target_count,
            "excluded": approved.excluded_count,
        },
    )
    return AddContactsOut(added=0, malformed=0, duplicate=0, plan_id=approved.id)


@router.post(
    "/{campaign_id}/contacts/from-leads",
    response_model=AddContactsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Add your CRM leads to a campaign, picked by id or by the leads lens",
)
async def add_contacts_from_leads(
    campaign_id: UUID,
    payload: AddLeadsIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> AddContactsOut:
    """The numbers are read from the leads on the server (`controls.add_leads`). A lens
    matching more than `controls.MAX_LEADS_PER_ADD` runs as the approved
    `campaign_add_leads` plan Pip makes (D-893 F3) rather than being cut short, because the
    person confirmed that whole count."""
    assert principal.tenant_id is not None
    if (payload.lead_ids is None) == (payload.lens is None):
        raise ProblemError(
            kind="validation",
            code="campaign_leads_selection_invalid",
            title="Choose leads one way",
            detail="Send the leads you picked or the filters that choose them: exactly one.",
        )
    lead_ids = payload.lead_ids
    if payload.lens is not None:
        from apps.api.crm import lens as crm_lens

        # Required, not optional: a large match becomes an approved plan below, so the
        # count the person saw is the only consent to that size a request carries.
        if payload.expected_count is None:
            raise ProblemError(
                kind="validation",
                code="campaign_leads_count_required",
                title="Confirm how many leads",
                detail="Send the number of leads you saw match, so a changed set is not added.",
            )
        scope = await crm_lens.resolve_lead_scope(session, payload.lens)
        lead_ids = await crm_lens.lead_ids(session, scope)
        if payload.expected_count != len(lead_ids):
            raise ProblemError.conflict(
                "campaign_leads_set_moved",
                f"This now matches {len(lead_ids)} leads rather than the "
                f"{payload.expected_count} you confirmed, so nobody was added.",
                remediation="Check the leads and add them again.",
            )
        if not lead_ids:
            return AddContactsOut(added=0, malformed=0, duplicate=0)
        if len(lead_ids) > controls.MAX_LEADS_PER_ADD:
            return await _add_leads_as_plan(session, request, principal, campaign_id, payload.lens)
    assert lead_ids is not None
    result = await controls.add_leads(
        session, tenant_id=principal.tenant_id, campaign_id=campaign_id, lead_ids=lead_ids
    )
    await write_audit(
        session,
        action="campaign.contacts_added",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary={
            "from": "lens" if payload.lens else "leads",
            **{key: int(value) for key, value in result.items()},
        },
    )
    return AddContactsOut.model_validate({k: v for k, v in result.items() if k != "leads"})


@router.post(
    "/{campaign_id}/contacts/remove",
    response_model=RemoveContactsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Take people off a campaign before it starts calling",
)
async def remove_campaign_contacts(
    campaign_id: UUID,
    payload: RemoveContactsIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> RemoveContactsOut:
    assert principal.tenant_id is not None
    removed = await controls.remove_contacts(
        session, campaign_id=campaign_id, contact_ids=payload.contact_ids
    )
    if removed:
        await write_audit(
            session,
            action="campaign.contacts_removed",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            ip=client_request_ip(request),
            summary={"removed": removed},
        )
    return RemoveContactsOut(removed=removed)


@router.get(
    "/{campaign_id}/contacts",
    response_model=ContactResultsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Each person on the campaign with their outcome, tries and next retry",
)
async def contact_results(
    campaign_id: UUID,
    session: Session,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    outcome: results.ContactOutcome | None = None,
    q: str | None = Query(None, max_length=60),
    _: Principal = Depends(requires("leads:read")),
) -> ContactResultsOut:
    page = await results.contacts_page(
        session,
        campaign_id=campaign_id,
        outcome=outcome,
        search=q.strip() if q else None,
        limit=limit,
        offset=offset,
    )
    return ContactResultsOut(
        items=[ContactResultOut.model_validate(item) for item in page.items],
        total=page.total,
        counts=page.counts,
    )


@router.get(
    "/{campaign_id}/results",
    response_model=CampaignResultsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Pickup rate, call length, outcomes, sentiment, leads and spend for one campaign",
)
async def campaign_results(
    campaign_id: UUID,
    session: Session,
    principal: Principal = Depends(requires("leads:read")),
) -> CampaignResultsOut:
    # What the calls cost is billing information: a role without `billing:read` gets the
    # field as null, the rule `GET /v1/calls` applies to the same figure.
    found = await results.summary(
        session,
        campaign_id=campaign_id,
        include_spend=principal.role is not None and role_has(principal.role, "billing:read"),
    )
    return CampaignResultsOut.model_validate(found)


@router.get(
    "/{campaign_id}/opt-outs",
    response_model=list[OptOutOut],
    openapi_extra=permission_meta("leads:read"),
    summary="Who on this campaign asked not to be called, in their own (redacted) words",
)
async def campaign_opt_outs(
    campaign_id: UUID,
    session: Session,
    limit: int = Query(50, ge=1, le=results.MAX_OPTOUTS_LISTED),
    _: Principal = Depends(requires("leads:read")),
) -> list[OptOutOut]:
    rows = await results.opt_outs(session, campaign_id=campaign_id, limit=limit)
    return [OptOutOut.model_validate(row) for row in rows]


@router.post(
    "/{campaign_id}/complaint-review",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Confirm you reviewed the opt-outs behind a complaint-spike pause",
)
async def complaint_review(
    campaign_id: UUID,
    payload: ComplaintReviewIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("leads:dispatch")),
) -> None:
    """Resume stays refused until this is recorded (`controls.assert_resumable`). Audited
    once: a second click is the same confirmation."""
    assert principal.tenant_id is not None
    del payload
    if await controls.acknowledge_complaint_review(session, campaign_id=campaign_id):
        await write_audit(
            session,
            action="campaign.complaint_review_confirmed",
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
