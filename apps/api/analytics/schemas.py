"""Wire models for `/v1/analytics/*` (D-869). Every model is `extra="forbid"`: the response
model is the output whitelist, and nothing here carries a phone number or a word of a
transcript — only counts, seconds, money, our own ids, and the names on the account's own
lead and agent records (the Leads and Agents screens show the same names)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from apps.api.core.schemas import Strict


class RangeOut(Strict):
    """The IST calendar days a response covers, both inclusive. Rendered verbatim: they are
    dates, not instants, and re-parsing one as an instant in a browser's zone moves it."""

    from_date: date
    to_date: date
    days: int
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"


HeatmapMetric = Literal["calls", "leads"]


class HeatmapCellOut(Strict):
    #: ISO weekday in IST: 1 = Monday … 7 = Sunday.
    weekday: int
    #: Hour of the IST day, 0-23.
    hour: int
    count: int


class HeatmapOut(Strict):
    """Always 168 cells (7 weekdays * 24 hours), Monday 00:00 first; a quiet hour is a zero
    cell, never a missing one."""

    window: RangeOut
    metric: HeatmapMetric
    total: int
    #: The busiest cell's count, so a colour scale needs no second pass. 0 when empty.
    max_count: int
    cells: list[HeatmapCellOut]


#: `business_outcome` groups by the business's own outcome label (D-836), falling back to
#: the platform outcome for a call with none (`crm/performance.OUTCOME_GROUP_SQL`).
DurationGroupBy = Literal["agent", "outcome", "business_outcome"]

#: Whether an outcome group is the business's own outcome or the platform's word.
OutcomeSource = Literal["business", "platform"]


class DurationGroupOut(Strict):
    #: The agent id, or the outcome word (`crm/schemas.CallOutcome`, or `unread` for a call
    #: the pipeline has not read yet), or the business's own outcome label.
    key: str
    #: The agent's name, or the outcome word; the screen owns the wording of platform
    #: outcomes and shows a business outcome's label as it is.
    label: str
    #: For an outcome group: whose outcome `key` is. None for an agent group.
    outcome_source: OutcomeSource | None = None
    calls: int
    #: Count of calls per bin, in `bin_edges_s` order; the last bin is "this long or longer".
    counts: list[int]
    median_s: int
    p90_s: int


class DurationsOut(Strict):
    """Completed calls only (a ringing or failed dial has no conversation length). Bins are
    fixed server-side so every group shares one x axis: `bin_edges_s[i]` is the bin's lower
    edge in seconds, and the last bin is open-ended."""

    window: RangeOut
    group_by: DurationGroupBy
    bin_s: int
    bin_edges_s: list[int]
    #: Groups with the most calls first, at most `limit`; `other_calls` counts the rest.
    groups: list[DurationGroupOut]
    other_calls: int


class TimelineDayOut(Strict):
    ist_date: date
    calls: int
    #: Calls that reached a conversation (`crm/performance.CONNECTED_SQL`).
    answered: int
    #: People who became a lead this day (`crm/lead_definition`), not everyone called.
    leads: int


class TimelineOut(Strict):
    """One entry per IST day, oldest first, zero-filled — a brush chart's full extent."""

    window: RangeOut
    days: list[TimelineDayOut]
    calls: int
    answered: int
    leads: int


class CampaignDayOut(Strict):
    ist_date: date
    dials: int
    connected: int
    leads: int


class CampaignSeriesOut(Strict):
    campaign_id: UUID
    name: str
    status: str
    dials: int
    connected: int
    leads: int
    days: list[CampaignDayOut]


class CampaignTimelinesOut(Strict):
    window: RangeOut
    #: Campaigns with the most dials in the range first, at most `limit`.
    campaigns: list[CampaignSeriesOut]


MetricKey = Literal[
    "calls",
    "answered",
    "answer_rate_pct",
    "leads",
    "hot_leads",
    "avg_duration_s",
    "talk_minutes",
    "interested_rate_pct",
    "spent_inr",
]


class StatsMetricOut(Strict):
    key: MetricKey
    #: The figure for the chosen range. A rate or an average is None when there was nothing
    #: to measure — "no calls" and "the calls averaged nothing" are different facts.
    value: Decimal | None
    #: The same figure over the same number of days immediately before.
    previous: Decimal | None
    #: `(value - previous) / previous * 100`, 1 dp; None when either side is None or
    #: `previous` is zero (a change from nothing has no percentage).
    change_pct: Decimal | None
    #: Whether a rise is good news for the business. Every metric here rises well except
    #: `spent_inr`, which is neither (spending more on more calls is not a loss), so it is
    #: False there and the screen colours no change in spend.
    higher_is_better: bool


SummaryBucket = Literal["day", "week", "month"]
#: Why a read carries no spend: the reader may not see billing, or one agent was picked,
#: or the calls were narrowed to a campaign, line or direction. The wallet is debited per
#: account, not per agent, campaign or day (`billing/history.py`), so a narrowed figure
#: would be the whole account's spend under a narrower heading.
SpendWithheld = Literal["no_billing_access", "one_agent", "narrowed"]


class StatsOut(Strict):
    window: RangeOut
    previous_window: RangeOut
    metrics: list[StatsMetricOut]
    #: Why `spent_inr` is absent from `metrics`; None when it is there.
    spend_withheld: SpendWithheld | None = None


class SummaryRowOut(Strict):
    """One IST day, Monday-first IST week or IST calendar month, cut to the range."""

    from_date: date
    to_date: date
    calls: int
    answered: int
    leads: int
    #: What left the wallet on these days, a rupee string (hard rule 7); None when withheld.
    spent_inr: str | None


class SummaryOut(Strict):
    """Calls, answered calls, new leads and spend per bucket, oldest first, zero-filled.
    Each column of `rows` sums exactly to the total of the same name."""

    window: RangeOut
    bucket: SummaryBucket
    rows: list[SummaryRowOut]
    calls: int
    answered: int
    leads: int
    spent_inr: str | None
    spend_withheld: SpendWithheld | None


CallGroupBy = Literal["caller", "outcome", "agent"]


class CallGroupOut(Strict):
    """One caller, outcome or agent and its calls in the range. A caller is its lead, or
    the number when no lead was filed; the number itself is never sent, only its last two
    digits (`number_tail`)."""

    #: The lead id, `number` (a caller with no lead), the outcome tag or the agent id.
    key: str
    #: The lead's name, else the name a campaign list gives the number; the agent's name;
    #: or None.
    label: str | None
    lead_id: UUID | None
    number_tail: str | None
    calls: int
    answered: int
    latest_at: datetime | None
    #: The group's most recent call, so a row with no lead still opens something.
    latest_call_id: UUID
    latest_status: str
    latest_outcome: str | None
    #: The latest call's outcome in the business's own words (D-836), when it has one.
    latest_business_outcome_label: str | None


class CallGroupsOut(Strict):
    """Every call in the range grouped, most calls first. `groups` holds at most `limit`
    rows; `groups_total` and `repeat_groups` count all of them, so a question about how
    many is never answered from the page."""

    window: RangeOut
    by: CallGroupBy
    calls: int
    groups_total: int
    #: Groups with two or more calls: repeat callers when `by` is `caller`.
    repeat_groups: int
    min_calls: int
    groups: list[CallGroupOut]


# --- speed to lead (W8.1) -----------------------------------------------------------------

SpeedPeriod = Literal["24h", "7d", "30d", "90d"]


class SpeedWindowOut(Strict):
    """`24h` is the last 24 hours to the minute; `7d`, `30d` and `90d` are IST calendar days
    ending today, both ends inclusive, as every other range here."""

    period: SpeedPeriod
    start_at: datetime
    end_at: datetime
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"


class SpeedFiguresOut(Strict):
    """One set of figures, for every lead source together or for one of them.

    A lead here is one delivery from a lead source that the account's Call new leads plan
    took on (a Follow-up run started), counted on the instant it reached us. The clock runs
    from that instant to the moment our first call to the person was placed; for a lead held
    or booked for later because it came outside calling hours it runs from the release, or
    from the opening the call was booked for (`from_release` counts them)."""

    leads: int
    #: Leads whose first call has been placed.
    called: int
    #: Median seconds from the clock's start to the first call, over `called`. None at zero.
    median_s: int | None
    #: Of `called`, those placed within 60 seconds of the clock's start.
    within_60s: int
    #: Leads with an answered call since they arrived.
    reached: int
    #: Leads not reached and no longer waiting for a first call: rung and never answered,
    #: refused by a rule (do-not-call, consent), or dropped from the waiting list.
    never_reached: int
    #: Leads still waiting for their first call (held, booked for later, or in the queue).
    waiting: int
    #: Leads who became leads in the product's sense (`crm/lead_definition`) after arriving.
    interested: int
    #: Leads whose clock started at a release or a later opening rather than on arrival.
    from_release: int


class SpeedSourceOut(SpeedFiguresOut):
    #: The lead source (`inbound_webhooks.id`), kept by the run after the source is deleted.
    source_id: UUID
    #: The source's kind as stored (`website_form`, `meta_lead_ads`, ...), which the screen
    #: words; None for a source deleted since.
    source: str | None


class SpeedCompareOut(Strict):
    """ "Called within a minute vs later": leads who became interested, by how fast the first
    call went out. Sent only from `SPEED_COMPARE_MIN_LEADS` called leads, with both counts,
    so a small sample is never read as a finding."""

    fast_called: int
    fast_interested: int
    later_called: int
    later_interested: int


class SpeedToLeadOut(Strict):
    window: SpeedWindowOut
    total: SpeedFiguresOut
    #: One row per source with a lead in the window, most leads first, at most
    #: `MAX_SPEED_SOURCES`; `other_sources` counts the leads of the rest.
    sources: list[SpeedSourceOut]
    other_sources: int
    #: None below the sample floor; `compare_min_leads` says what the floor is.
    compare: SpeedCompareOut | None
    compare_min_leads: int


# --- agents today (W8.3) ------------------------------------------------------------------


class AgentTodayOut(Strict):
    agent_id: UUID
    #: Calls started today (IST) that were not the owner's own tests.
    calls: int
    answered: int
    #: People who became a lead today on this agent (`crm/lead_definition`).
    interested: int


class AgentsTodayOut(Strict):
    """Agents with a call or a new lead today only; an agent absent here had neither. The
    latest call of any day is the roster's own `GET /v1/agents/stats`."""

    ist_date: date
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    #: At most `agents/roster.AGENT_ROSTER_LIMIT` rows, the roster's own ceiling.
    agents: list[AgentTodayOut]


# --- the last hour (W8.2) -----------------------------------------------------------------


class LastHourSlotOut(Strict):
    #: The slot's first instant; slots are `LAST_HOUR_SLOT_MINUTES` long, oldest first.
    start_at: datetime
    calls: int


class LastHourOut(Strict):
    #: Calls ringing or connected right now, under the same narrowing as the slots.
    live_now: int
    calls: int
    slots: list[LastHourSlotOut]


# --- weekly call quality (W8.5) -----------------------------------------------------------


class QualityWeekOut(Strict):
    """One Monday-first IST week of answered real calls, each judged once after the call."""

    from_date: date
    to_date: date
    #: Answered calls the after-call read has finished with.
    calls_read: int
    #: Of those, calls with a goal verdict of yes or no (`unclear` is not a verdict).
    judged: int
    goal_reached: int
    #: Calls on which a caller asked something the agent could not answer.
    calls_not_known: int
    #: Calls on which the after-call check found at least one mistake.
    calls_with_mistakes: int


class QualityGapAgentOut(Strict):
    agent_id: UUID
    name: str
    #: Open questions this agent has not been taught the answer to.
    open_questions: int


class QualityWeeksOut(Strict):
    weeks: list[QualityWeekOut]
    #: Agents with open Questions to answer, most first, at most `MAX_GAP_AGENTS`.
    gap_agents: list[QualityGapAgentOut]


__all__ = [
    "AgentTodayOut",
    "AgentsTodayOut",
    "CallGroupBy",
    "CallGroupOut",
    "CallGroupsOut",
    "CampaignDayOut",
    "CampaignSeriesOut",
    "CampaignTimelinesOut",
    "DurationGroupBy",
    "DurationGroupOut",
    "DurationsOut",
    "HeatmapCellOut",
    "HeatmapMetric",
    "HeatmapOut",
    "LastHourOut",
    "LastHourSlotOut",
    "MetricKey",
    "QualityGapAgentOut",
    "QualityWeekOut",
    "QualityWeeksOut",
    "RangeOut",
    "SpeedCompareOut",
    "SpeedFiguresOut",
    "SpeedPeriod",
    "SpeedSourceOut",
    "SpeedToLeadOut",
    "SpeedWindowOut",
    "SpendWithheld",
    "StatsMetricOut",
    "StatsOut",
    "SummaryBucket",
    "SummaryOut",
    "SummaryRowOut",
    "TimelineDayOut",
    "TimelineOut",
]
