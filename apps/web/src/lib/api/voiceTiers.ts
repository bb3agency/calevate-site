"use client";

/**
 * The billing screen's Clear-against-Studio comparison and its "This month / All time"
 * credit view (D-869). Owner-only (`billing:read`).
 *
 * Every rupee is a decimal STRING. `from_inr_per_min`/`to_inr_per_min` are the card's range
 * across packs; `your_inr_per_min` is what this account's next minute on that tier costs
 * (null with no open credit); `minutes_left` is null for the same reason. `recommended` and
 * `recommendation_reason` answer "which is right for me" from the account's own use.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type VoiceTierComparison = Schemas["VoiceTierComparisonOut"];
export type VoiceTierCompare = Schemas["VoiceTierCompareOut"];
export type CreditUsage = Schemas["CreditUsageOut"];
export type CreditUsagePeriod = Schemas["CreditUsagePeriodOut"];

export const voiceTierKeys = {
  comparison: (org: string) => ["billing", org, "voice-tiers"] as const,
  creditUsage: (org: string) => ["billing", org, "credit-usage"] as const,
};

export function useVoiceTierComparison(session: Session): UseQueryResult<VoiceTierComparison> {
  return useQuery({
    queryKey: voiceTierKeys.comparison(session.orgSlug),
    queryFn: () => apiRequest<VoiceTierComparison>(session, "/v1/billing/voice-tiers"),
  });
}

/** Both periods in one read; the toggle chooses `this_month` or `all_time`. */
export function useCreditUsage(session: Session): UseQueryResult<CreditUsage> {
  return useQuery({
    queryKey: voiceTierKeys.creditUsage(session.orgSlug),
    queryFn: () => apiRequest<CreditUsage>(session, "/v1/billing/credit-usage"),
  });
}
