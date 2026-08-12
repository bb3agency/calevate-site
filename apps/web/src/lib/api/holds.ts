"use client";

/**
 * The ops work list: which accounts are waiting on a human, and on what.
 *
 * `GET /v1/admin/compliance/holds` (`org:read`, admin realm) shipped in with no screen —
 * two R-11 gates were blocking tenants and the only way to see who was blocked was a
 * curl. `apps/api/admin/holds.py` argues the read: nothing in RLS was widened, the row
 * is composed from the SAME blockers that refuse the client's dial and launch, and it
 * carries accounts rather than people.
 *
 * What this module holds is the console's half of that: the operator vocabulary for
 * each rule, WHICH SCREEN CLEARS IT, and how long an account has been waiting.
 *
 * Three properties of the API kept rather than smoothed over:
 *
 * - **`holds` is a list, not a status.** An account can be held by both gates at once
 *   and the API says so instead of picking a winner, so every row here renders every
 *   rule and offers every remedy. Collapsing them would send an operator to clear KYC
 *   and leave the account still held.
 * - **The rules are the GATES' names, and they arrive as plain strings.** They are the
 *   same words the client's own screen and the launch preview use, so an operator and a
 *   client on the phone name one condition identically. A rule this build has never
 *   heard of is rendered as itself and routed to the account, never dropped: an
 *   unrecognised hold is still a held account.
 * - **Hard rule 6 is a property of the payload, and this module adds nothing to it.**
 *   No phone number, no document reference, no signatory, no reviewer prose — the
 *   reasons the blockers return are dropped server-side on purpose, because
 *   `first_campaign_rejected_reason` interpolates an operator's free text. Nothing here
 *   fetches any of it back; everything identifying stays one click away on the
 *   account's own screen, behind the permission that opens it.
 */

import type { NoticeTone } from "@/components/ui";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** One line of the work list. `holds` is the gates' own rule names. */
export type HeldTenant = Schemas["HeldTenantOut"];

/** One path string for the one endpoint. */
export const HOLDS_PATH = "/v1/admin/compliance/holds";

export interface HoldRule {
  /** What an operator calls this hold. */
  label: string;
  /** What is actually blocked while it stands — the triage question. */
  blocks: string;
  /** The action that clears it, in the operator's words. */
  remedy: string;
  /** The screen that records that action, relative to a tenant id. */
  screen: (tenantId: string) => string;
  /** Wording on the link to that screen. */
  cta: string;
  tone: NoticeTone;
}

/**
 * The four rule names the two gates emit (`compliance/service.py`), each with the
 * screen that clears it.
 *
 * A `Record<string, …>` rather than a `Record<Rule, …>`, because `holds` is `string[]`
 * on the wire — the API deliberately did not narrow it to a Literal, since the set grows
 * whenever a gate does. `holdRule()` below is the only reader, and it fails visible
 * rather than closed: an unknown rule keeps the account on the list and says the console
 * does not know what clears it, which is the honest answer and the one that gets fixed.
 *
 * `kyc_missing` and `kyc_not_verified` are two rules and one screen — they are separate
 * facts (nothing filed at all, versus filed and not cleared) with the same remedy, and
 * `kyc_not_verified_reason` exists in the API for exactly that distinction. The list
 * keeps both names because "we have never heard from them" and "we owe them a review"
 * are different work.
 */
export const HOLD_RULES: Record<string, HoldRule> = {
  kyc_missing: {
    label: "Identity not filed",
    blocks: "All outbound calling, and a number purchase on any tier.",
    remedy: "Chase the business's registration details, then record the verification.",
    screen: (tenantId) => `/admin/tenants/${tenantId}/kyc`,
    cta: "Identity (KYC)",
    tone: "stop",
  },
  kyc_not_verified: {
    label: "Identity not verified",
    blocks: "All outbound calling, and a number purchase on any tier.",
    remedy: "Something is on file and is not cleared — check it and record the outcome.",
    screen: (tenantId) => `/admin/tenants/${tenantId}/kyc`,
    cta: "Identity (KYC)",
    tone: "warn",
  },
  first_campaign_review_pending: {
    label: "First campaign not reviewed",
    blocks: "Every campaign on the account. Inbound answering is unaffected.",
    remedy: "Read the list, the script and the disclosure line, then release the account.",
    screen: (tenantId) => `/admin/tenants/${tenantId}/first-campaign-review`,
    cta: "Review & release",
    tone: "warn",
  },
  first_campaign_review_rejected: {
    label: "First campaign refused",
    blocks: "Every campaign on the account. Inbound answering is unaffected.",
    remedy:
      "A reviewer refused this account. It stays held until the client fixes what was " +
      "named and someone looks again.",
    screen: (tenantId) => `/admin/tenants/${tenantId}/first-campaign-review`,
    cta: "Review & release",
    tone: "stop",
  },
};

/**
 * The copy for a rule, or `null` when this build cannot name it.
 *
 * `Object.hasOwn`, never `rule in HOLD_RULES`: `rule` is an arbitrary string off the
 * wire and `in` walks the prototype chain, so `holdRule("constructor")` handed back
 * `Object` itself typed as a `HoldRule` — and the queue's very next line is
 * `copy.screen(tenantId)`, which is a TypeError that takes the whole ops screen down.
 * The contract here is fail-VISIBLE (an unknown rule keeps the row and says so); a
 * blank screen is the one way to fail that an operator cannot see past.
 * Covered by tests/holds.test.ts.
 */
export function holdRule(rule: string): HoldRule | null {
  return Object.hasOwn(HOLD_RULES, rule) ? HOLD_RULES[rule] : null;
}

/**
 * How long this account has been waiting, in whole hours.
 *
 * `signed_up_at` is on the row precisely so the wait is visible: both gates are "since
 * you signed up, nobody has looked", and the API deliberately did not send a per-gate
 * timestamp, because a KYC record filed later does not restart the account's wait.
 *
 * Clamped at zero. A signup in the future is clock skew between the operator's laptop
 * and the database, not a negative wait, and "in 2 hours" in a waiting column is the
 * kind of nonsense that makes a whole screen untrustworthy.
 */
export function hoursWaiting(signedUpAt: string, now: number = Date.now()): number {
  const started = new Date(signedUpAt).getTime();
  if (Number.isNaN(started)) return 0;
  return Math.max(0, Math.floor((now - started) / 3_600_000));
}

/**
 * "3 days" / "5 hours" — the wait as a phrase, so nobody subtracts dates by hand.
 *
 * `Intl.RelativeTimeFormat` with `numeric: "always"`, which is what turns -3 days into
 * "3 days ago" rather than the conversational "yesterday" that `"auto"` produces
 * (developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/RelativeTimeFormat/format).
 * A queue is scanned, not read: "yesterday" and "2 days ago" next to each other cannot
 * be compared at a glance, and comparing them IS the triage. The "ago" is trimmed here
 * because the column already says what the number measures.
 */
const RELATIVE = new Intl.RelativeTimeFormat("en-IN", { numeric: "always" });

export function waitedFor(signedUpAt: string, now: number = Date.now()): string {
  const hours = hoursWaiting(signedUpAt, now);
  // Below the first whole hour the formatter would render `-0` as "in 0 hours", which is
  // both wrong-tensed and the only cell on the screen pointing at the future. A signup
  // this minute has waited no measurable time, and saying so is the honest reading.
  if (hours === 0) return "under an hour";
  const [value, unit]: [number, Intl.RelativeTimeFormatUnit] =
    hours < 24 ? [hours, "hour"] : [Math.floor(hours / 24), "day"];
  return RELATIVE.format(-value, unit).replace(/\s*ago$/, "");
}

/**
 * How alarming this wait is. THREE BANDS, and they are OURS, not a published SLA.
 *
 * No document in `docs/` sets a turnaround for either gate, so this does not pretend to
 * measure one. What it measures is the shape of the work: both gates are a person
 * reading a page, so an account still waiting on the second day is not busy, it is
 * stuck, and one waiting past a week is the account `holds.py` describes as having
 * "quietly stopped trying" — a self-serve signup that cannot dial and hears nothing does
 * not complain, it churns. The bands exist to make that visible at a glance; the
 * numbers are a triage heuristic and should move the day an SLA is actually agreed.
 */
export const WAIT_WARN_HOURS = 48;
export const WAIT_BREACH_HOURS = 24 * 7;

export function waitBand(signedUpAt: string, now: number = Date.now()): NoticeTone {
  const hours = hoursWaiting(signedUpAt, now);
  if (hours >= WAIT_BREACH_HOURS) return "stop";
  if (hours >= WAIT_WARN_HOURS) return "warn";
  return "neutral";
}

/**
 * The queue's cache key, named here and imported by both the read and every write that
 * can empty a row off it.
 *
 * Clearing either gate removes an account from the list, so the KYC write and the
 * first-campaign decision both have to invalidate this — and a key spelled out at three
 * call sites is a key that eventually differs at one of them, leaving an operator
 * looking at a row they just cleared.
 */
export const HOLDS_QUERY_KEY = ["admin", "holds"] as const;
