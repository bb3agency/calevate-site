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

/**
 * The create-campaign body — the SERVER's model, not a hand-written copy of it.
 *
 * This was an interface restating all seven fields, which is the drift the "typed
 * client generated from OpenAPI" convention forbids: a field added, renamed or made
 * nullable on `CreateCampaignIn` would have compiled cleanly here and failed at 422.
 * The two properties worth knowing are still worth saying, so they are said here
 * rather than re-declared:
 *
 * - `calling_hours` omitted/null = "no extra restriction, the platform's 09:00-21:00
 *   IST window applies". A campaign window may only NARROW that legal bound — the
 *   server rejects anything wider (`campaign_window_outside_platform_hours`).
 * - `consent_provenance` is all-or-nothing by construction: source and collection
 *   date travel as ONE nested object, so "a source with no date" is not a shape this
 *   client can send. Null is a campaign that has not answered §3's provenance
 *   question yet — a legal state to create, never a legal state to dial from
 *   (`consent_provenance_missing`).
 */
export type NewCampaign = Schemas["CreateCampaignIn"];
export type Classification = NewCampaign["classification"];

/**
 * Where a contact list's consent came from (SEC-COMP §3).
 *
 * Aliased from the generated schema rather than re-typed, because the enum IS the
 * compliance artefact: the five members are the only answers the gate recognises, and
 * `purchased_list` is one of them ON PURPOSE — a refusal can only be issued in writing
 * if the client is able to state the thing being refused. A hand-written union here
 * would eventually drift from the server's Literal, and the first symptom would be a
 * client unable to give the true answer.
 */
export type ConsentProvenance = Schemas["ConsentProvenanceIn"];
export type ConsentSource = ConsentProvenance["source"];

/**
 * A `<input type="date">` value → the `date-time` the API expects.
 *
 * Parsed as LOCAL midnight, not `Date.parse("2026-08-10")` which is UTC midnight: for
 * a client in IST the latter is 05:30 IST on the same day, so "collected today" would
 * be sent as a moment that has not happened yet in the only timezone this product
 * runs in — and the server refuses a future collection date. Local midnight is always
 * safely in the past at +05:30.
 */
export function consentCollectedAt(date: string): string | null {
  if (!date) return null;
  const parsed = new Date(`${date}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
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

/**
 * Answer §3's provenance question for a campaign that already exists.
 *
 * The reason this endpoint (and this hook) exist at all: the columns arrived after
 * clients had drafts, so every one of those drafts is now blocked on a question it was
 * never asked. Without an answer path the only "fix" is to delete a five-thousand-row
 * list and rebuild it to record a date — data loss dressed up as a compliance control.
 *
 * Draft-only, and that is the mechanism's integrity, not a limitation to work around:
 * if provenance could be edited on a running campaign, "dial first, pick a
 * lawful-sounding source afterwards" would be available and the declaration would
 * document nothing. The server refuses with `campaign_not_draft`; we do not pre-empt it.
 *
 * The launch check is invalidated on success because the answer is precisely what
 * changes it — including the answer that makes it WORSE (`purchased_list` swaps
 * `consent_provenance_missing` for `consent_source_refused`). The client must see that.
 */
export function useDeclareConsentProvenance(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (provenance: ConsentProvenance) =>
      apiRequest<{ [key: string]: string }>(
        session,
        `/v1/campaigns/${campaignId}/consent-provenance`,
        { method: "POST", body: provenance },
      ),
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
