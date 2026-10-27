"use client";

/**
 * The analytics charts' reads (D-869): `/v1/analytics/*`.
 *
 * Every range is IST calendar days: `days` (1-366) ending on `to` (an IST date, today when
 * left out). Dates in responses (`ist_date`, `window.from_date`) are IST calendar days and
 * are rendered verbatim, never re-parsed as instants. Counts are numbers; the stats band's
 * figures are decimal STRINGS (`value`, `previous`, `change_pct`), null when there was
 * nothing to measure.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AnalyticsWindow = Schemas["RangeOut"];
export type Heatmap = Schemas["HeatmapOut"];
export type HeatmapCell = Schemas["HeatmapCellOut"];
export type Durations = Schemas["DurationsOut"];
export type DurationGroup = Schemas["DurationGroupOut"];
export type Timeline = Schemas["TimelineOut"];
export type TimelineDay = Schemas["TimelineDayOut"];
export type CampaignTimelines = Schemas["CampaignTimelinesOut"];
export type CampaignSeries = Schemas["CampaignSeriesOut"];
export type Stats = Schemas["StatsOut"];
export type StatsMetric = Schemas["StatsMetricOut"];

/** The range every analytics read takes. */
export interface AnalyticsRange {
  days?: number;
  /** `YYYY-MM-DD`, IST. */
  to?: string;
  agentId?: string;
  /** False leaves out the owner's own test calls. */
  testCalls?: boolean;
}

function search(params: Record<string, string | number | boolean | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") qs.set(key, String(value));
  }
  const text = qs.toString();
  return text ? `?${text}` : "";
}

function rangeParams(range: AnalyticsRange) {
  return {
    days: range.days,
    to: range.to,
    agent_id: range.agentId,
    test_calls: range.testCalls,
  };
}

/** Owned here so a mutation elsewhere can invalidate every chart with one prefix. */
export const analyticsKeys = {
  all: (org: string) => ["analytics", org] as const,
  heatmap: (org: string, args: object) => ["analytics", org, "heatmap", args] as const,
  durations: (org: string, args: object) => ["analytics", org, "durations", args] as const,
  timeline: (org: string, args: object) => ["analytics", org, "timeline", args] as const,
  campaigns: (org: string, args: object) => ["analytics", org, "campaigns", args] as const,
  stats: (org: string, args: object) => ["analytics", org, "stats", args] as const,
  summary: (org: string, args: object) => ["analytics", org, "summary", args] as const,
  callGroups: (org: string, args: object) => ["analytics", org, "call-groups", args] as const,
};

export type Summary = Schemas["SummaryOut"];
export type SummaryRow = Schemas["SummaryRowOut"];
export type SummaryBucket = Summary["bucket"];
export type CallGroups = Schemas["CallGroupsOut"];
export type CallGroup = Schemas["CallGroupOut"];
export type CallGroupBy = CallGroups["by"];

/** Calls, answered, new leads and wallet spend per IST day, Monday-first week or month.
 *  Spend is null with `spend_withheld` for a reader without billing, or one agent picked. */
export function useActivitySummary(
  session: Session,
  range: AnalyticsRange & { bucket: SummaryBucket },
): UseQueryResult<Summary> {
  const params = { ...rangeParams(range), bucket: range.bucket };
  return useQuery({
    queryKey: analyticsKeys.summary(session.orgSlug, params),
    queryFn: () => apiRequest<Summary>(session, `/v1/analytics/summary${search(params)}`),
  });
}

/** Every call in the range counted per caller, outcome or agent; the counts cover every
 *  call even when `groups` is cut to `limit`. `minCalls: 2` with `by: "caller"` lists
 *  repeat callers. */
export function useCallGroups(
  session: Session,
  range: AnalyticsRange & { by: CallGroupBy; minCalls?: number; limit?: number },
): UseQueryResult<CallGroups> {
  const params = {
    ...rangeParams(range),
    by: range.by,
    min_calls: range.minCalls,
    limit: range.limit,
  };
  return useQuery({
    queryKey: analyticsKeys.callGroups(session.orgSlug, params),
    queryFn: () => apiRequest<CallGroups>(session, `/v1/analytics/call-groups${search(params)}`),
  });
}

/** Calls (or new leads) per IST weekday × hour; always 168 cells, Monday 00:00 first. */
export function useActivityHeatmap(
  session: Session,
  range: AnalyticsRange & { metric?: "calls" | "leads" } = {},
): UseQueryResult<Heatmap> {
  const params = { ...rangeParams(range), metric: range.metric };
  return useQuery({
    queryKey: analyticsKeys.heatmap(session.orgSlug, params),
    queryFn: () => apiRequest<Heatmap>(session, `/v1/analytics/heatmap${search(params)}`),
  });
}

/** Completed-call lengths binned per agent or per outcome — the ridgeline. */
export function useCallDurations(
  session: Session,
  range: AnalyticsRange & {
    groupBy?: "agent" | "outcome";
    binSeconds?: 15 | 30 | 60 | 120;
    limit?: number;
  } = {},
): UseQueryResult<Durations> {
  const params = {
    ...rangeParams(range),
    group_by: range.groupBy,
    bin_s: range.binSeconds,
    limit: range.limit,
  };
  return useQuery({
    queryKey: analyticsKeys.durations(session.orgSlug, params),
    queryFn: () => apiRequest<Durations>(session, `/v1/analytics/durations${search(params)}`),
  });
}

/** Calls, answered calls and new leads per IST day (default 90 days) — the brush chart. */
export function useActivityTimeline(
  session: Session,
  range: AnalyticsRange = {},
): UseQueryResult<Timeline> {
  const params = rangeParams(range);
  return useQuery({
    queryKey: analyticsKeys.timeline(session.orgSlug, params),
    queryFn: () => apiRequest<Timeline>(session, `/v1/analytics/timeline${search(params)}`),
  });
}

/** Dials, connected and leads per IST day for one campaign, or the busiest few. */
export function useCampaignTimelines(
  session: Session,
  range: { days?: number; to?: string; campaignId?: string; limit?: number } = {},
): UseQueryResult<CampaignTimelines> {
  const params = {
    days: range.days,
    to: range.to,
    campaign_id: range.campaignId,
    limit: range.limit,
  };
  return useQuery({
    queryKey: analyticsKeys.campaigns(session.orgSlug, params),
    queryFn: () =>
      apiRequest<CampaignTimelines>(session, `/v1/analytics/campaigns${search(params)}`),
  });
}

/** The stats band (default 7 days), each figure beside the same length of time before. */
export function useAnalyticsStats(
  session: Session,
  range: AnalyticsRange = {},
): UseQueryResult<Stats> {
  const params = rangeParams(range);
  return useQuery({
    queryKey: analyticsKeys.stats(session.orgSlug, params),
    queryFn: () => apiRequest<Stats>(session, `/v1/analytics/stats${search(params)}`),
  });
}
