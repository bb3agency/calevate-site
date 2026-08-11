"use client";

/**
 * Hook for GET /v1/performance (teardown §5 feature floor, SURFACES §2).
 *
 * The endpoint returns a plain dict (see apps/api/crm/performance.py), so the
 * generated schema.d.ts has no named type for it — the shape is declared HERE,
 * next to the only consumer, and mirrors the server's return statement 1:1.
 * If the server response model gets typed later, swap this for the generated
 * alias in client.ts like every other endpoint.
 */

import { useQuery, keepPreviousData, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";

export interface Performance {
  /** Echo of the requested window, clamped server-side to 1–365. */
  days: number;
  funnel: {
    calls: number;
    connected: number;
    /** Lead-level, not call-level: three calls that qualify one lead count once. */
    qualified: number;
  };
  /**
   * Whole-number percentages, and null — not 0 — when the denominator is zero.
   * "0%" means calls happened and none connected; null means nothing to measure
   * yet. The UI must keep that distinction (same doctrine as the margin panel).
   */
  connect_rate_pct: number | null;
  qualify_rate_pct: number | null;
  inbound: number;
  outbound: number;
  avg_duration_s: number | null;
  /** outcome tag (or status when untagged) → count. */
  outcomes: Record<string, number>;
  /** Always exactly 24 buckets, index = IST hour. Silent hours are 0, not absent. */
  busiest_hours_ist: number[];
}

export function usePerformance(session: Session, days: number): UseQueryResult<Performance> {
  return useQuery({
    queryKey: ["performance", session.orgSlug, days],
    queryFn: () => apiRequest<Performance>(session, `/v1/performance?days=${days}`),
    // Aggregates over closed calls; nothing here moves second-to-second.
    staleTime: 60_000,
    // Switching 7 → 30 → 90 keeps the previous numbers on screen instead of
    // flashing a skeleton — the toggle should feel like a re-filter, not a
    // navigation.
    placeholderData: keepPreviousData,
  });
}
