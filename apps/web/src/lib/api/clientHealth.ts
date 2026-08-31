"use client";

/**
 * The client health overview: which account is about to churn or break, this week.
 *
 * `GET /v1/admin/client-health` (`org:read`, admin realm). `apps/api/admin/health.py`
 * argues the whole design — the five signals, the candidates rejected, why the call trend
 * carries a `basis` instead of a bare ratio, and why the cross-tenant read widens no RLS
 * policy. What lives here is the console's half: the operator vocabulary for each signal,
 * WHICH SCREEN FIXES IT, and the two rules about what may be rendered.
 *
 * Three properties of the API kept rather than smoothed over:
 *
 * - **The board is an EXCEPTION report.** An account with nothing wrong is absent, not
 *   green — the roster is `/admin` (`GET /v1/admin/tenants`). So an empty board is the
 *   GOOD state and must say so in words; rendering "no data" at its own success reads as
 *   a broken load.
 * - **`calls_basis` decides whether a trend may be shown at all.** This is the
 *   `after_hours_basis` precedent applied to an ACCUSATION rather than a tile. `too_new`
 *   and `no_baseline` are not "0% change" — they are "we are not entitled to say", and a
 *   console that rendered all three the same would send an operator to ask a four-day-old
 *   account why its calls stopped. `trendClaim` is the only reader, and there is no code
 *   path that formats a delta from an unearned basis.
 * - **Severity and order are the SERVER's answers.** `severity` is the worst signal on
 *   the row and the array arrives in triage order (`admin/health.py::_triage_order`).
 *   Re-sorting or re-scoring here would be a second opinion about priority held in the
 *   place least able to defend it — the same reason the hold queue keeps the server's
 *   order.
 *
 * Hard rule 6 is a property of the payload and nothing here widens it: the API sends
 * accounts and machine rule names, never a phone number and never the blockers' `reason`
 * prose (which interpolates an operator's free text). This module supplies all wording
 * from its own tables and fetches none of it back.
 */

import type { NoticeTone } from "@/components/ui";
import { lookup } from "@/lib/lookup";

import { holdRule } from "./holds";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One line of the board. */
export type ClientHealth = Schemas["ClientHealthOut"];
/** One thing wrong with one account, in machine names. */
export type HealthSignal = Schemas["HealthSignalOut"];
export type Severity = ClientHealth["severity"];
// No `CallBasis` alias: `trendClaim` below is the ONLY reader of `calls_basis`, and
// exporting the union would invite a second one — which is precisely the code path that
// must not exist (a screen that switches on the basis itself can render a trend from an
// unearned one).

/** One path string for the one endpoint. */
export const CLIENT_HEALTH_PATH = "/v1/admin/client-health";

/** The board's cache key, named here so the read and any future invalidator agree. */
export const CLIENT_HEALTH_QUERY_KEY = ["admin", "client-health"] as const;

export interface SignalCopy {
  /** What an operator calls this signal. */
  label: string;
  /** What it means for the client — the triage sentence. */
  meaning: string;
  /** Where the fix lives, relative to a tenant id and slug. */
  screen: (tenantId: string, slug: string) => string;
  /** Wording on the link to that screen. */
  cta: string;
}

/**
 * The six signals the board emits, each with the screen that acts on it.
 *
 * A `Record<string, …>` rather than a `Record<Rule, …>`, for the reason `HOLD_RULES` is:
 * `rule` is a plain string on the wire because the set grows whenever a signal does, and
 * a generated client that had to be regenerated before it could DISPLAY a new signal
 * would drop the row instead. `signalCopy()` is the only reader and it fails VISIBLE — an
 * unknown signal keeps its account on the board and prints the rule as itself, because an
 * account in trouble for a reason this build cannot name is still an account in trouble.
 */
export const SIGNAL_COPY: Record<string, SignalCopy> = {
  calls_stopped: {
    label: "Calls stopped",
    meaning:
      "This account was taking calls last week and has all but stopped. Either the number " +
      "is no longer routing to us, or they have stopped using it — both are a phone call today.",
    screen: (tenantId) => `/admin/tenants/${tenantId}`,
    cta: "Open the account",
  },
  outbound_blocked: {
    label: "Cannot dial out",
    meaning:
      "The platform is refusing this account's outbound calls right now. Inbound answering " +
      "is unaffected. The rules below are the same ones the client sees on their own launch screen.",
    screen: (tenantId) => `/admin/tenants/${tenantId}`,
    cta: "Open the account",
  },
  spend_cap_near: {
    label: "Spend cap about to bite",
    meaning:
      "Most of the ceiling in force is gone. Raising it now costs a conversation; " +
      "raising it after it binds costs an outage the client noticed first.",
    screen: (tenantId) => `/admin/tenants/${tenantId}`,
    cta: "Open the account",
  },
  deliveries_failing: {
    label: "Leads not arriving",
    meaning:
      "Outbound deliveries to this client's own CRM or spreadsheet are failing. To them " +
      "this looks like the product having quietly stopped working.",
    screen: (_tenantId, slug) => `/c/${slug}/integrations`,
    cta: "Their integrations",
  },
  knowledge_waiting: {
    label: "Knowledge waiting on us",
    meaning:
      "This client submitted knowledge and nobody here has approved it. Their agent is " +
      "answering without it, and this one is entirely ours to clear.",
    screen: (tenantId) => `/admin/tenants/${tenantId}`,
    cta: "Approve knowledge",
  },
  calls_unmetered: {
    label: "Calls billed to us and to nobody",
    meaning:
      "Completed calls on this account produced no usage row, so they are missing from " +
      "the client's usage panel, their invoice, their spend cap and their wallet — while " +
      "the engine has already charged us for them. The reconciliation poller treats them " +
      "as settled and will not come back, so this does not clear itself.",
    screen: (tenantId) => `/admin/tenants/${tenantId}`,
    cta: "Open the account",
  },
};

/** The copy for a signal, or `null` when this build cannot name it. */
export function signalCopy(rule: string): SignalCopy | null {
  return lookup(SIGNAL_COPY, rule) ?? null;
}

/**
 * The gate rule names `outbound_blocked` carries that are NOT the hold queue's.
 *
 * These are the SAME strings `campaigns.service.launch_blockers` refuses a launch with,
 * so an operator reading this board and a client reading their own campaign screen are
 * naming one condition identically.
 *
 * The R-11 gates (`kyc_missing`, `kyc_not_verified`, `first_campaign_review_*`) are
 * deliberately ABSENT: `holds.ts::HOLD_RULES` already carries their operator wording AND
 * the screen that clears each one, and a second table here would be a second set of words
 * for one condition — exactly the drift `admin/holds.py` composes its predicates to avoid,
 * one layer up. `causeLabel` and `causeHref` below ask that table first.
 */
const CAUSE_LABELS: Record<string, string> = {
  spend_cap: "Monthly spend cap reached",
  no_credits: "Prepaid wallet empty",
  pe_registration_missing: "No DLT Principal Entity registration",
  pe_registration_not_active: "DLT Principal Entity registration not active",
  tm_link_not_active: "PE has not authorised Calevate as telemarketer",
};

/**
 * A cause in words: the hold queue's own wording where it has some, ours where it does
 * not, and the bare wire name where neither does.
 *
 * Fails VISIBLE, like every other wire lookup in the admin realm: a cause this build has
 * never heard of is still a cause the client is being refused on, and hiding it would
 * leave an operator staring at a blocked account with an empty explanation.
 */
export function causeLabel(cause: string): string {
  return holdRule(cause)?.label ?? lookup(CAUSE_LABELS, cause) ?? cause;
}

/**
 * Where an operator goes to clear this cause.
 *
 * A hold goes to the screen `HOLD_RULES` names — the queue owns those two gates and their
 * remedies, and this board is not a second place to work them. Everything else goes to the
 * account, which is where the DLT registration, the caps and the credit ledger are.
 */
export function causeHref(cause: string, tenantId: string): string {
  return holdRule(cause)?.screen(tenantId) ?? `/admin/tenants/${tenantId}`;
}

/**
 * The wording on the link `causeHref` produces — the hold queue's own call to action
 * where it has one, and the account otherwise.
 *
 * Paired with `causeHref` rather than derived separately, because a label and a
 * destination that disagree is the shape that sends an operator to the wrong desk.
 */
export function causeCta(cause: string): string {
  return holdRule(cause)?.cta ?? "Open the account";
}

export type TrendClaim =
  | { kind: "measured"; droppedPct: number; from: number; to: number }
  | { kind: "unknown"; why: string };

/**
 * WHAT the console is entitled to say about this account's call volume.
 *
 * The one reader of `calls_basis`, and the reason it returns a discriminated union rather
 * than a formatted string: there is then no way to render a percentage without having
 * handled the two cases where no percentage exists. A `?? "—"` at the call site would
 * type-check and would put the guess back.
 *
 * `too_new` and `no_baseline` are separate sentences because they have separate next
 * actions: one account has not had time to trade, the other has traded and barely. An
 * operator told "not enough history" about a client doing four calls a week would wait
 * for a baseline that has already arrived.
 */
export function trendClaim(row: ClientHealth): TrendClaim {
  if (row.calls_basis === "too_new") {
    return { kind: "unknown", why: "Too new to compare — no previous week yet." };
  }
  if (row.calls_basis === "no_baseline") {
    return { kind: "unknown", why: "Too few calls last week for a comparison to mean anything." };
  }
  // `measured` guarantees a non-zero previous week server-side (TREND_BASELINE_MIN), so
  // this division is safe — but it is guarded anyway, because a divide-by-zero here
  // renders `NaN%` on an operations screen and that is a worse failure than a missing
  // cell.
  const from = row.calls_prev_7d;
  const to = row.calls_7d;
  if (from <= 0) return { kind: "unknown", why: "No previous week to compare against." };
  return { kind: "measured", droppedPct: Math.round(((from - to) * 100) / from), from, to };
}

/** The tone a severity renders in. `stop` is broken now; `warn` will break. */
export function severityTone(severity: Severity): NoticeTone {
  return severity === "stop" ? "stop" : "warn";
}

/**
 * A signal's count as a phrase, or null when the signal is a state rather than a count.
 *
 * `count` means a different thing per signal — deliveries, sources, a percentage, the
 * size of the baseline week — so the wording lives beside the rule rather than in one
 * generic "N". `null` and `0` are different claims on the wire and both render as
 * nothing here rather than as "0", which would read as a measured zero.
 */
export function signalCount(signal: HealthSignal): string | null {
  if (signal.count === null || signal.count === undefined) return null;
  switch (signal.rule) {
    case "deliveries_failing":
      return `${signal.count} failed ${signal.count === 1 ? "delivery" : "deliveries"}`;
    case "knowledge_waiting":
      return `${signal.count} ${signal.count === 1 ? "source" : "sources"} waiting`;
    case "spend_cap_near":
      return `${signal.count}% of the ceiling used`;
    case "calls_stopped":
      return signal.severity === "stop"
        ? `${signal.count} calls last week, none this week`
        : `${signal.count} calls this week`;
    default:
      // A signal this build cannot name still has a number behind it, and printing it
      // bare beats hiding it: an operator who can read the rule name can read the count.
      return String(signal.count);
  }
}
