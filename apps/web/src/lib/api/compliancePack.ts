"use client";

/**
 * D-943's reads and writes: the promo check, the call purpose, the rights desk and the
 * short caller notice.
 *
 * The rights desk LOGS a request with the person's number in the BODY of a POST (hard rule
 * 6: never a URL, never a cache key); everything it reads back names the person by a
 * one-way code only. The promo check and the short notice are about the account's own
 * script and settings and carry no caller's data, so they are ordinary queries.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type PromoReport = Schemas["PromoReportOut"];
export type PromoFinding = Schemas["FindingOut"];
export type AgentPromoCheck = Schemas["AgentPromoCheckOut"];
export type CampaignPurpose = Schemas["CampaignPurposeOut"];
export type RightsDesk = Schemas["RightsDeskOut"];
export type RightsRequest = Schemas["RightsRequestOut"];
export type RightsRequestIn = Schemas["RightsRequestIn"];
export type RightsRequestCloseIn = Schemas["RightsRequestCloseIn"];
export type ShortNotice = Schemas["ShortNoticeOut"];
export type NoticeLanguage = ShortNotice["language"];

export const compliancePackKeys = {
  agentPromo: (org: string, agentId: string) => ["promo-check", org, agentId] as const,
  campaignPurpose: (org: string, campaignId: string) => ["call-purpose", org, campaignId] as const,
  desk: (org: string) => ["rights-desk", org] as const,
  shortNotice: (org: string, language: NoticeLanguage) => ["short-notice", org, language] as const,
};

/** The script being edited, checked as a placed call would say it. */
export function useAgentPromoCheck(session: Session, agentId: string): UseQueryResult<AgentPromoCheck> {
  return useQuery({
    queryKey: compliancePackKeys.agentPromo(session.orgSlug, agentId),
    queryFn: () => apiRequest<AgentPromoCheck>(session, `/v1/compliance/promo-check/agents/${agentId}`),
    staleTime: 15_000,
  });
}

/** What kind of call a campaign places, and whether its live script is promotional. */
export function useCampaignPurpose(session: Session, campaignId: string): UseQueryResult<CampaignPurpose> {
  return useQuery({
    queryKey: compliancePackKeys.campaignPurpose(session.orgSlug, campaignId),
    queryFn: () =>
      apiRequest<CampaignPurpose>(session, `/v1/compliance/call-purpose/campaigns/${campaignId}`),
    staleTime: 15_000,
  });
}

export const RIGHTS_DESK_LIMIT = 100;

/** How often the desk is read while a row waits on a running erasure. The worker closes
 * the row when the erasure completes (`rights_desk.answer_with_completed_erasure`), so the
 * desk learns of it only by asking; the erasure register polls on the same clock. */
export const DESK_ERASURE_POLL_MS = 15_000;

export function useRightsDesk(
  session: Session,
  { waitsOn }: { waitsOn?: (request: RightsRequest) => boolean } = {},
): UseQueryResult<RightsDesk> {
  return useQuery({
    queryKey: compliancePackKeys.desk(session.orgSlug),
    queryFn: () =>
      apiRequest<RightsDesk>(session, `/v1/compliance/rights-requests?limit=${RIGHTS_DESK_LIMIT}`),
    refetchInterval: untilRefused((query) =>
      waitsOn && query.state.data?.items.some(waitsOn) ? DESK_ERASURE_POLL_MS : false),
  });
}

/** Log a request. Not retried: the server writes an audit row per request. */
export function useLogRightsRequest(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RightsRequestIn) =>
      apiRequest<RightsRequest>(session, "/v1/compliance/rights-requests", {
        method: "POST",
        body,
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: compliancePackKeys.desk(session.orgSlug) }),
  });
}

export function useCloseRightsRequest(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: RightsRequestCloseIn }) =>
      apiRequest<RightsRequest>(session, `/v1/compliance/rights-requests/${id}/close`, {
        method: "POST",
        body,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: compliancePackKeys.desk(session.orgSlug) }),
  });
}

export function useShortNotice(session: Session, language: NoticeLanguage): UseQueryResult<ShortNotice> {
  return useQuery({
    queryKey: compliancePackKeys.shortNotice(session.orgSlug, language),
    queryFn: () => apiRequest<ShortNotice>(session, `/v1/compliance/caller-notice/short?language=${language}`),
    staleTime: 30_000,
  });
}
