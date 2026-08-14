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
 * - **The route takes no `X-Confirm-Action`.** Unlike every write on `/v1/ops`, this one
 *   accepts no step-up header, so `useRecordTopUp` sends none — a header the API ignores
 *   is a confirmation of nothing. The console's own confirmation is argued on the screen.
 *   Admin-realm MFA is enforced for every admin token in `core/auth.py::verify_token`
 *   (D-68), so this surface is already behind a second factor.
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

/** The wallet: balance, the server's low-balance verdict, and the recent entries. */
export type Credits = Schemas["CreditsOut"];

/** One line of `credit_ledger`. Every amount is exact digits — never a number. */
export type LedgerEntry = Schemas["LedgerEntryOut"];

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

export function rupeeProblem(raw: string): string | null {
  const value = raw.trim();
  if (value === "") return "Enter the amount exactly as the statement shows it.";
  if (!RUPEES.test(value)) {
    return (
      "Digits only, with at most two decimal places — no commas, no ₹ sign, no spaces " +
      "(so 2500.10, not ₹2,500.10). Up to eight digits before the decimal point."
    );
  }
  if (ONLY_ZEROS.test(value)) {
    return (
      "A top-up has to be more than zero. Taking credit BACK is a compensating " +
      "adjustment, never a negative top-up — see below."
    );
  }
  return null;
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
