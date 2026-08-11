"use client";

/**
 * Hook for GET /v1/performance (teardown §5 feature floor, SURFACES §2).
 *
 * The endpoint now has a real response model (`PerformanceOut`), so the shape is
 * ALIASED from the generated schema rather than mirrored by hand here — a mirror is
 * only ever as current as the last person who remembered to update it.
 *
 * What the generated type cannot say, and the screen must still honour:
 *
 * - `connect_rate_pct` / `qualify_rate_pct` are whole-number percentages, and null —
 *   not 0 — when the denominator is zero. "0%" means calls happened and none
 *   connected; null means there is nothing to measure yet. Collapsing the two tells a
 *   brand-new client their agent is failing before it has rung once.
 * - `funnel.qualified` is lead-level, not call-level: three calls that qualify one
 *   lead count once.
 * - `busiest_hours_ist` is always exactly 24 buckets, index = IST hour. Silent hours
 *   are 0, not absent.
 */

import { useQuery, keepPreviousData, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Performance = Schemas["PerformanceOut"];

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
