"""The public API's frozen request and response shapes (D-1047, W2.2).

FROZEN means: within one `Calevate-Version` a field here may be ADDED and never removed,
renamed or retyped. `scripts/check_public_api_snapshot.py` diffs the public OpenAPI
document against `tests/fixtures/public_api_snapshot.json` in CI and fails on anything
but an addition. These models are deliberately separate from the console's: the console
may change its own shapes every release, and an integration must not notice.

Money is a decimal STRING of rupees (hard rule 7). Times are UTC instants with an offset.
Lists are cursor-paged by our uuid7 ids, newest first: pass `next_cursor` back as `after`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import Field, HttpUrl, StringConstraints

from apps.api.campaigns.routes import (
    MAX_CONTACT_CUSTOM_FIELDS,
    MAX_CONTACT_CUSTOM_KEY_LEN,
    MAX_CONTACT_CUSTOM_VALUE_LEN,
)
from apps.api.core.schemas import Instant, Strict
from apps.api.crm.one_call import DETAILS_MAX, NAME_MAX, REASON_MAX
from apps.api.integrations.routes import EventChoice
from apps.api.integrations.service import EVENT_TYPES

PAGE_DEFAULT: Final = 50
PAGE_MAX: Final = 100


class PublicPageMeta(Strict):
    object: Literal["list"] = "list"
    #: Pass back as `after` for the next page; null on the last page.
    next_cursor: UUID | None = None
    has_more: bool = False
    api_version: str


# --- me, balance ---------------------------------------------------------------------


class PublicAccountOut(Strict):
    id: UUID
    name: str
    slug: str
    status: str


class PublicKeyInfoOut(Strict):
    id: UUID
    name: str
    scopes: list[str]
    #: Null when the key may use every agent.
    agent_ids: list[UUID] | None
    expires_at: datetime


class PublicMeOut(Strict):
    object: Literal["me"] = "me"
    account: PublicAccountOut
    key: PublicKeyInfoOut
    api_version: str


class PublicBalanceOut(Strict):
    object: Literal["balance"] = "balance"
    #: Rupees, as a decimal string.
    balance_inr: str
    prepaid: bool
    #: True when outbound calling is stopped for want of credit.
    outbound_stopped: bool
    on_trial: bool
    #: Calls this account may place through the API today (IST), and how many it has.
    daily_call_budget: int
    calls_placed_today: int


# --- agents, numbers ----------------------------------------------------------------


class PublicCaptureFieldOut(Strict):
    key: str
    label: str
    type: Literal["text", "number", "bool", "enum", "date"]
    #: The allowed answers of an `enum` field.
    choices: list[str] | None = None


class PublicAgentOut(Strict):
    object: Literal["agent"] = "agent"
    id: UUID
    name: str
    direction: str
    status: str
    language: str
    published: bool
    #: What this agent captures from each call, in the shape `Lead.fields` reports it.
    capture_fields: list[PublicCaptureFieldOut]
    created_at: datetime


class PublicAgentList(PublicPageMeta):
    data: list[PublicAgentOut] = Field(max_length=PAGE_MAX)


class PublicNumberOut(Strict):
    object: Literal["number"] = "number"
    id: UUID
    phone: str
    direction: str
    agent_id: UUID | None
    inbound_line_id: UUID | None
    active: bool
    created_at: datetime


class PublicNumberList(PublicPageMeta):
    data: list[PublicNumberOut] = Field(max_length=PAGE_MAX)


# --- calls ---------------------------------------------------------------------------


class PublicPlaceCallIn(Strict):
    """Exactly one of `phone`, `lead_id` or `follow_up_of` names the person."""

    #: Ten digits are read as an Indian mobile; anything else needs its country code.
    phone: str | None = Field(default=None, max_length=32)
    lead_id: UUID | None = None
    #: Follow up this earlier call: the same person and agent.
    follow_up_of: UUID | None = None
    name: str | None = Field(default=None, max_length=NAME_MAX)
    agent_id: UUID | None = None
    #: Why the agent is calling. Required unless following up.
    reason: str | None = Field(default=None, max_length=REASON_MAX)
    details: str | None = Field(default=None, max_length=DETAILS_MAX)
    #: Call later, with its offset (IST is +05:30). Left out: now.
    at: Instant | None = None


class PublicPlaceCallOut(Strict):
    object: Literal["call_request"] = "call_request"
    #: `blocked` is an answer, not an error: `blocked_rule` and `blocked_reason` say why,
    #: and `opens_at` when a call becomes possible again, when we know.
    status: Literal["queued", "scheduled", "blocked"]
    call_id: UUID | None = None
    lead_id: UUID | None = None
    callback_id: UUID | None = None
    blocked_rule: str | None = None
    blocked_reason: str | None = None
    opens_at: datetime | None = None


class PublicTranscriptTurnOut(Strict):
    speaker: str
    #: Personal details masked (hard rule 5). The unmasked text is never on this API.
    text_redacted: str | None


class PublicCallOut(Strict):
    object: Literal["call"] = "call"
    id: UUID
    direction: str
    status: str
    #: True once the call can change no more (`ended`, `failed`, `no_answer`, ...).
    finished: bool
    agent_id: UUID
    lead_id: UUID | None
    campaign_id: UUID | None
    inbound_line_id: UUID | None
    #: The other party's number: who was called, or who called.
    phone: str | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_s: int | None
    outcome: str | None
    #: The agent's own goal for the call and whether it was met.
    business_outcome: str | None
    business_outcome_label: str | None
    #: Two sentences on how the call went, personal details masked.
    summary_redacted: str | None
    next_step: str | None
    callback_requested: bool | None
    #: Why a call was never placed, when it was not.
    not_placed_reason: str | None
    created_at: datetime


class PublicCallDetailOut(PublicCallOut):
    transcript: list[PublicTranscriptTurnOut] = Field(max_length=2000)


class PublicCallList(PublicPageMeta):
    data: list[PublicCallOut] = Field(max_length=PAGE_MAX)


# --- leads ---------------------------------------------------------------------------


class PublicLeadFieldOut(Strict):
    key: str
    label: str
    type: Literal["text", "number", "bool", "enum", "date"]
    #: Typed by `type`: a number, a boolean, an ISO date or a string; null when not captured.
    value: Any = None


class PublicLeadOut(Strict):
    object: Literal["lead"] = "lead"
    id: UUID
    phone: str
    name: str | None
    status: str
    source: str
    agent_id: UUID
    call_count: int
    last_call_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PublicLeadDetailOut(PublicLeadOut):
    fields: list[PublicLeadFieldOut] = Field(max_length=200)


class PublicLeadList(PublicPageMeta):
    data: list[PublicLeadOut] = Field(max_length=PAGE_MAX)


class PublicCreateLeadIn(Strict):
    """A lead, as one of your lead sources would send it: `lead` is mapped and consent-
    checked exactly as that source's own webhook is."""

    source_id: UUID
    lead: dict[str, Any] = Field(max_length=100)


class PublicCreateLeadOut(Strict):
    object: Literal["lead_intake"] = "lead_intake"
    status: Literal["accepted", "duplicate"]
    lead_id: UUID | None = None
    #: True when the lead is being called now.
    calling: bool = False
    #: The rule that held the call, when one did.
    blocked_rule: str | None = None


# --- do-not-call ---------------------------------------------------------------------


class PublicDncEntryOut(Strict):
    object: Literal["dnc_entry"] = "dnc_entry"
    id: UUID
    phone: str
    #: `tenant`: your account's list. `global`: suppressed for every account.
    scope: str
    source: str | None
    #: False for a person's own request not to be called and for global entries.
    removable: bool
    added_at: datetime


class PublicDncList(PublicPageMeta):
    data: list[PublicDncEntryOut] = Field(max_length=PAGE_MAX)


class PublicDncAddIn(Strict):
    numbers: list[str] = Field(min_length=1, max_length=500)
    source: Literal["customer_request", "manual"] = "manual"


class PublicDncAddOut(Strict):
    object: Literal["dnc_add"] = "dnc_add"
    added: int
    already_suppressed: int
    malformed: int


class PublicDncCheckIn(Strict):
    phone: str = Field(min_length=8, max_length=20)


class PublicDncCheckOut(Strict):
    object: Literal["dnc_check"] = "dnc_check"
    valid: bool
    suppressed: bool
    scope: str | None


class PublicDncRemoveIn(Strict):
    #: Why this number may be called again. Kept in the audit trail.
    reason: str = Field(min_length=5, max_length=200)


# --- campaigns -----------------------------------------------------------------------


class PublicCampaignOut(Strict):
    object: Literal["campaign"] = "campaign"
    id: UUID
    name: str
    status: str
    agent_id: UUID
    launched_at: datetime | None
    created_at: datetime


class PublicCampaignList(PublicPageMeta):
    data: list[PublicCampaignOut] = Field(max_length=PAGE_MAX)


class PublicContactIn(Strict):
    phone: str = Field(min_length=8, max_length=20)
    name: str | None = Field(default=None, max_length=120)
    #: Your own columns, said to the agent as this person's details.
    variables: dict[
        Annotated[str, StringConstraints(max_length=MAX_CONTACT_CUSTOM_KEY_LEN)],
        Annotated[str, StringConstraints(max_length=MAX_CONTACT_CUSTOM_VALUE_LEN)],
    ] = Field(default_factory=dict, max_length=MAX_CONTACT_CUSTOM_FIELDS)


class PublicAddContactsIn(Strict):
    contacts: list[PublicContactIn] = Field(min_length=1, max_length=1000)


class PublicAddContactsOut(Strict):
    object: Literal["contacts_added"] = "contacts_added"
    added: int
    malformed: int
    duplicate: int
    foreign: int


class PublicLaunchBlockerOut(Strict):
    rule: str
    reason: str


class PublicLaunchCheckOut(Strict):
    object: Literal["launch_check"] = "launch_check"
    ready: bool
    blockers: list[PublicLaunchBlockerOut] = Field(max_length=100)


class PublicLaunchOut(Strict):
    object: Literal["launch"] = "launch"
    status: str
    #: Contacts that will be called.
    dialable: int
    #: Contacts left out because they are on a do-not-call list.
    dnc_scrubbed: int


class PublicCampaignStateOut(Strict):
    object: Literal["campaign_state"] = "campaign_state"
    id: UUID
    status: str


class PublicWebhookCreateIn(Strict):
    """A destination this key's server will receive events at. `["*"]` is every event
    there is now; `call.recording_ready` is refused, because a recording link is switched
    on by a person with a code, never by a key."""

    url: HttpUrl
    events: list[EventChoice] = Field(min_length=1, max_length=len(EVENT_TYPES) + 1)
    auto_subscribe_new_events: bool = False


class PublicWebhookOut(Strict):
    object: Literal["webhook"] = "webhook"
    id: UUID
    events: list[str] = Field(max_length=len(EVENT_TYPES))
    #: The signing secret, shown this once: store it to check each delivery's signature.
    secret: str


__all__ = [
    "PAGE_DEFAULT",
    "PAGE_MAX",
    "PublicAccountOut",
    "PublicAddContactsIn",
    "PublicAddContactsOut",
    "PublicAgentList",
    "PublicAgentOut",
    "PublicBalanceOut",
    "PublicCallDetailOut",
    "PublicCallList",
    "PublicCallOut",
    "PublicCampaignList",
    "PublicCampaignOut",
    "PublicCampaignStateOut",
    "PublicCaptureFieldOut",
    "PublicContactIn",
    "PublicCreateLeadIn",
    "PublicCreateLeadOut",
    "PublicDncAddIn",
    "PublicDncAddOut",
    "PublicDncCheckIn",
    "PublicDncCheckOut",
    "PublicDncEntryOut",
    "PublicDncList",
    "PublicDncRemoveIn",
    "PublicKeyInfoOut",
    "PublicLaunchBlockerOut",
    "PublicLaunchCheckOut",
    "PublicLaunchOut",
    "PublicLeadDetailOut",
    "PublicLeadFieldOut",
    "PublicLeadList",
    "PublicLeadOut",
    "PublicMeOut",
    "PublicNumberList",
    "PublicNumberOut",
    "PublicPageMeta",
    "PublicPlaceCallIn",
    "PublicPlaceCallOut",
    "PublicTranscriptTurnOut",
    "PublicWebhookCreateIn",
    "PublicWebhookOut",
]
