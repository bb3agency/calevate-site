"use client";

/**
 * Campaign hooks (FLOWS §5, SURFACES §2b).
 *
 * The one that shapes the screen is `useLaunchCheck`: SURFACES §2b asks for a launch
 * button "disabled with reasons listed until green", so the check is a first-class
 * query the page renders from, not a validation that happens after a click. The
 * server re-runs the identical gate on `POST /launch` — this hook is a preview, never
 * the enforcement.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LaunchCheck = Schemas["LaunchCheckOut"];
export type LaunchResult = Schemas["LaunchOut"];
export type CampaignProgress = Schemas["ProgressOut"];
export type AddContactsResult = Schemas["AddContactsOut"];
export type Classification = "promotional" | "transactional" | "service";

export interface NewCampaign {
  agent_id: string;
  name: string;
  classification: Classification;
  number_id?: string | null;
  dlt_template_id?: string | null;
  concurrency?: number;
  // Omitted/null = "no extra restriction, the platform's 09:00-21:00 IST window
  // applies". A campaign window may only NARROW that legal bound — the server
  // rejects anything wider (campaign_window_outside_platform_hours).
  calling_hours?: { start: string; end: string } | null;
}

export type CampaignNumber = Schemas["NumberOut"];
export type DltTemplate = Schemas["TemplateOut"];
export type CampaignSummary = Schemas["CampaignSummaryOut"];

export function useCampaigns(session: Session): UseQueryResult<CampaignSummary[]> {
  return useQuery({
    queryKey: ["campaigns", session.orgSlug],
    queryFn: () => apiRequest<CampaignSummary[]>(session, "/v1/campaigns"),
  });
}

export function useCampaignNumbers(session: Session) {
  return useQuery({
    queryKey: ["campaign-numbers", session.orgSlug],
    queryFn: () => apiRequest<CampaignNumber[]>(session, "/v1/campaigns/numbers"),
    staleTime: 5 * 60_000,
  });
}

export function useDltTemplates(session: Session) {
  return useQuery({
    queryKey: ["dlt-templates", session.orgSlug],
    queryFn: () => apiRequest<DltTemplate[]>(session, "/v1/campaigns/templates"),
    staleTime: 5 * 60_000,
  });
}

export function useCreateCampaign(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: NewCampaign) =>
      apiRequest<Schemas["CreateCampaignOut"]>(session, "/v1/campaigns", {
        method: "POST",
        body: payload,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] }),
  });
}

export function useAddContacts(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (contacts: { phone: string; name?: string | null }[]) =>
      apiRequest<AddContactsResult>(session, `/v1/campaigns/${campaignId}/contacts`, {
        method: "POST",
        body: { contacts },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign-check", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaign", campaignId] });
    },
  });
}

export function useLaunchCheck(
  session: Session,
  campaignId: string | null,
): UseQueryResult<LaunchCheck> {
  return useQuery({
    queryKey: ["campaign-check", campaignId],
    queryFn: () => apiRequest<LaunchCheck>(session, `/v1/campaigns/${campaignId}/launch-check`),
    enabled: Boolean(campaignId),
  });
}

export function useCampaignProgress(session: Session, campaignId: string | null) {
  return useQuery({
    queryKey: ["campaign", campaignId],
    queryFn: () => apiRequest<CampaignProgress>(session, `/v1/campaigns/${campaignId}`),
    enabled: Boolean(campaignId),
    // Poll only while the campaign is actually dispatching, and no faster than the
    // dispatcher ticks (30s) — a completed campaign polled every 15s is pure noise on
    // a phone connection, which is what most of these clients are on.
    refetchInterval: (query) =>
      query.state.data?.status === "running" || query.state.data?.status === "paused"
        ? 15_000
        : false,
  });
}

export function useLaunchCampaign(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<LaunchResult>(session, `/v1/campaigns/${campaignId}/launch`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaign-check", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
    },
  });
}

export function usePauseCampaign(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: "pause" | "resume") =>
      apiRequest<{ status: string }>(session, `/v1/campaigns/${campaignId}/${action}`, {
        method: "POST",
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign", campaignId] });
      // The list carries the status too, and it is one click away ("Start another
      // campaign") — without this it keeps showing "running" for a paused campaign.
      void client.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
    },
  });
}

/**
 * CSV → contacts, parsed in the browser so the client sees the row count before
 * committing. Deliberately forgiving about the header row and column order, and
 * deliberately NOT forgiving about the numbers themselves: the API normalizes and
 * counts what it cannot parse rather than guessing a country code.
 */
export function parseContactCsv(text: string): { phone: string; name?: string }[] {
  const rows = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (rows.length === 0) return [];

  const first = rows[0].toLowerCase();
  const hasHeader = first.includes("phone") || first.includes("number") || first.includes("mobile");
  const header = hasHeader ? rows[0].split(",").map((c) => c.trim().toLowerCase()) : [];
  const phoneIdx = hasHeader
    ? Math.max(
        0,
        header.findIndex((c) => c.includes("phone") || c.includes("number") || c.includes("mobile")),
      )
    : 0;
  const nameIdx = hasHeader ? header.findIndex((c) => c.includes("name")) : 1;

  return rows.slice(hasHeader ? 1 : 0).map((line) => {
    const cells = line.split(",").map((c) => c.trim());
    const name = nameIdx >= 0 ? cells[nameIdx] : undefined;
    return { phone: cells[phoneIdx] ?? "", ...(name ? { name } : {}) };
  });
}
