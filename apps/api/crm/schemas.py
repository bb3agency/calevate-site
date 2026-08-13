"""CRM request/response models.

**The response model IS the output whitelist** (BACKEND-PATTERNS §1). Every model here
sets `extra="forbid"`, which is what the redaction-exposure guardrail checks: a field
that is not declared cannot be serialized, so adding a raw transcript column to a query
cannot accidentally ship it to a browser.

Two fields are deliberately absent from every default response:
- `transcript_turns[].text` (raw) — `text_redacted` is the default view (hard rule 5).
- the engine's recording URL — clients get a short-lived presigned link to OUR copy.

A third is present but never raw: `summary` is transcript-DERIVED prose, so the service
puts it through the same `redact()` pass as `text_redacted` before it is serialized
(`crm.service.redacted_summary`). A field name here is not evidence of what the value
holds, which is why the redaction guardrail names `CallSummaryOut.summary` explicitly
and `tests/call_summary_redaction_test.py` is what proves the claim.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from pydantic import BaseModel, ConfigDict, Field

LeadStatus = Literal["new", "contacted", "interested", "hot", "won", "lost"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptTurnOut(Strict):
    idx: int
    speaker: Literal["agent", "caller"]
    # Redacted by default. The raw view is a separate, role-checked, audited endpoint.
    text: str
    lang: str | None = None
    start_ms: int | None = None
    redacted: bool = True


class CallSummaryOut(Strict):
    id: UUID
    agent_id: UUID
    agent_name: str | None = None
    direction: Literal["inbound", "outbound"]
    status: str
    # Masked: a call list is the most-screenshotted page in the product.
    caller_masked: str | None = None
    started_at: datetime | None = None
    duration_s: int | None = None
    outcome_tag: str | None = None
    sentiment: str | None = None
    # REDACTED prose, not the stored column: the summary is derived from the transcript
    # (the offline extractor's is a transcript line verbatim), so it ships through the
    # same pass as `text_redacted`. Raw only from the audited raw-transcript route.
    summary: str | None = None
    lead_id: UUID | None = None


class CallDetailOut(CallSummaryOut):
    transcript: list[TranscriptTurnOut] = Field(default_factory=list)
    extraction: dict[str, Any] = Field(default_factory=dict)
    extraction_valid: bool = True
    has_recording: bool = False
    disclosure_played: bool | None = None


class RecordingLinkOut(Strict):
    url: str
    expires_in_s: int


class LeadOut(Strict):
    id: UUID
    phone_masked: str
    name: str | None = None
    status: LeadStatus
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    schema_version: int | None = None
    call_count: int
    is_repeat_caller: bool
    last_call_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    # WHO OWNS THIS LEAD (ROADMAP M3). The id is what the assignee control writes back,
    # the name is what a person reads — and the two are separate fields rather than one
    # resolved string because a name is not an identity: two colleagues called Ravi are
    # not a bug the picker has to solve.
    assigned_to: UUID | None = None
    # NULL for an unassigned lead AND for an assignee this tenant can no longer name —
    # a member who was removed, or (impossibly, but the query does not assume it) a user
    # from another tenant. The resolution goes through `memberships`, which is RLS'd, so
    # a foreign id resolves to nothing rather than to a stranger's name. The screen says
    # "someone who has left" for the second case and never invents a name for it.
    assigned_to_name: str | None = None


class LeadListOut(Strict):
    """The Leads table is schema-driven (TRD §7): the columns travel WITH the rows so
    the frontend never hard-codes a client's fields."""

    items: list[LeadOut]
    columns: list[ExtractionField]
    # Rows matching EVERY filter the request sent, `status` included — the denominator
    # in "showing 50 of 140".
    total: int
    limit: int
    offset: int
    # status → count for all six statuses, over the SAME search, agent and ASSIGNEE
    # scope as the page, but NOT narrowed by `status`. (The name predates the assignee
    # filter and is kept — a shipped field name is a contract, and it was already
    # imprecise about `agent_id`; `crm.service._lead_scope` is the definition.) Under a
    # "my leads" chip these are therefore MY leads by stage, which is the only reading
    # that answers the question the screen is asking. The name carries the scope on purpose: the
    # screen renders this as a badge row, and the two wrong readings of an unlabelled
    # `status_counts` are both damaging. Narrowed by status it would be one real number
    # and five zeroes — which is exactly the bug this replaces, where filtering to `hot`
    # told a client "new 0, contacted 0". Widened to the whole account it would be a
    # different population from the rows above it, and would cost a second unfiltered
    # scan on every keystroke of the debounced search.
    #
    # Always all six keys: a status with no leads answers 0 rather than going missing,
    # so the UI never has to tell "none of these" apart from "the server did not say".
    status_counts_matching_search: dict[str, int]


class LeadUpdateIn(Strict):
    # Statuses are a FIXED enum (D-21): analytics and hot-lead rules key off them, so
    # clients cannot add their own.
    status: LeadStatus | None = None
    name: str | None = Field(default=None, max_length=120)
    # THE OWNER, and the one field here where `null` is a value rather than a silence.
    #
    # A PATCH body that omits `assigned_to` means "leave the owner alone"; a body that
    # sends `"assigned_to": null` means "this lead has no owner", which is a real event
    # — the person who owned it left, or handed it back. Pydantic v2 tells the two apart
    # through `model_fields_set`, which holds exactly the fields the request supplied and
    # not the ones that took their default (pydantic.dev/docs/validation/latest/concepts/
    # models — "fields_set"); `crm.routes.patch_lead` reads it. Every other field here is
    # non-nullable in the domain, so `None` can keep meaning "unchanged" for them.
    #
    # A dedicated `PUT /v1/leads/{id}/assignee` was the alternative, and it would have
    # made the null unambiguous without the sentinel. Rejected because it would put TWO
    # routes on "edit this lead" — the status select and the assignee select sit in the
    # same table row, are the same permission, and would otherwise be two mutations, two
    # cache invalidations and two places for the next field to be added wrongly.
    assigned_to: UUID | None = None


class LeadTimelineEventOut(Strict):
    """One line of a lead's history, PROJECTED — never `lead_events.payload` itself.

    `lead_events.payload` is JSONB written by six producers in three deployables
    (`crm.service.update_lead`, `ingest.service._timeline`, `workers.pipeline`,
    `workers.notifications`, and two paths in `workers.whatsapp`), with no schema
    between them and the column. Every one of them was read before this model was
    written, and today every one of them stores ids, authored rule/reason codes,
    booleans and counters — no phone number, no transcript text, no extraction payload
    (`crm.service.lead_timeline` records the audit key by key).

    That is a fact about today's writers, not a property of the column, and hard rules 5
    and 6 have to survive the seventh producer. So the read PROJECTS: the service builds
    every field below from a whitelist of keys, and a key nothing here names cannot
    reach a browser however it got into the row. The blob is never serialized, which is
    also why this model needs no `ACKNOWLEDGED_PASSTHROUGH` entry in
    `scripts/check_redaction_exposure.py` — there is no free-form dict to acknowledge.
    """

    id: UUID
    # A STRING, not a `Literal` of the five values `crm.models.LEAD_EVENT_TYPES` allows.
    # The database CHECK is the enum's home, and a build older than the database it is
    # talking to would otherwise 500 on `extra="forbid"` and take a client's whole
    # history off the screen rather than one unfamiliar row. The screen reads this
    # through `lookup` with a visible fallback — the same call the call-detail transcript
    # makes for `speaker`, and for the same reason.
    type: str
    occurred_at: datetime
    # "system" when the platform did it (a call landed, an alert went out), "member"
    # when a person did. The two are told apart HERE rather than by the screen sniffing
    # `actor_name`, because "a colleague we can no longer name" and "the platform" are
    # different sentences and both would otherwise render as an absent name.
    actor_kind: Literal["system", "member"]
    # The member's own name. None for a system event, and None for a member this tenant
    # can no longer name (removed, deactivated, or — see `LeadOut.assigned_to_name` —
    # never theirs to begin with). Resolved through `memberships`, so RLS decides.
    actor_name: str | None = None
    # Client-safe prose, composed by the service from the whitelist. Same doctrine as
    # `AttentionItemOut.title`/`detail`, which already projects rows from this table.
    title: str
    detail: str | None = None
    # The call this line is about, when there is one, so the screen can link to it.
    # OUR id — never the engine's handle, which is a vendor identifier (hard rule 2).
    call_id: UUID | None = None


class LeadTimelineOut(Strict):
    """A page of a lead's history, newest first.

    `total` is the size of the SET, counted with `count(*) OVER ()` in the same pass as
    the rows — never `len(items)`, which is the size of the page (BUILD-LOG §52, and
    `AttentionOut` makes the identical distinction in the identical words).
    """

    items: list[LeadTimelineEventOut]
    total: int
    limit: int
    offset: int


class CallLeadIn(Strict):
    """D-21: an owner may dispatch a single AI call from the Leads table, with an
    optional per-call note rendered into the agent's prompt."""

    agent_id: UUID
    context_note: str | None = Field(default=None, max_length=500)


class CallLeadOut(Strict):
    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None


class CallbackOut(Strict):
    """D-21 M2. `eligible` is a first-class answer, not an error: the call detail
    screen renders the button disabled with `blocked_reason` rather than hiding it,
    which is what SURFACES §2b asks of every gated action."""

    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None
    follow_up_number: int | None = None


class CallbackEligibilityOut(Strict):
    eligible: bool
    reason: str | None = None
    rule: str | None = None
    follow_up_number: int | None = None


class DashboardDayOut(Strict):
    """One IST calendar day of the dashboard's 7-day call chart.

    **The four class counts PARTITION `calls.status`** — every value the CHECK
    constraint allows (`crm.models.CALL_STATUSES`) belongs to exactly one of them, so
    `completed + no_answer + failed + in_flight == total` on every bucket and an owner
    can check the arithmetic against the bar they are looking at.
    `tests/dashboard_daily_test.py` pins both halves of that claim: the partition
    against the constraint's own tuple, and the sum against real rows.

    The grouping is the one the product already uses. `CALL_STATUS_STYLES` in
    apps/web/src/components/ui.tsx already paints these exact sets in these exact
    colours, so a bar and a status badge on the same screen never disagree about what a
    call was:

    - `completed` (green) — the one status that means a conversation happened.
    - `no_answer` (amber) — `no_answer`, `busy`, `voicemail`. Three ways a dial reaches
      the network and not a person. Deliberately NOT folded into `failed`: nothing
      malfunctioned, and the owner's next move ("ring them back") is a different move
      from the one a failure calls for.
    - `failed` (red) — the dial itself broke. Ours to fix, not the callee's.
    - `in_flight` — `queued`, `ringing`, `in_progress`. Not an outcome YET, and a
      FOURTH field rather than a silent omission: today's bar always carries some, and
      a reader seeing three bands add to less than `total` cannot tell a live call from
      a dropped row. The chart draws three bands and may show this one as the gap.

    No status is dropped. A ninth one added to `CALL_STATUSES` without a class here
    fails the partition test rather than quietly unbalancing every bucket.
    """

    # The IST calendar day — not UTC, and not the browser's zone. Serialized `YYYY-MM-DD`
    # and meant to be rendered verbatim: re-parsing it as an instant in a client-side
    # timezone is how "Tuesday" becomes "Monday" for a reader in London.
    ist_date: date
    # Calls that STARTED on this day. A row with a NULL `started_at` was never dialled,
    # so it has no calendar day and appears in no bucket.
    total: int
    completed: int
    no_answer: int
    failed: int
    in_flight: int


class DashboardOut(Strict):
    calls_today: int
    calls_7d: int
    leads_new_7d: int
    hot_leads_open: int
    avg_duration_s: int | None = None
    sentiment_split: dict[str, int] = Field(default_factory=dict)
    outcome_split: dict[str, int] = Field(default_factory=dict)
    after_hours_captured_7d: int = 0
    # WHICH definition of "after hours" produced the number above. `business_hours` =
    # this client's own recorded opening times; `default_window` = the 09:00-21:00 IST
    # fallback used while no agent has any hours recorded.
    #
    # It is a field rather than a comment because the two are not the same claim. The
    # fallback is a guess that is wrong in both directions — it undercounts the
    # late-night clinic and overcounts the salon that closes on Sundays — and a tile
    # that renders "14 captured after hours" identically from a guess and from a fact
    # invites a client to trust a number we did not earn. The UI can now say which one
    # it is holding, and prompt for the intake that turns the guess into the fact.
    after_hours_basis: Literal["business_hours", "default_window"] = "default_window"
    # Client-facing spend is INR NUMERIC, never a float (hard rule 7).
    minutes_used_month: Decimal | None = None
    # The stacked bar chart: the last 7 IST calendar days, OLDEST FIRST, ending today.
    #
    # ALWAYS exactly 7 entries. A day with no calls answers zero rather than going
    # missing — the same rule `PerformanceOut.busiest_hours_ist` follows with its 24
    # hours, and for the same reason: a chart that omits its silent buckets reads as
    # data loss, and the UI must never have to tell "no calls that day" apart from "the
    # server did not say". The zero-fill is the server's job, not the chart's, because
    # only the server knows which seven days it meant.
    #
    # No default: `dashboard()` always emits all seven, so an empty list is a bug that
    # should surface loudly here rather than render as a week of flat bars.
    #
    # These bars do NOT sum to `calls_7d`, and that is not a defect in either. `calls_7d`
    # is a rolling 168 hours back from this instant; this is seven IST calendar days
    # ending tonight, so it holds today's part-day and reaches further back than the
    # rolling window on every day but one. Two different questions — "how busy has the
    # last week been" and "what did each day look like" — and a chart that had to agree
    # with a headline number would have to lie about one of them.
    daily_7d: list[DashboardDayOut]


# --- panels that used to answer `dict[str, Any]` --------------------------------
#
# These three returned an untyped dict, which meant OpenAPI advertised
# `additionalProperties: true` with no properties at all. Two things followed, and the
# second is the one that mattered: the frontend hand-wrote its own interfaces (free to
# drift), and `scripts/check_redaction_exposure.py` — which reads response MODELS — had
# nothing to read, so a field that later carried a raw phone or a transcript line would
# have shipped past the guardrail green. Every field below is declared, so it is now
# inspectable; none is a free-form dict, so none needs an ACKNOWLEDGED_PASSTHROUGH entry.
#
# No field carries a default: the services always emit every key, so a missing one is a
# bug that should surface as a loud 500 rather than a silently invented value.


class PerformanceFunnelOut(Strict):
    """Calls → connected conversations → LEADS that moved past `new` (crm/performance.py
    states each definition; `qualified` is lead-level on purpose)."""

    calls: int
    connected: int
    qualified: int


class PerformanceOut(Strict):
    days: int
    funnel: PerformanceFunnelOut
    # None, never 0, when the denominator is zero: "0% connected" and "no calls yet"
    # are different facts and the screen must keep them apart.
    connect_rate_pct: int | None
    qualify_rate_pct: int | None
    inbound: int
    outbound: int
    avg_duration_s: int | None
    # Outcome tag, or the bare status when a call was never tagged → count. Typed
    # VALUES, so this is a map and not the free-form passthrough the redaction
    # guardrail has to be told about.
    outcomes: dict[str, int]
    # Always exactly 24 buckets, index = IST hour; silent hours are 0, not absent.
    busiest_hours_ist: list[int]


AttentionKind = Literal["lead_blocked", "delivery_failed", "campaign_stalled", "kb_rejected"]


class AttentionItemOut(Strict):
    """One thing the platform refused to do quietly (crm/attention.py).

    `title` and `detail` are already client-safe prose: a blocked lead is named by its
    lead NAME, falling back to a MASKED number, never a raw one.
    """

    kind: AttentionKind
    id: str
    title: str
    detail: str
    # The machine name of the rule that fired ("dnc"), or the campaign status for a
    # stalled campaign. None for the sources that have no rule (deliveries, knowledge).
    rule: str | None
    occurred_at: datetime
    # Realm-relative link to the screen where the fix lives, e.g. "/leads".
    href: str | None


class AttentionOut(Strict):
    """The queue, and the two numbers that say what it is a page OF.

    `counts` and `total` are counted SEPARATELY from the rows (crm/attention.py argues
    it, and `LeadListOut.status_counts_matching_search` above is the same decision on the
    leads table). They are the size of the set, never the size of the page: `items` is
    capped at the request's `limit` and these are not, so `total > len(items)` is the
    normal state of a busy account and the screen says so in words. The bug this
    replaces capped each of the four sources at 25 and then counted what came back, so a
    client with 40 blocked leads read 25 — on the badge, in the nav bell, and in the "of
    M" the shortfall sentence divides by.
    """

    # Everything the four sources match, inside the queue's 14-day window. The nav bell
    # renders this, so it is the number an owner sees most often.
    total: int
    # kind → count, for the summary chips. Only the kinds present appear: absent means
    # genuinely zero, which is what lets the screen skip a chip rather than draw "0".
    counts: dict[str, int]
    # The newest `limit` across all four sources. Truly the newest: each source is
    # fetched to the merged limit, so nothing older is shown above something newer.
    items: list[AttentionItemOut]


class UsagePanelOut(Strict):
    """GET /v1/usage — this month's usage and what it costs (SURFACES §2b).

    **Every money field is a STRING.** The values are `Decimal` all the way through
    billing (hard rule 7) and the route stringifies them at the boundary, because a
    JSON float cannot hold a rupee amount exactly. They must stay strings to the
    screen; `Number()` on INR is how ₹10,159.00 becomes ₹10,158.999999999998.

    Our supplier cost (`unit_cost_paid`) is deliberately absent — that is the admin
    margin panel, and a client who can see it is a client negotiating against it.
    """

    month: str
    minutes_used: str
    calls: int
    included_minutes: int
    overage_minutes: str
    # The two TTS rungs the overage was split across (D-36's ladder, `billing/rates.py`).
    # They add to `overage_minutes` exactly, so an owner can check the arithmetic.
    overage_minutes_premium: str
    overage_minutes_value: str
    overage_cost_inr: str
    # The rate the overage was actually priced at, published so the invoice does not
    # re-read `plans` and risk quoting a different row.
    overage_rate_inr: str
    # The value rung's rate, or None when this plan quotes no separate one — in which
    # case BOTH rungs above were priced at `overage_rate_inr`. None rather than a repeat
    # of the premium rate, because "one rate" and "two rates that happen to be equal"
    # are different plans and the screen says different things about them.
    overage_rate_value_inr: str | None
    # None until the client has a plan row with a fee (mid-onboarding is a real state).
    monthly_fee_inr: str | None
    cap_minutes: int | None
    minutes_left: int | None
    capped: bool
    spend_used_inr: str
    plan_tier: str
    # Credits only mean something for the self-serve motion (D-34); None for a managed
    # client, whose ₹0 wallet would otherwise invite a support ticket.
    credit_balance_inr: str | None


__all__ = [
    "AttentionItemOut",
    "AttentionKind",
    "AttentionOut",
    "CallDetailOut",
    "CallLeadIn",
    "CallLeadOut",
    "CallSummaryOut",
    "CallbackEligibilityOut",
    "CallbackOut",
    "DashboardDayOut",
    "DashboardOut",
    "LeadListOut",
    "LeadOut",
    "LeadStatus",
    "LeadTimelineEventOut",
    "LeadTimelineOut",
    "LeadUpdateIn",
    "PerformanceFunnelOut",
    "PerformanceOut",
    "RecordingLinkOut",
    "TranscriptTurnOut",
    "UsagePanelOut",
]
