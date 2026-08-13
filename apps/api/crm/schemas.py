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
    # status → count for all six statuses, over the SAME search and agent scope as the
    # page, but NOT narrowed by `status`. The name carries the scope on purpose: the
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
    "LeadUpdateIn",
    "PerformanceFunnelOut",
    "PerformanceOut",
    "RecordingLinkOut",
    "TranscriptTurnOut",
    "UsagePanelOut",
]
