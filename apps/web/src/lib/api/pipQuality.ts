"use client";

/**
 * Pip's live success scores — `GET /v1/ops/copilot-quality` (D-937). Every share, count,
 * median and the thresholds arrive as server fields (`apps/api/ops/copilot_quality.py`), so
 * nothing here computes a statistic; this module only formats them.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type PipQualityReport = Schemas["CopilotQualityReport"];
export type PipQualityFigures = Schemas["QualityFigures"];
export type PipAreaQuality = Schemas["AreaQuality"];
export type PipToolQuality = Schemas["ToolQuality"];
export type PipExampleTurn = Schemas["ExampleTurn"];
export type PipRealm = PipQualityReport["realm"];

export const PIP_QUALITY_PATH = "/v1/ops/copilot-quality";

/** The server's own window choices (`ops/copilot_quality.WINDOW_CHOICES`). */
export const PIP_WINDOW_CHOICES: readonly number[] = [7, 30];
export const PIP_DEFAULT_WINDOW_DAYS = 7;

export const pipQualityKeys = {
  report: (realm: PipRealm, days: number) => ["admin", "ops", "pip-quality", realm, days] as const,
};

export function pipQualityUrl(realm: PipRealm, days: number): string {
  return `${PIP_QUALITY_PATH}?days=${days}&realm=${realm}`;
}

/** One realm's report over one window. No poll: a week of answers does not move in a minute. */
export function usePipQuality(
  realm: PipRealm,
  days: number,
  enabled = true,
): UseQueryResult<PipQualityReport> {
  return useQuery({
    queryKey: pipQualityKeys.report(realm, days),
    queryFn: () => apiRequest<PipQualityReport>(adminSession(), pipQualityUrl(realm, days)),
    enabled,
  });
}

/** A 0..1 share as a whole percent, or a dash when there was nothing to divide. */
export function formatShare(share: number | null | undefined): string {
  if (share === null || share === undefined || !Number.isFinite(share)) return "—";
  return `${Math.round(share * 100)}%`;
}

/** The server's area names, in words. An unknown one is shown as sent. */
export const AREA_LABELS: Record<string, string> = {
  no_tool: "Answer only",
  platform: "Platform",
  calls: "Calls",
  callbacks: "Call-backs",
  leads: "Leads",
  campaigns: "Campaigns",
  agents: "Agents",
  knowledge: "Knowledge",
  numbers: "Numbers",
  team: "Team",
  settings: "Settings",
  integrations: "Integrations",
  billing: "Billing",
  reports: "Reports",
  routines: "Routines",
  other: "Other",
};

export function areaLabel(area: string): string {
  return lookup(AREA_LABELS, area) ?? area;
}

export const REASON_LABELS: Record<string, string> = {
  wrong: "Wrong",
  not_done: "Didn't do it",
  too_slow: "Too slow",
  misunderstood: "Didn't understand",
  other: "Other",
  fair_use: "Daily limit",
  consent: "Pip not turned on",
  paused: "AI paused",
};

/** A thumbs-down or refusal reason in words. An unknown one is shown as sent. */
export function reasonLabel(reason: string): string {
  return lookup(REASON_LABELS, reason) ?? reason;
}

export const WHY_LABELS: Record<PipExampleTurn["why"], string> = {
  thumbs_down: "Thumbs down",
  tool_failed: "A tool failed",
  action_undone: "Action undone",
  unfinished: "Unfinished",
};

export const LOW_LABELS: Record<PipQualityFigures["low"][number], string> = {
  thumbs_down: "Rated down",
  action_failures: "Actions failing",
};
