"use client";

/**
 * The NATIONAL DND SCRUB — the customer preference register, recorded per campaign.
 *
 * ## The blocker this closes, confirmed rather than assumed
 *
 * `compliance/preference_scrub.national_dnd_blocker` refuses a campaign whose
 * `classification` is in `PREFERENCE_SCRUBBED_CLASSIFICATIONS` — which is
 * `("promotional",)` — with `national_dnd_scrub_missing` until a run exists, and with
 * `national_dnd_scrub_expired` once the one on file has aged out. It is asked at LAUNCH
 * and again on EVERY DISPATCH TICK, and `record_scrub_run` — the only writer of
 * `preference_scrub_runs` anywhere in `apps/api` — has exactly one caller:
 * `POST /v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub`.
 *
 * That route had NO caller in either console. So no promotional campaign on this
 * platform could be launched by anybody, and the operator who could clear it had no
 * form: the gate was closed and the key was not cut. This module is the key.
 *
 * ## Four properties of the route that this module must not smooth over
 *
 * - **The scrub expires at MIDNIGHT IST, and `is_current` is the server's verdict on
 *   that, not `expires_at > now` computed here.** A run recorded after its own day has
 *   ended is a legitimate historical record that does NOT satisfy the gate, and the
 *   route says so in as many words. The console prints both — the verdict and the
 *   instant — and derives neither.
 * - **`submitted` is COUNTED SERVER-SIDE and is not a field.** The count that matters is
 *   how many contacts were pending when the run was recorded; a number an operator
 *   transcribes off a provider's report is a number that can disagree with the list
 *   about to dial, which is the exact disagreement the artefact exists to rule out. So
 *   there is no "submitted" box on the form and there must never be one.
 * - **`blocked_numbers` is the SUPPRESSED list, not the survivors.** A DLT portal hands
 *   back two files and pasting the wrong one suppresses everybody the scrub cleared.
 *   The field is named and labelled for what it is, everywhere it appears.
 * - **The confirmation is bound to the CAMPAIGN** — `record_preference_scrub:<id>` — so
 *   a header captured for one campaign cannot be replayed against another whose list
 *   nobody scrubbed. It is the one write in this module and it always carries it.
 *
 * ## Why it is a step-up and the carrier decision is not
 *
 * This turns a promotional campaign's launch gate GREEN on the strength of an artefact
 * only the operator has seen, and the thing it permits — dialling numbers on the
 * national preference register — is not undoable once a call is placed. `plan-tier`
 * carries no ceremony because both of its directions are reversible; this one is the
 * opposite case, and the API asks for the header rather than the console inventing it.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { hasKey } from "@/lib/lookup";

import { adminSession, viewAsSession } from "./admin";
import { apiRequest } from "./client";
import type { CampaignSummary } from "./campaigns";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One scrub, as an access provider's DLT platform reported it. */
export type PreferenceScrubIn = Schemas["PreferenceScrubIn"];
/** What the recording did, and whether the gate is now satisfied. */
export type PreferenceScrubOut = Schemas["PreferenceScrubOut"];
/** The launch gate's own answer for one campaign — `(rule, reason)` pairs. */
export type LaunchCheck = Schemas["LaunchCheckOut"];
export type Blocker = Schemas["BlockerOut"];

export function preferenceScrubPath(tenantId: string, campaignId: string): string {
  return (
    `/v1/admin/tenants/${encodeURIComponent(tenantId)}` +
    `/campaigns/${encodeURIComponent(campaignId)}/preference-scrub`
  );
}

/**
 * The step-up string, spelled ONCE here.
 *
 * It mirrors `national_dnd_routes.preference_scrub_confirmation` exactly. ⚠ It is
 * `record_preference_scrub:<id>` and NOT `preference_scrub:<id>` — the shorter spelling
 * was what a previous reading of this route recorded from memory, and a console sending
 * it would have every scrub refused with a header the operator could not debug. Read the
 * function, not the route's prose.
 */
export function preferenceScrubConfirmation(campaignId: string): string {
  return `record_preference_scrub:${campaignId}`;
}

/**
 * The classifications the register scopes, mirrored from
 * `PREFERENCE_SCRUBBED_CLASSIFICATIONS`. A `Record` and not an array so a member added
 * to the API's tuple is a deliberate edit here rather than a campaign silently offered a
 * scrub it does not need — or worse, denied one it does.
 */
const SCRUBBED_CLASSIFICATIONS: Record<string, true> = { promotional: true };

/**
 * The campaign states with something left to scrub (`SCRUBBABLE_CAMPAIGN_STATUSES`). A
 * completed or cancelled campaign will not dial again, and recording evidence against it
 * would be evidence of nothing.
 */
const SCRUBBABLE_STATUSES: Record<string, true> = {
  draft: true,
  scheduled: true,
  running: true,
  paused: true,
};

/**
 * Does this campaign need a scrub, and can one still be recorded against it?
 *
 * `classification` and `status` are plain STRINGS on `CampaignSummaryOut`, so this is a
 * membership test against a named set and never `classification === "promotional" ? …`.
 * The fail direction is the safe one in both halves: a classification this build does
 * not know is NOT offered a scrub (the register does not scope it as far as we can tell,
 * and inventing an artefact is worse than not offering a form), and a status this build
 * does not know is not either.
 */
export function needsPreferenceScrub(campaign: CampaignSummary): boolean {
  return (
    hasKey(SCRUBBED_CLASSIFICATIONS, campaign.classification) &&
    hasKey(SCRUBBABLE_STATUSES, campaign.status)
  );
}

/** The two rules this screen is about, as the launch check names them. */
export const SCRUB_BLOCKER_RULES: Record<string, true> = {
  national_dnd_scrub_missing: true,
  national_dnd_scrub_expired: true,
};

/** This campaign's scrub blocker, as the SERVER stated it, or `null`. */
export function scrubBlocker(check: LaunchCheck | undefined): Blocker | null {
  if (!check) return null;
  return check.blockers.find((blocker) => hasKey(SCRUB_BLOCKER_RULES, blocker.rule)) ?? null;
}

/**
 * A client's campaigns, read through impersonation — the D-22 split every admin tenant
 * screen uses. There is no admin-realm list of a tenant's campaigns, and `campaigns:read`
 * is non-mutating, so the view-as session is both the available shape and the right one.
 */
export function useTenantCampaigns(slug: string): UseQueryResult<CampaignSummary[]> {
  return useQuery({
    queryKey: ["admin", "campaigns", slug],
    queryFn: () => apiRequest<CampaignSummary[]>(viewAsSession(slug), "/v1/campaigns"),
    enabled: Boolean(slug),
  });
}

/**
 * The launch gate's live answer for one campaign, read the same way.
 *
 * This is what tells an operator whether the scrub on file is still good BEFORE they
 * record another one — `national_dnd_blocker` is what the launch and every dispatch tick
 * ask, so the console reads the gate's own verdict rather than a second opinion.
 */
export function useTenantLaunchCheck(
  slug: string,
  campaignId: string | null,
): UseQueryResult<LaunchCheck> {
  return useQuery({
    queryKey: ["admin", "campaign-check", slug, campaignId],
    queryFn: () =>
      apiRequest<LaunchCheck>(viewAsSession(slug), `/v1/campaigns/${campaignId}/launch-check`),
    enabled: Boolean(slug) && Boolean(campaignId),
    // The gate's answer changes at midnight IST whether or not anybody touches it, so a
    // cached "ready" is exactly the reassurance this read exists to stop anyone giving.
    staleTime: 0,
  });
}

/** What the operator has typed, before it is a request. */
export interface ScrubDraft {
  /** The access provider whose DLT platform ran it. */
  provider: string;
  /** Their reference for the run — the handle that makes the record checkable. */
  scrubRef: string;
  /** What the operator typed into a `datetime-local` labelled IST. */
  scrubbedAtInput: string;
  /** The SUPPRESSED numbers, pasted. One per line or comma-separated. */
  blockedNumbers: string;
}

/**
 * The pasted block → the list the API takes.
 *
 * Split on any run of newline, comma, semicolon or tab, because a DLT portal's export
 * pasted through a spreadsheet arrives as any of them. NOTHING is normalized beyond
 * trimming: `normalize_phone` on the server decides what is a number, and what it cannot
 * read is COUNTED `malformed` and reported back rather than suppressed on a guess. A
 * console that cleaned the list here would be deciding, silently, which numbers the
 * register blocked.
 */
export function splitBlockedNumbers(pasted: string): string[] {
  return pasted
    .split(/[\s,;]+/)
    .map((entry) => entry.trim())
    .filter((entry) => entry !== "");
}

/** How many numbers one recorded run may report (`MAX_BLOCKED_NUMBERS`). */
export const MAX_BLOCKED_NUMBERS = 5000;

/**
 * Why this scrub cannot be recorded yet, or `null` when it can.
 *
 * A PREVIEW of the route's own refusals, asked where the operator is typing: the field
 * lengths `PreferenceScrubIn` declares, the ceiling on the paste, and
 * `preference_scrub_in_the_future`. Each names what to do rather than the rule it came
 * from. The server refuses all of them again.
 */
export function scrubBlockReason(draft: ScrubDraft, instant: string | null): string | null {
  if (draft.provider.trim().length < 2) {
    return "Name the access provider whose DLT platform ran the scrub — their name as you would quote it to them.";
  }
  if (draft.scrubRef.trim().length < 3) {
    return (
      "Copy the provider's reference for this run. It is the handle that makes this " +
      "record checkable against their portal a year from now."
    );
  }
  if (instant === null) {
    return "Give the date and time the provider ran the scrub, as their report states it (IST).";
  }
  if (new Date(instant).getTime() > Date.now()) {
    return (
      "That moment has not happened yet. A scrub timestamp records something the " +
      "provider has already done — check the date, and check you have not typed a UTC " +
      "time into a field that means IST."
    );
  }
  if (splitBlockedNumbers(draft.blockedNumbers).length > MAX_BLOCKED_NUMBERS) {
    return (
      `One recorded run may report up to ${MAX_BLOCKED_NUMBERS.toLocaleString("en-IN")} ` +
      "suppressed numbers. Record the run in parts, each with its own reference."
    );
  }
  return null;
}

/** The draft as the API wants it. `blocked_numbers` may legitimately be empty. */
export function toScrubBody(draft: ScrubDraft, instant: string): PreferenceScrubIn {
  return {
    provider: draft.provider.trim(),
    scrub_ref: draft.scrubRef.trim(),
    scrubbed_at: instant,
    blocked_numbers: splitBlockedNumbers(draft.blockedNumbers),
  };
}

/**
 * Record one scrub.
 *
 * ADMIN realm with the tenant in the PATH (`admin:tenants` is a mutating permission, so
 * D-22 would correctly refuse an impersonating session), and the confirmation header on
 * every call — the route requires it unconditionally.
 *
 * What it invalidates, and why each:
 *   * this campaign's launch check, which is the gate this write exists to turn green;
 *   * the campaign list, because suppressing numbers moves the contact counts on it.
 */
export function useRecordPreferenceScrub(
  tenantId: string,
  slug: string,
  campaignId: string | null,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ draft, instant }: { draft: ScrubDraft; instant: string }) =>
      apiRequest<PreferenceScrubOut>(
        adminSession(),
        preferenceScrubPath(tenantId, campaignId ?? ""),
        {
          method: "POST",
          body: toScrubBody(draft, instant),
          confirmAction: preferenceScrubConfirmation(campaignId ?? ""),
        },
      ),
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: ["admin", "campaign-check", slug, campaignId] }),
        client.invalidateQueries({ queryKey: ["admin", "campaigns", slug] }),
      ]),
  });
}
