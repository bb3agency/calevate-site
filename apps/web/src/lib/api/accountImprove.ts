"use client";

/**
 * The account-wide Improve page (`GET /v1/improve`, `campaigns/account_improve.py`) and Pip's
 * weekly summaries (`GET /v1/improve/weekly-summaries`). One read feeds every section; the
 * knowledge gaps come from the teach questions (`teachQuestions.ts`), which already serve
 * "What your agents know".
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { Holder } from "./improve";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AccountImprove = Schemas["AccountImproveOut"];
export type NumberHealth = Schemas["NumberHealthOut"];
export type HolderRow = Schemas["HolderRowOut"];
export type Difference = Schemas["DifferenceOut"];
export type MistakePattern = Schemas["MistakePatternOut"];
export type PipFix = Schemas["PipFixOut"];
export type WeeklySummary = Schemas["WeeklySummaryOut"];

/** Past weeks one read lists (`weekly_summary.MAX_LISTED`). */
export const PAST_WEEKS = 26;

export const accountImproveKey = (org: string) => ["account-improve", org] as const;
export const weeklySummariesKey = (org: string, limit: number) => ["weekly-summaries", org, limit] as const;

export function useAccountImprove(session: Session): UseQueryResult<AccountImprove> {
  return useQuery({
    queryKey: accountImproveKey(session.orgSlug),
    queryFn: () => apiRequest<AccountImprove>(session, "/v1/improve"),
  });
}

export function useWeeklySummaries(session: Session, limit: number, enabled = true): UseQueryResult<WeeklySummary[]> {
  return useQuery({
    queryKey: weeklySummariesKey(session.orgSlug, limit),
    queryFn: () => apiRequest<WeeklySummary[]>(session, `/v1/improve/weekly-summaries?limit=${limit}`),
    enabled,
  });
}

/** The holder a row names, in the shape the Improve cards and Pip's draft path take. */
export function holderOf(row: { kind: HolderRow["kind"]; id: string }): Holder {
  return { kind: row.kind, id: row.id };
}

/** A campaign's or line's own page, on its Improve tab or section. */
export function holderImproveHref(slug: string, holder: Holder): string {
  return holder.kind === "campaign"
    ? `/c/${slug}/campaigns/${encodeURIComponent(holder.id)}?tab=improve`
    : `/c/${slug}/inbound/${encodeURIComponent(holder.id)}#line-improve`;
}

/** Where a holder's script Versions are, with Put back on each. */
export function holderVersionsHref(slug: string, holder: Holder): string {
  return holder.kind === "campaign"
    ? `/c/${slug}/campaigns/${encodeURIComponent(holder.id)}`
    : `/c/${slug}/inbound/${encodeURIComponent(holder.id)}#line-script`;
}

/** Company training, the training every agent is given. */
export const companyTrainingHref = (slug: string) => `/c/${slug}/knowledge?tab=training`;
