"use client";

/**
 * A client's prepaid wallet, from the admin side: what is on the ledger, and the one
 * way money gets onto it.
 *
 * `GET|POST /v1/admin/tenants/{tenant_id}/credits` (`apps/api/billing/credit_routes.py`)
 * has existed since M1 with no caller in this console at all, so
 * `runbooks/topup-payments.md` §3 told an operator to hand-assemble the POST against
 * production from a bank statement. This module is that request, typed.
 *
 * ## THREE PROPERTIES OF THE ROUTE THAT THIS MODULE MUST NOT SMOOTH OVER
 *
 * - **The payment reference IS the idempotency key.** Not an `Idempotency-Key` header —
 *   the route's docstring rejects that machinery explicitly, because a header expires in
 *   24h and a bank reference is permanent. Posting the same reference again returns the
 *   EXISTING entry with `recorded: false` and credits nothing; posting it with a
 *   different amount is a 409 (`topup_reference_conflict`), not a second payment. So
 *   `recorded` is the field every caller must read: a replay and a fresh credit are both
 *   200, and the flag is the only thing that tells them apart.
 * - **Money is a STRING both ways** (hard rule 7). `TopUpIn.amount_inr` is typed
 *   `number | string` by the generator because Pydantic accepts both, and sending the
 *   number is REFUSED at the boundary on purpose — `_never_a_float` raises rather than
 *   quietly rounding, because `2500.10` through a binary float and back is how a
 *   paise-level dispute starts. `TopUpDraft.amountInr` is therefore a `string` all the
 *   way to `fetch`, and nothing in this file or its screen calls `Number()` on it.
 * - **Three writes, three different confirmation rules, each copied from its own route.**
 *   `useRecordTopUp` sends no `X-Confirm-Action`, because the route accepts none — a
 *   header the API ignores is a confirmation of nothing. `useRecordAdjustment` sends one
 *   when the correction takes credit AWAY and none when it puts credit back, mirroring
 *   the route's rule (bound to the dangerous direction, not to the endpoint).
 *   `useRecordRestatement` sends one ALWAYS, and it echoes the amount: that route has
 *   one direction, no ceiling above it, and it credits the client. Guessing any of the
 *   three would produce a request the API refuses or a ceremony that protects nobody.
 *   Both consoles' human confirmations are argued on the screen. Admin-realm MFA is
 *   enforced for every admin token in `core/auth.py::verify_token` (D-68), so this
 *   surface is already behind a second factor either way.
 *
 * Types come from `schema.d.ts` (`pnpm gen:api`), never hand-mirrored. The ONE exception
 * is `CreditReason`: FastAPI serializes the ledger's `reason` as a bare `string`, so the
 * union below is OUR reading of it, kept because the copy table is keyed by it and read
 * through `lookup()` — a reason this build has no word for still prints, rather than
 * blanking the row (`lib/lookup.ts`).
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];


/**
 * One line of `credit_ledger`. Every amount is exact digits — never a number.
 *
 * `reversible_inr` is how much of this entry a compensating adjustment can still take
 * back: its own magnitude less whatever adjustments already name it, and `"0.00"` once
 * it is fully corrected. The SERVER computes it, through the same dataclass that
 * enforces the ceiling on the write — the console cannot do decimal arithmetic on money
 * (hard rule 7 reaches the browser too).
 */
export type LedgerEntry = Schemas["LedgerEntryOut"];

/**
 * ONE BANK TRANSFER, whatever it took on the ledger to record it.
 *
 * `credited_inr` is everything that reference has credited — the original entry plus
 * every restatement of it — summed by the SERVER across all of that payment's rows,
 * including any that have scrolled off the page. It is the figure a person holding a
 * bank statement compares against, and the console could not compute it even if it
 * wanted to (hard rule 7 reaches the browser: no decimal arithmetic here).
 *
 * `entries > 1` means the payment has been restated. That is the only place a
 * restatement is visible AS one, which is the point — reconciliation must see one bank
 * transfer, not two references invented to fit around an append-only ledger.
 */
export type Payment = Schemas["PaymentOut"];

/**
 * The wallet: balance, the server's low-balance verdict, the recent entries — and the
 * bank transfers behind them.
 */
export type Credits = Schemas["CreditsOut"];

/**
 * The adjustment request body. `amount_inr` is a POSITIVE magnitude, and it is sent as
 * a STRING — the generator types it `number | string` because Pydantic accepts both,
 * exactly as it does for `TopUpIn`, and the same rule applies: nothing in this module
 * ever puts a `number` in it.
 */
export type AdjustmentIn = Schemas["AdjustmentIn"];

/** The adjustment answer. `recorded: false` means this correction was already made. */
export type AdjustmentResult = Schemas["AdjustmentOut"];

/** The request body. `amount_inr` is sent as a STRING; see the header. */
export type TopUpIn = Schemas["TopUpIn"];

/** The answer. `recorded: false` means the reference was already on the ledger. */
export type TopUpResult = Schemas["TopUpOut"];

export function creditsPath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/credits`;
}

/**
 * How many entries the screen asks for. Sent EXPLICITLY rather than left to the route's
 * default, so the request the console makes is visible in one place and the query key,
 * the path and the fixture cannot drift apart. The route bounds it at 200.
 */
export const LEDGER_LIMIT = 50;

export function creditsKey(tenantId: string): readonly unknown[] {
  return ["admin", "credits", tenantId];
}

/**
 * `credit_ledger.reason` — the four values `ck_credit_ledger_reason_enum` allows
 * (`apps/api/billing/models.py`).
 */
export type CreditReason = "topup" | "usage" | "adjustment" | "refund";

/** What an entry IS, for the operator reading the ledger. */
export const CREDIT_REASON_LABEL: Record<CreditReason, string> = {
  topup: "Payment recorded",
  usage: "Call usage",
  adjustment: "Compensating adjustment",
  refund: "Refund",
};

/**
 * Fails VISIBLE, not silent: a reason this build has no word for is printed as the
 * server sent it, because an unrecognised entry on a money ledger is exactly the one
 * worth reading. Same direction as `StatusBadge` (`components/ui.tsx`).
 */
export function creditReasonLabel(reason: string): string {
  return lookup(CREDIT_REASON_LABEL, reason) ?? reason;
}

/**
 * A rupee amount as the API will read it — checked by SHAPE, never by `Number()`.
 *
 * This mirrors `TopUpIn.amount_inr` (`Decimal`, `max_digits=10`, `decimal_places=2`, so
 * eight integer digits and at most a paisa of precision) and the route's own
 * `amount <= 0` refusal. It exists to put the refusal BEFORE the click rather than
 * after it — the server is still the enforcement, and its problem+json is still
 * rendered when this preview and the API disagree.
 *
 * The zero test is a regex and not `Number(value) <= 0`, and that is the whole point of
 * the function: parsing the operator's digits to decide something about them is the one
 * move hard rule 7 forbids, and "we only parsed it to validate" is how the parse ends up
 * feeding the value that gets sent.
 */
const RUPEES = /^\d{1,8}(?:\.\d{1,2})?$/;
const ONLY_ZEROS = /^0+(?:\.0+)?$|^0*\.0+$/;

/** What is wrong with these digits, if anything — the SHAPE, with no copy attached. */
export type RupeeFault = "missing" | "shape" | "zero";

/**
 * The check itself, separated from what to say about it.
 *
 * Both money fields on the credits screen accept the same shape and refuse it for the
 * same three reasons; only the sentences differ, because "a top-up has to be more than
 * zero" and "a correction has to take something back" are different next actions. One
 * predicate, two messages — the alternative is two regexes drifting apart on the two
 * fields where they must agree.
 */
export function rupeeFault(raw: string): RupeeFault | null {
  const value = raw.trim();
  if (value === "") return "missing";
  if (!RUPEES.test(value)) return "shape";
  if (ONLY_ZEROS.test(value)) return "zero";
  return null;
}

const DIGITS_ONLY =
  "Digits only, with at most two decimal places — no commas, no ₹ sign, no spaces " +
  "(so 2500.10, not ₹2,500.10). Up to eight digits before the decimal point.";

export function rupeeProblem(raw: string): string | null {
  switch (rupeeFault(raw)) {
    case "missing":
      return "Enter the amount exactly as the statement shows it.";
    case "shape":
      return DIGITS_ONLY;
    case "zero":
      return (
        "A top-up has to be more than zero. Taking credit BACK is a compensating " +
        "adjustment against the entry that was wrong — the “Correct a wrong entry” " +
        "panel below, never a negative top-up."
      );
    default:
      return null;
  }
}

/**
 * The same shape check, said for a CORRECTION.
 *
 * Never signed: the amount is how much of the named entry to take back, and the route
 * derives the direction from that entry. An operator who types `-500` here has
 * misunderstood the control, and the message says which way round it works rather than
 * silently accepting a minus the API would refuse.
 */
export function adjustmentAmountProblem(raw: string): string | null {
  switch (rupeeFault(raw)) {
    case "missing":
      return "Enter how much of that entry to take back.";
    case "shape":
      return `${DIGITS_ONLY} Never a minus sign — the direction comes from the entry.`;
    case "zero":
      return "A correction has to move something. Enter the amount that was wrong.";
    default:
      return null;
  }
}

/**
 * The payment reference as the API will key on it.
 *
 * `.trim()` and NOTHING ELSE, deliberately: the route's `_trimmed` validator strips the
 * ends and stops there, so any further normalization here (collapsing the internal
 * spaces, upper-casing) would send a key that is not the string the operator read off
 * the statement, and would make this console's idea of "the same payment" differ from
 * the ledger's. The internal-space hazard is REPORTED instead — see `referenceCaution`.
 */
export function normalizeReference(raw: string): string {
  return raw.trim();
}

export function referenceProblem(raw: string): string | null {
  const ref = normalizeReference(raw);
  if (ref === "") return "The bank's reference for this payment is required.";
  if (ref.length < 3) return "A payment reference is at least three characters.";
  if (ref.length > 120) return "A payment reference is at most 120 characters.";
  return null;
}

/**
 * A reference that is probably about to become two different payments.
 *
 * The server keys on the exact string, so `UTR 900011` and `UTR900011` are two payments
 * and crediting both is a real double credit that no amount of care at the second entry
 * catches — the double-keyed confirmation on the screen does not help here, because an
 * operator who reads a space off the statement types it twice. A caution rather than a
 * refusal: some banks really do print references with spaces in them, and refusing one
 * would send the operator back to the curl this screen exists to replace.
 */
export function referenceCaution(raw: string): string | null {
  const ref = normalizeReference(raw);
  if (ref === "" || !/\s/.test(ref)) return null;
  return (
    "This reference has a space inside it. The ledger keys on the exact string, so " +
    "“ABC 123” and “ABC123” are two different payments — copy it from the statement " +
    "exactly, spaces and all, and the same way every time."
  );
}

/**
 * The wallet and the tail of its ledger.
 *
 * `billing:read` (`read_credits`), which both admin roles hold. The read is what makes
 * the write safe to offer: recording a payment against a ledger nobody can see is how
 * one gets credited twice, so the screen withholds the form when this fails.
 */
export function useCredits(session: Session, tenantId: string): UseQueryResult<Credits> {
  return useQuery({
    queryKey: creditsKey(tenantId),
    queryFn: () =>
      apiRequest<Credits>(session, `${creditsPath(tenantId)}?limit=${LEDGER_LIMIT}`),
    enabled: Boolean(tenantId),
  });
}

/** What the operator submits. Every field is a STRING, because the money one must be. */
export interface TopUpDraft {
  /** Rupees as DIGITS, exactly as they will cross the wire (hard rule 7). */
  amountInr: string;
  /** The bank's UTR/RRN. THE idempotency key — see the module header. */
  paymentRef: string;
  /** Free text stored in the entry's `meta`; `null` when the operator wrote none. */
  note: string | null;
}

/**
 * Record a received payment onto the wallet.
 *
 * `admin:tenants` (`record_topup`) — the route argues why recording a payment is
 * admin-realm support work rather than a `billing:write` that does not exist. The
 * session is the ADMIN one with the tenant in the path, never an impersonating one:
 * `admin:tenants` is in `MUTATING_PERMISSIONS`, so D-22 would correctly refuse it.
 *
 * The reference is trimmed HERE as well as by the server. Not defensive duplication:
 * the screen echoes the reference back in its result, and a console that displayed
 * `"UTR-1 "` while the ledger stored `"UTR-1"` would be showing a key that is not the
 * key — which on the one field that decides double-crediting is worth one `.trim()`.
 */
export function useRecordTopUp(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ amountInr, paymentRef, note }: TopUpDraft) => {
      const body: TopUpIn = {
        // A string, always. `TopUpIn.amount_inr` is `number | string` only because
        // Pydantic's `Decimal` accepts both shapes; the route REFUSES the float one.
        amount_inr: amountInr.trim(),
        payment_ref: normalizeReference(paymentRef),
        note,
      };
      return apiRequest<TopUpResult>(session, creditsPath(tenantId), {
        method: "POST",
        body,
      });
    },
    // The balance and the ledger both moved — and on a replay neither did, which is
    // just as important to re-read: the screen must show the ledger as it IS, not the
    // one it had before a colleague's entry landed.
    onSuccess: () => void client.invalidateQueries({ queryKey: creditsKey(tenantId) }),
  });
}

/* --------------------------------------------------------------------------
 * Compensating adjustments — the only way an entry comes back OFF a wallet.
 * ----------------------------------------------------------------------- */

export function adjustmentsPath(tenantId: string): string {
  return `${creditsPath(tenantId)}/adjustments`;
}

/**
 * The step-up string, copied from the route VERBATIM
 * (`credit_routes.credit_adjustment_confirmation`).
 *
 * Bound to the ENTRY rather than to the tenant, which is the route's own choice and
 * worth repeating where the header is built: a wallet has many entries, so "confirm for
 * this client" would let a confirmation captured while reversing a ₹500 call charge be
 * replayed against a ₹50,000 top-up on the same screen.
 */
export function creditAdjustmentConfirmation(entryId: string): string {
  return `adjust_credits:${entryId}`;
}

/**
 * Does correcting this entry take credit AWAY from the client?
 *
 * The direction is a property of the ENTRY, not of the request — reversing a top-up is
 * a debit and reversing a call charge is a credit — and the server derives it exactly
 * this way. It decides two things here: whether the step-up header is sent at all (one
 * the API ignores is a confirmation of nothing), and how loudly the screen states the
 * consequence.
 *
 * Read off the DIGITS, never `Number()`: `formatINR` keeps a leading minus and so does
 * this, which is the same reason the ledger row colours itself from the string
 * (hard rule 7 — parsing money in the browser is how ₹10,159.00 becomes
 * ₹10,158.999999999998).
 */
export function takesCreditAway(entry: Pick<LedgerEntry, "delta_inr">): boolean {
  return !entry.delta_inr.trim().startsWith("-");
}

/** Entries with something left to take back — the only ones worth offering. */
export function correctableEntries(entries: readonly LedgerEntry[]): LedgerEntry[] {
  return entries.filter((entry) => !isFullyReversed(entry));
}

/**
 * Nothing left to take back, decided WITHOUT parsing.
 *
 * `reversible_inr` is `to_paise`d server-side, so a zero is always some spelling of
 * `0.00` — the regex accepts the family rather than pinning one literal, because a
 * console that mistook `"0.0000"` for a live figure would offer a correction the route
 * is bound to refuse.
 */
const ZERO_RUPEES = /^0+(?:\.0+)?$/;

export function isFullyReversed(entry: Pick<LedgerEntry, "reversible_inr">): boolean {
  return ZERO_RUPEES.test(entry.reversible_inr.trim());
}

/** What the operator submits to correct one entry. Strings, because the money one is. */
export interface AdjustmentDraft {
  /** The `credit_ledger` row being corrected. */
  entry: LedgerEntry;
  /** How much of it to take back, as DIGITS (hard rule 7). Positive; never signed. */
  amountInr: string;
  /** Required. Reaches the entry's `meta` and the audit record verbatim. */
  reason: string;
}

/**
 * Append a compensating entry.
 *
 * `admin:tenants`, the same permission and the same argument as the top-up: this is
 * admin-realm support work, and there is no `billing:write` in the registry. The ADMIN
 * session with the tenant in the path, never an impersonating one — `admin:tenants` is
 * in `MUTATING_PERMISSIONS` and D-22 would correctly refuse it.
 *
 * **The step-up header is sent only for the dangerous direction**, because that is the
 * only direction the route asks for one. Taking credit off a client's wallet is the
 * act that needs confirming; putting a wrongly-charged call back is ordinary support.
 *
 * There is no optimistic update and no `recorded` guess. Both outcomes are 200 and the
 * flag is the only thing that separates "we just took ₹50,000 off this client" from
 * "that correction was already made" — the same distinction `useRecordTopUp` refuses to
 * smooth over, one direction more expensive.
 */
export function useRecordAdjustment(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ entry, amountInr, reason }: AdjustmentDraft) => {
      const body: AdjustmentIn = {
        corrects_entry_id: entry.id,
        amount_inr: amountInr.trim(),
        reason: reason.trim(),
      };
      return apiRequest<AdjustmentResult>(session, adjustmentsPath(tenantId), {
        method: "POST",
        body,
        confirmAction: takesCreditAway(entry)
          ? creditAdjustmentConfirmation(entry.id)
          : undefined,
      });
    },
    // Three things moved: the balance, the ledger, and every entry's `reversible_inr`.
    // The third is why a replay must re-read too — the figure the next correction is
    // offered against is derived from rows this screen cannot recompute.
    onSuccess: () => void client.invalidateQueries({ queryKey: creditsKey(tenantId) }),
  });
}

/* --------------------------------------------------------------------------
 * Restatements (D-89) — the repair for a payment recorded for TOO LITTLE.
 *
 * The mirror image of the adjustment above, and deliberately NOT the same control. An
 * adjustment names a ledger ENTRY and takes credit away, bounded by what that entry
 * moved. A restatement names a PAYMENT and says what the bank actually transferred; the
 * server credits the difference against the same reference, so the wallet keeps showing
 * one bank transfer instead of the `UTR-123-part2` invention this replaces.
 * ----------------------------------------------------------------------- */

export function restatementsPath(tenantId: string): string {
  return `${creditsPath(tenantId)}/restatements`;
}

/** The request body. `corrected_amount_inr` is sent as a STRING; see the header. */
export type RestatementIn = Schemas["RestatementIn"];

/** The answer. `recorded: false` means this restatement was already made. */
export type RestatementResult = Schemas["RestatementOut"];

/**
 * The step-up string, copied from the route VERBATIM
 * (`credit_routes.topup_restatement_confirmation`).
 *
 * It carries the AMOUNT as well as the reference, which
 * `creditAdjustmentConfirmation` deliberately does not — and the difference is worth
 * repeating where the header is built. The adjustment's danger is "which row"; this
 * route's is "how much", because a restatement has no ceiling but the statement the
 * operator is reading. So a confirmation captured for ₹50,000 cannot travel with a
 * request for ₹500,000, and changing the figure means confirming the new one.
 *
 * The amount is passed through as the operator's DIGITS, never parsed. The server
 * quantizes both this string and the ledger key with the same function, so `50000.0`
 * and `50000.00` agree on the wire — but a `Number()` here would be the one place
 * hard rule 7 broke, on the field that decides how much money appears.
 */
export function topupRestatementConfirmation(paymentRef: string, correctedAmountInr: string): string {
  return `restate_topup:${paymentRef}:${correctedAmountInr.trim()}`;
}

/**
 * The same shape check as the other two money fields, said for a RESTATEMENT.
 *
 * The message is the whole reason this is a third function rather than a third caller of
 * `rupeeProblem`: the mistake this field admits is not a malformed number, it is a
 * CORRECTLY FORMED one that means the wrong thing — the difference typed where the total
 * belongs. So every sentence here says "total", and the field's own label and hint say
 * it again beside the figure the reference already credits.
 */
export function restatementAmountProblem(raw: string): string | null {
  switch (rupeeFault(raw)) {
    case "missing":
      return "Enter the TOTAL the bank moved, exactly as the statement shows it.";
    case "shape":
      return `${DIGITS_ONLY} The total the bank moved — not the difference.`;
    case "zero":
      return "A payment has to be more than zero. Enter the total the statement shows.";
    default:
      return null;
  }
}

/** What the operator submits to restate one payment. Strings, because the money one is. */
export interface RestatementDraft {
  /** The payment being restated — chosen from the wallet's own list, never typed. */
  payment: Payment;
  /** THE TOTAL THE BANK MOVED, as DIGITS (hard rule 7). Never the difference. */
  correctedAmountInr: string;
  /** Required. Reaches the entry's `meta` and the audit record verbatim. */
  reason: string;
}

/**
 * Credit the difference on an under-recorded payment.
 *
 * `admin:tenants`, the same permission and the same argument as the other two writes.
 * The ADMIN session with the tenant in the path, never an impersonating one — it is in
 * `MUTATING_PERMISSIONS` and D-22 would correctly refuse it.
 *
 * **The step-up header goes on EVERY call**, unlike `useRecordAdjustment`, which sends
 * one only in the dangerous direction. That is the route's own rule and not this
 * screen's opinion: this correction has exactly one direction, it is unbounded, and it
 * moves money towards the party who will never report an error in their favour.
 *
 * No optimistic update and no `recorded` guess. Both outcomes are 200 and the flag is
 * the only thing separating "we have just put ₹45,000 on this client" from "that
 * restatement was already made".
 */
export function useRecordRestatement(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ payment, correctedAmountInr, reason }: RestatementDraft) => {
      const amount = correctedAmountInr.trim();
      const body: RestatementIn = {
        payment_ref: payment.payment_ref,
        // A string, always — the route REFUSES the JSON number (hard rule 7).
        corrected_amount_inr: amount,
        reason: reason.trim(),
      };
      return apiRequest<RestatementResult>(session, restatementsPath(tenantId), {
        method: "POST",
        body,
        confirmAction: topupRestatementConfirmation(payment.payment_ref, amount),
      });
    },
    // The balance, the ledger and the payment's own total all moved — and the third is
    // what the NEXT restatement of this payment would be measured against, so a stale
    // one on screen is how somebody restates from a figure that is no longer true.
    onSuccess: () => void client.invalidateQueries({ queryKey: creditsKey(tenantId) }),
  });
}
