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
 *
 * **204, and the invalidation above is why that is enough.** The endpoint used to answer
 * `{"status": "recorded"}` — a constant, in a shape the generated client could only
 * describe as an index signature. Whether the answer unblocks dialling is `/launch-check`'s
 * to state, and this hook re-reads it; a copy of that verdict in the declaration's own
 * response would be a second thing to keep in step with the gate.
 */
export function useDeclareConsentProvenance(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (provenance: ConsentProvenance) =>
      apiRequest<void>(session, `/v1/campaigns/${campaignId}/consent-provenance`, {
        method: "POST",
        body: provenance,
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
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // `scheduled` polls for the same reason `running` does: the thing the client is
      // watching for is a change they did not cause. A scheduled campaign flips to
      // running on a dispatch tick, and a screen that only learned that on a manual
      // reload would show "Starts 10:00" at 10:05.
      return status === "running" || status === "paused" || status === "scheduled"
        ? 15_000
        : false;
    },
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

/**
 * Stop or restart the dialling. **204 on both**, so there is nothing to read back — the
 * screen re-reads progress, which is where the campaign's state has always come from.
 * The constant `{"status": "paused"}` this used to return said only what the URL it was
 * posted to already said.
 */
export function usePauseCampaign(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: "pause" | "resume") =>
      apiRequest<void>(session, `/v1/campaigns/${campaignId}/${action}`, {
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

/* ------------------------------------------------------------------ scheduling */

export type ScheduledStart = Schemas["ScheduleOut"];

/**
 * A `<input type="date">` + `<input type="time">` pair → the offset-carrying
 * `date-time` the API demands.
 *
 * **The +05:30 is written in, not taken from the browser.** `new Date("2026-08-17T10:00")`
 * is parsed in the VIEWER's zone, so the same two fields would mean 10:00 IST for a
 * client in Hyderabad and 10:00 GMT — 15:30 IST — for an operator viewing the account
 * from London (D-22 impersonation makes that a real session, not a hypothetical). The
 * campaign screen's every other time is rendered in IST (`formatIST`), the calling
 * window is IST law, and the client picking the time is in India: the input means IST,
 * so it is sent as IST.
 *
 * Returns null for an incomplete or unparseable pair rather than a guess — the server
 * refuses a start with no offset outright (`campaign_schedule_timezone_missing`), and
 * inventing one here is exactly what that refusal exists to prevent.
 */
export function scheduleStartAt(date: string, time: string): string | null {
  if (!date || !time) return null;
  const candidate = `${date}T${time.length === 5 ? `${time}:00` : time}+05:30`;
  const parsed = new Date(candidate);
  return Number.isNaN(parsed.getTime()) ? null : candidate;
}

/**
 * Set a one-time start. The launch check is invalidated because a scheduled campaign is
 * still answerable by it — the server runs the SAME gate when the schedule fires, so
 * "would this launch right now" stays the question worth showing.
 */
export function useScheduleCampaign(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (startAt: string) =>
      apiRequest<ScheduledStart>(session, `/v1/campaigns/${campaignId}/schedule`, {
        method: "POST",
        body: { start_at: startAt },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaign-check", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
    },
  });
}

/**
 * What one stop button actually stopped, and what the campaign is now.
 *
 * HAND-WRITTEN, and marked: `ScheduleCancelledOut` exists on the server now, so this
 * becomes `Schemas["ScheduleCancelledOut"]` at the next `pnpm gen:api` — the same swap
 * the activity types went through. Mirrored exactly in the meantime, because a mirror
 * that drifts is the defect this convention exists to prevent.
 */
export interface CancelledSchedule {
  /** Which promise was held: a one-time start, or a weekly repeat. */
  cancelled: "one_time" | "recurring";
  /** The campaign's status AFTER the cancellation — see the hook below. */
  status: string;
}

/**
 * Cancel a pending start OR stop a repeat — one button, because it is one column.
 *
 * The response carries the status the campaign is ACTUALLY in afterwards: a campaign
 * that was waiting goes back to `draft`, and one that is mid-dial keeps running, because
 * stopping a repeat means "do not start this again" and never "abandon the calls going
 * out now". The screen re-reads progress rather than assuming either.
 */
export function useUnscheduleCampaign(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<CancelledSchedule>(session, `/v1/campaigns/${campaignId}/schedule`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaign-check", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
    },
  });
}

/* ------------------------------------------------------------------ recurrence */

/**
 * The recurrence wire types, aliased from the generated client.
 *
 * Two fields carry the design and are worth reading here rather than in the server:
 * `days` is ISO weekday numbers (1 = Monday … 7 = Sunday) and `at` is an IST wall clock
 * — a repeat is a TIME OF DAY, never an instant, which is what keeps it free of
 * month-end ambiguity. `last_skipped_at`/`last_skipped_reason` exist because a missed
 * occurrence is SKIPPED rather than caught up (D-79), and a skip the client cannot see
 * is a dial they will ask about.
 */
export type CampaignRecurrence = Schemas["RecurrenceOut"];
export type NewRecurrence = Schemas["RecurrenceIn"];
export type RecurrenceSet = Schemas["RecurrenceSetOut"];

/**
 * A `<input type="date">` value → the offset-carrying `date-time` the API demands for a
 * repeat's end date.
 *
 * The +05:30 is written in rather than taken from the browser, for `scheduleStartAt`'s
 * reason: an operator viewing the account from London (D-22) must not send a different
 * instant than the client would for the same two digits. End of day, not midnight, so
 * "until the 30th" includes the 30th — a repeat that stops the morning of the day the
 * client typed is the kind of off-by-one that silently drops a run.
 */
export function recurrenceUntil(date: string): string | null {
  if (!date) return null;
  const candidate = `${date}T23:59:00+05:30`;
  return Number.isNaN(new Date(candidate).getTime()) ? null : candidate;
}

/**
 * Set (or replace) the repeat. The launch check is invalidated for the same reason
 * `useScheduleCampaign` invalidates it: a repeating campaign is still answerable by
 * "would this launch right now", and the server runs that identical gate on every
 * occurrence.
 */
export function useSetRecurrence(session: Session, campaignId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: NewRecurrence) =>
      apiRequest<RecurrenceSet>(session, `/v1/campaigns/${campaignId}/recurrence`, {
        method: "POST",
        body: payload,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaign-check", campaignId] });
      void client.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
    },
  });
}
