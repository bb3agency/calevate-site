"use client";

/**
 * Trial periods, from the admin side — the one act that carries a client for free.
 *
 * `POST|GET /v1/admin/tenants/{tenant_id}/trial` (`apps/api/billing/trial_routes.py`) has
 * been mounted and in the OpenAPI since D-536 with NO caller in this console: starting a
 * trial meant assembling a `curl` with an `X-Confirm-Action` header against production.
 * That was defensible while it was a rare commercial gift (ROADMAP §2 — "admin can be CLI
 * + SQL where UI would slow us down") and stopped being defensible when D-551 made an
 * empty wallet stop INBOUND ANSWERING too: a trial is now the cheapest answer to "a
 * brand-new client has no credit and their phone stopped after one call", which is a
 * thing an operator does while the client is on the line.
 *
 * ## WHY THIS IS ITS OWN MODULE AND NOT A FIFTH HOOK IN `billing.ts`
 *
 * `billing.ts` is the CLIENT realm's wallet top-up (`/v1/billing/...`, the client's own
 * session, the client's own query keys). These are admin-realm reads and writes against
 * `/v1/admin/tenants/{id}/...`, and CLAUDE.md keeps the two realms apart deliberately —
 * separate route groups, separate session modules, never shared session logic. Every
 * other admin subject in this directory already has its own module (`credits.ts`,
 * `creditLots.ts`, `erasure.ts`, `holds.ts`); this follows that, rather than inventing a
 * second arrangement for one endpoint.
 *
 * ## THE THREE PROPERTIES OF THE ROUTES THIS MODULE MUST NOT SMOOTH OVER
 *
 * - **Starting one takes a step-up header that carries the DAYS**, because the founder
 *   chose days with NO spend ceiling, so the number of days is the entire bound on what
 *   this act can cost. `startTrialConfirmation` is copied from the route verbatim: an
 *   operator who meant 14 and typed 140 has to key 140 twice. Ending one takes NO header,
 *   which is the route's own rule and not this module's opinion — it is the direction
 *   that stops us spending money, and putting a second factor in front of the safe act
 *   while the expensive one is one call away is how a console teaches people to click
 *   through ceremony.
 * - **The read may answer `null`.** A client who has never been given a trial is not an
 *   error and not an empty object; `TrialStatus | null` is carried all the way to the
 *   screen so "never had one" cannot be confused with "we could not read it" (§52).
 * - **`cost_to_us_inr` is OUR supplier cost and is operator-only.** It is the other half
 *   of "no spend ceiling" — the founder chose days only, so this figure is the visibility
 *   that makes the choice survivable. No client surface has ever shown `unit_cost_paid`
 *   and none starts here. It is a STRING and is never parsed (hard rule 7).
 *
 * Types come from `schema.d.ts` (`pnpm gen:api`), never hand-mirrored.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import { creditsKey } from "./credits";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** One trial as any write answers it — dates, a count and an operator's words. */
export type Trial = Schemas["TrialOut"];

/**
 * The read: the same facts plus what the trial has cost CALEVATE so far.
 *
 * `active` is the SERVER's verdict and is not `status === "active"`: the sweep that
 * expires a row runs daily, so a row can read `active` for up to a day past its end date.
 * The console displays the field and never re-derives it, for the reason every other
 * server verdict on these screens is displayed rather than recomputed.
 */
export type TrialStatus = Schemas["TrialStatusOut"];

export type TrialStartIn = Schemas["TrialStartIn"];
export type TrialEndIn = Schemas["TrialEndIn"];

/** The two endings a HUMAN may name. `expired` is the clock's own verdict and is refused
 * by the route, so it is absent here too — a stopped trial recorded as one that ran its
 * course is a different fact about the same client. */
export const TRIAL_OUTCOMES = ["converted", "stopped"] as const;
export type TrialOutcome = (typeof TRIAL_OUTCOMES)[number];

/** The bounds the route and the table both enforce (`MIN_TRIAL_DAYS` / `MAX_TRIAL_DAYS`),
 * mirrored here only to shape the input. The refusal is `invalid_trial_days` and arrives
 * as problem+json with its own message. */
export const MIN_TRIAL_DAYS = 1;
export const MAX_TRIAL_DAYS = 365;

/** The platform default grace before a NON-converting client's data is erased
 * (`trials.DEFAULT_ERASURE_GRACE_DAYS`), and its bounds. Stamped onto the trial row at
 * START and frozen there, so what an operator picks here is a term of THIS arrangement
 * with THIS client and cannot move under them later. */
export const DEFAULT_ERASURE_GRACE_DAYS = 30;
export const MIN_ERASURE_GRACE_DAYS = 1;
export const MAX_ERASURE_GRACE_DAYS = 180;

export function trialPath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/trial`;
}

export function trialKey(tenantId: string): readonly unknown[] {
  return ["admin", "trial", tenantId];
}

/**
 * The step-up string, copied from the route VERBATIM
 * (`trial_routes.start_trial_confirmation`).
 *
 * It carries the TENANT and the DAYS. The tenant, because a confirmation captured while
 * opening a trial for one client must not be replayable against another. The days,
 * because there is no spend ceiling on a trial by the founder's explicit choice, so the
 * number of days is the whole bound on what this costs — changing the figure means
 * confirming the new one.
 */
export function startTrialConfirmation(tenantId: string, days: number): string {
  return `start_trial:${tenantId}:${days}`;
}

/**
 * This client's newest trial, open or closed, or `null` if they have never had one.
 *
 * Newest rather than "the open one" is the route's own choice, and the screen depends on
 * it: "their trial ended on the 3rd" is a sentence an operator needs, and a reader that
 * could only see open trials would show them nothing at all.
 */
export function useTenantTrial(session: Session, tenantId: string) {
  return useQuery({
    queryKey: trialKey(tenantId),
    queryFn: () => apiRequest<TrialStatus | null>(session, trialPath(tenantId)),
  });
}

/** What the operator submits to open a trial. */
export interface TrialStartDraft {
  /** The number of days the client was promised. */
  days: number;
  /** Required. Reaches the audit record verbatim — a client carried for free with no
   * stated reason is the ticket nobody can close. */
  reason: string;
  /** How long after a non-converting trial ends before this client's data is erased.
   * Omitted means the platform default; the route applies the same number. */
  erasureGraceDays?: number;
}

/**
 * Put a client on a trial.
 *
 * `admin:tenants` — the same permission and the same argument as recording a payment
 * (`credit_routes.py` records why no `billing:write` was invented for this shape). The
 * ADMIN session with the tenant in the path, never an impersonating one: it is in
 * `MUTATING_PERMISSIONS`, and D-22 would correctly refuse a "view as client" session that
 * tried to give the client it is viewing a fortnight of free calling.
 *
 * The step-up header goes on EVERY call, carrying the days — see
 * `startTrialConfirmation`.
 *
 * TWO reads are invalidated, and the second is the one that is easy to forget: opening a
 * trial changes nothing on the wallet, but it changes what the WALLET SCREEN means, since
 * the credit gate stops refusing this client while it runs (`credits_exhausted` asks
 * `trial_billing_active` before it asks the balance). A screen still showing "their line
 * is down" beside a live trial is the same class of stale as a balance.
 */
export function useStartTrial(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ days, reason, erasureGraceDays }: TrialStartDraft) => {
      const body: TrialStartIn = {
        days,
        reason: reason.trim(),
        erasure_grace_days: erasureGraceDays ?? DEFAULT_ERASURE_GRACE_DAYS,
      };
      return apiRequest<Trial>(session, trialPath(tenantId), {
        method: "POST",
        body,
        confirmAction: startTrialConfirmation(tenantId, days),
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: trialKey(tenantId) });
      void client.invalidateQueries({ queryKey: creditsKey(tenantId) });
    },
  });
}

/** What the operator submits to end one. */
export interface TrialEndDraft {
  outcome: TrialOutcome;
  reason: string;
}

/**
 * End the open trial — `converted` (they bought; they keep their data for good) or
 * `stopped` (we ended it; a tenant erasure is scheduled for the end of the grace period
 * agreed when the trial was opened).
 *
 * NO step-up header, because the route asks for none, and a header the API ignores is a
 * confirmation of nothing. The screen still states the consequence before the click: what
 * differs between the two outcomes is whether this client's leads, calls and transcripts
 * survive, which is not a thing to discover afterwards.
 */
export function useEndTrial(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ outcome, reason }: TrialEndDraft) => {
      const body: TrialEndIn = { outcome, reason: reason.trim() };
      return apiRequest<Trial>(session, `${trialPath(tenantId)}/end`, {
        method: "POST",
        body,
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: trialKey(tenantId) });
      void client.invalidateQueries({ queryKey: creditsKey(tenantId) });
    },
  });
}
