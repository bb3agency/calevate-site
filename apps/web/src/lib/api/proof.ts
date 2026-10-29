"use client";

/**
 * Proof a client can check (D-944): how fast their agent answered each IST week
 * (`/v1/analytics/reply-speed`), what each answered call, lead and booking cost
 * (`/v1/analytics/cost-per-result`), and the owner's daily summary switch
 * (`/v1/notifications/daily-summary`). Money is a decimal STRING, formatted and never parsed.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { languageName } from "@/lib/callReview";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ReplySpeed = Schemas["ReplySpeedOut"];
export type WeekSpeed = Schemas["WeekSpeed"];
export type FleetReplySpeed = Schemas["FleetReplySpeedOut"];
export type CostPerResult = Schemas["CostPerResultOut"];
export type CostWindow = Schemas["CostWindowOut"];
export type DailySummarySetting = Schemas["DailySummaryOut"];

export const DAILY_SUMMARY_PATH = "/v1/notifications/daily-summary";

/** Three families (`lib/live/topics.ts`): each moves with different changes. */
export const proofKeys = {
  speed: (org: string, weeks: number) => ["reply-speed", org, weeks] as const,
  cost: (org: string) => ["cost-per-result", org] as const,
  summary: (org: string) => ["daily-summary", org] as const,
  fleet: (weeks: number) => ["admin", "ops", "reply-speed", weeks] as const,
};

/** Every client's reply speed by language, for the admin console. `enabled` is `!refused`. */
export function useFleetReplySpeed(weeks: number, enabled = true): UseQueryResult<FleetReplySpeed> {
  return useQuery({
    queryKey: proofKeys.fleet(weeks),
    queryFn: () =>
      apiRequest<FleetReplySpeed>(adminSession(), `/v1/ops/reply-speed-by-language?weeks=${weeks}`),
    enabled,
  });
}

/** The every-language row of each week; the server always sends one per week. */
export const ALL_LANGUAGES = "all";
/** Calls whose language neither the call nor its agent recorded. */
export const UNKNOWN_LANGUAGE = "unknown";

export function useReplySpeed(session: Session, weeks = 4): UseQueryResult<ReplySpeed> {
  return useQuery({
    queryKey: proofKeys.speed(session.orgSlug, weeks),
    queryFn: () => apiRequest<ReplySpeed>(session, `/v1/analytics/reply-speed?weeks=${weeks}`),
    staleTime: 60_000,
  });
}

export function useCostPerResult(
  session: Session,
  options: { enabled?: boolean } = {},
): UseQueryResult<CostPerResult> {
  return useQuery({
    queryKey: proofKeys.cost(session.orgSlug),
    queryFn: () => apiRequest<CostPerResult>(session, "/v1/analytics/cost-per-result"),
    staleTime: 60_000,
    enabled: options.enabled ?? true,
  });
}

export function useDailySummary(
  session: Session,
  options: { enabled?: boolean } = {},
): UseQueryResult<DailySummarySetting> {
  return useQuery({
    queryKey: proofKeys.summary(session.orgSlug),
    queryFn: () => apiRequest<DailySummarySetting>(session, DAILY_SUMMARY_PATH),
    enabled: options.enabled ?? true,
  });
}

export function useSetDailySummary(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      apiRequest<DailySummarySetting>(session, DAILY_SUMMARY_PATH, {
        method: "PUT",
        body: { enabled },
      }),
    onSuccess: (data) => client.setQueryData(proofKeys.summary(session.orgSlug), data),
  });
}

/** A roll-up's language key as a name: "te-IN" → "Telugu", `unknown` → "Language not known". */
export function speedLanguageName(key: string): string {
  if (key === UNKNOWN_LANGUAGE) return "Language not known";
  return languageName(key) ?? key;
}

/** Milliseconds as seconds with one decimal ("1.4 s"), or null when not measured. */
export function secondsText(ms: number | null | undefined): string | null {
  return ms == null ? null : `${(ms / 1000).toFixed(1)} s`;
}

/** A share 0..1 as a whole percentage, or null for a week with no calls. */
export function percentText(share: number | null | undefined): string | null {
  return share == null ? null : `${Math.round(share * 100)}%`;
}
