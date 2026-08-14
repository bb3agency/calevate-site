"use client";

/**
 * Commercial terms and account lifecycle — the two admin surfaces over `organizations`
 * and `plans` (SURFACES §1: "Controlled mutations with audit: plan changes … cap raises,
 * suspend/reactivate, offboarding trigger").
 *
 * Both endpoints shipped with this module and neither has a client-realm twin, which is
 * not an oversight in either case: a business that could set its own overage rate would
 * be setting what we invoice them, and one that could clear its own suspension would be
 * reversing the control we suspended them with. What the client gets is the READ of the
 * caps that bind them (`caps.ts`) and their own usage panel.
 *
 * THREE THINGS THE API DECIDED THAT THIS MODULE KEEPS RATHER THAN SMOOTHS OVER
 *
 * - **Money is a STRING, both ways.** Every amount is exact NUMERIC INR (hard rule 7).
 *   Fees are formatted for display with `formatINR`, which reads the digits and never
 *   parses them; RATES are printed verbatim, because `formatINR` would round ₹7.1250 to
 *   ₹7.12 and break the invoice's own `qty x unit = amount` in our favour (BUILD-LOG
 *   §52 records that distinction and where it came from).
 * - **`null` means UNSET, never zero.** An overage rate of 0 is free minutes; an absent
 *   one is a plan that quotes no overage. No field here is defaulted to a number, and
 *   the value-tier rate in particular is left settable and empty — it is an open founder
 *   decision (TRD §10.1's bands are unmeasured), and a default would be invention.
 * - **`state` is the SERVER's word for what an operator is looking at.** "Does this
 *   client have terms" is answered once, in `billing/terms.py`, and never re-derived
 *   here — the same rule `kyc.ts` states about `is_verified`.
 *
 * Types come from `schema.d.ts` (`pnpm gen:api`), not from hand-mirroring
 * `apps/api/admin/routes.py`. They were hand-written while this slice was in flight,
 * because the generator runs once at the end of a change; the regen has since happened
 * and they were swapped, which is the half that makes the convention worth having.
 *
 * The ONE exception is `TermsState`. FastAPI serializes the server's `Literal` as a bare
 * `string`, so the generated `CommercialTermsOut["state"]` cannot narrow — the union below
 * is OUR reading of that string, kept because the copy tables are keyed by it. It is not
 * a second source for the value: `state` is still decided once, in `billing/terms.py`, and
 * every read goes through `lookup()`, which is prototype-safe and returns undefined for a
 * state the server invents rather than crashing the screen.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** One dated agreement. Every amount is exact digits or absent — never a zero for unset. */
export type PlanRow = Schemas["PlanRowOut"];

/** See the header: the server's `Literal` serializes as a bare `string`, so this union is
 *  our reading of it rather than a shape the generator can hand us. */
export type TermsState = "none" | "unpriced" | "lapsed" | "set";

export type CommercialTerms = Schemas["CommercialTermsOut"];

/** What an operator submits. Amounts as strings; `null` leaves a field unset. */
export type CommercialTermsIn = Schemas["CommercialTermsIn"];

export type RecordTermsOut = Schemas["RecordTermsOut"];

export type LifecycleStatus = "active" | "suspended" | "churned";

export type LifecycleOut = Schemas["LifecycleOut"];

export function commercialTermsPath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/commercial-terms`;
}

export function tenantStatusPath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/status`;
}

export interface TermsStateCopy {
  label: string;
  /** What this state MEANS for the client's money, in one sentence an operator can act on. */
  detail: string;
  tone: "ok" | "warn" | "stop" | "neutral";
}

/**
 * A `Record` over the union rather than a loose object, so that a state added to the API
 * stops this file compiling instead of rendering a blank badge (the device `kyc.ts` uses).
 *
 * `none` and `lapsed` are both `stop` even though neither is an error: an account with
 * no terms in effect is billed nothing and capped by nothing, which is a state somebody
 * has to resolve rather than a state to be reported calmly.
 */
export const TERMS_STATE_COPY: Record<TermsState, TermsStateCopy> = {
  none: {
    label: "No commercial terms set",
    detail:
      "Nothing has ever been agreed for this account. They are invoiced nothing, have no included minutes, and no spend ceiling stops their dialling. Onboarding does not invent a price — set the terms here.",
    tone: "stop",
  },
  unpriced: {
    label: "No price agreed",
    detail:
      "The only plan row in effect carries the client's own spend cap and no commercial terms. They are still invoiced nothing.",
    tone: "stop",
  },
  lapsed: {
    label: "Terms have lapsed",
    detail:
      "This account has plan rows and none is in effect — an end date was set with no successor, so the rate and the ceiling both stopped binding on that instant. Record the successor, or reopen the current terms.",
    tone: "stop",
  },
  set: {
    label: "Terms in effect",
    detail: "The agreement below is what prices this account today.",
    tone: "ok",
  },
};

/** Fails to a REFUSAL, not to "fine": an unnameable state must not read as priced. */
export function termsStateCopy(state: string): TermsStateCopy {
  return (
    lookup(TERMS_STATE_COPY, state) ?? {
      label: `Unrecognised state (${state})`,
      detail:
        "This console does not know what this state means, so it will not tell you the account is priced. Reload; if it persists, the API is ahead of the console.",
      tone: "stop",
    }
  );
}

/**
 * Which ADMIN ceilings this draft would RAISE or REMOVE, by field name.
 *
 * A copy of `billing/terms.py::loosened_ceilings`, and copied deliberately: the server
 * is the enforcement (it refuses without a superadmin and the step-up header), and this
 * is the PREVIEW — it decides whether to send the confirmation and whether to warn
 * before the click. Removing a ceiling counts, because `null` is the loosest value there
 * is; setting a first ceiling on an account that has none does not, because unlimited is
 * what they have right now.
 */
export function loosenedCeilings(
  inEffect: PlanRow | null,
  draft: Pick<CommercialTermsIn, "hard_cap_minutes" | "hard_cap_spend_inr">,
): string[] {
  if (!inEffect) return [];
  const raised: string[] = [];
  // ABSENT AND NULL ARE THE SAME LOOSENING, and the generated types are what forced this
  // to be said out loud. `CommercialTermsIn`'s ceilings are OPTIONAL on the wire (Pydantic
  // defaults), which the hand-written mirror this file used to carry declared as
  // required-and-nullable — so an omitted ceiling type-checked as impossible. It is not:
  // omitting the field unsets the ceiling exactly as `null` does, and reading `undefined`
  // as "not a loosening" would let a cap raise reach the server without the step-up
  // confirmation this function exists to demand. Normalised once, here, rather than at
  // each comparison.
  const newMinutes = draft.hard_cap_minutes ?? null;
  if (
    inEffect.hard_cap_minutes !== null &&
    (newMinutes === null || newMinutes > inEffect.hard_cap_minutes)
  ) {
    raised.push("minute ceiling");
  }
  const oldSpend = inEffect.hard_cap_spend_inr;
  const newSpend = draft.hard_cap_spend_inr ?? null;
  if (
    oldSpend !== null &&
    (newSpend === null || Number(newSpend) > Number(oldSpend))
    // `Number` is safe HERE and nowhere else on this screen: this is a comparison that
    // decides which header to send, not a value that is stored or displayed. The server
    // repeats the comparison in Decimal and refuses if this preview was wrong.
  ) {
    raised.push("spend ceiling");
  }
  return raised;
}

export interface LifecycleCopy {
  /** The verb on the button. */
  action: string;
  /** What pressing it does to the client, said before it is pressed. */
  consequence: string;
  tone: "ok" | "warn" | "stop";
  /** Does the API require a reason? Mirrors `_NEEDS_REASON` in `admin/routes.py`. */
  needsReason: boolean;
}

export const LIFECYCLE_COPY: Record<LifecycleStatus, LifecycleCopy> = {
  active: {
    action: "Reactivate",
    consequence:
      "Outbound dialling resumes at the next dial: campaigns, the call-this-lead button and lead callbacks all start placing calls again.",
    tone: "ok",
    needsReason: false,
  },
  suspended: {
    action: "Suspend",
    consequence:
      "Outbound dialling stops at the next dial — campaigns included. Inbound answering is deliberately unaffected: their own customers still get through. Reversible from this screen.",
    tone: "warn",
    needsReason: true,
  },
  churned: {
    action: "Close the account",
    consequence:
      "Outbound stops, and the account's users lose access entirely. This cannot be undone here — reopening a closed account is a new agreement. Their commercial terms are deliberately left alone so the final invoice still prices the month they left in.",
    tone: "stop",
    needsReason: true,
  },
};

export function useCommercialTerms(
  session: Session,
  tenantId: string,
): UseQueryResult<CommercialTerms> {
  return useQuery({
    queryKey: ["admin", "commercial-terms", tenantId],
    queryFn: () => apiRequest<CommercialTerms>(session, commercialTermsPath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

export function useRecordTerms(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ terms, confirm }: { terms: CommercialTermsIn; confirm: string | null }) =>
      apiRequest<RecordTermsOut>(session, commercialTermsPath(tenantId), {
        method: "POST",
        body: terms,
        // Sent ONLY when this write loosens a ceiling. A confirmation header attached to
        // every request would be a confirmation of nothing — §7 wants it bound to the
        // dangerous action, and the server refuses one that names another tenant.
        ...(confirm ? { confirmAction: confirm } : {}),
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["admin", "commercial-terms", tenantId] }),
  });
}

export function useSetTenantStatus(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ status, reason }: { status: LifecycleStatus; reason: string | null }) =>
      apiRequest<LifecycleOut>(session, tenantStatusPath(tenantId), {
        method: "POST",
        body: reason ? { status, reason } : { status },
      }),
    onSuccess: () => {
      // The directory record carries `status`, and the detail screen prints it under the
      // client's name — a stale one there is the console telling an operator the
      // suspension did not take.
      void client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] });
      void client.invalidateQueries({ queryKey: ["admin", "tenants"] });
    },
  });
}
