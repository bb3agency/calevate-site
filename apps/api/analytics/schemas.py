"""Wire models for `/v1/analytics/*` (D-869). Every model is `extra="forbid"`: the response
model is the output whitelist, and nothing here carries a phone number or a word of a
transcript — only counts, seconds, money, our own ids, and the names on the account's own
lead and agent records (the Leads and Agents screens show the same names)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


DurationGroupBy = Literal["agent", "outcome"]


class DurationGroupOut(Strict):
    #: The agent id, or the outcome word (`crm/schemas.CallOutcome`, or `unread` for a call
    #: the pipeline has not read yet).
    key: str
    #: The agent's name, or the outcome word; the screen owns the wording of outcomes.
    label: str
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
    "calls", "answered", "answer_rate_pct", "leads", "hot_leads", "avg_duration_s", "talk_minutes"
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
    #: Whether a rise is good news for the business. Every metric here rises well, but the
    #: screen should read this rather than assume it.
    higher_is_better: bool


class StatsOut(Strict):
    window: RangeOut
    previous_window: RangeOut
    metrics: list[StatsMetricOut]


SummaryBucket = Literal["day", "week", "month"]
#: Why a summary carries no spend: the reader may not see billing, or one agent was picked
#: and the wallet is debited per account, not per agent and day (`billing/history.py`).
SpendWithheld = Literal["no_billing_access", "one_agent"]


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
    #: The lead's name, the agent's name, or None.
    label: str | None
    lead_id: UUID | None
    number_tail: str | None
    calls: int
    answered: int
    latest_at: datetime | None
    latest_outcome: str | None


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


__all__ = [
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
    "MetricKey",
    "RangeOut",
    "SpendWithheld",
    "StatsMetricOut",
    "StatsOut",
    "SummaryBucket",
    "SummaryOut",
    "SummaryRowOut",
    "TimelineDayOut",
    "TimelineOut",
]
