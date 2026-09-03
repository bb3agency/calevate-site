"use client";

/**
 * The client's own prepaid wallet — balance, runway, ledger, receipts, and the payments
 * that went nowhere.
 *
 * `lib/api/credits.ts` is the ADMIN twin and this is deliberately NOT it: that module
 * writes (a bank transfer recorded, a compensating adjustment, a restatement) and carries
 * `reversible_inr`, a ceiling that exists so an OPERATOR can be offered a correction.
 * None of that is a client's business. What the two DO share is the money vocabulary —
 * the rupee-shape check and the ledger reason labels — and that is imported from here's
 * neighbour rather than copied, so a reason this build has no word for prints the same
 * way on both screens.
 *
 * ## Three properties of these routes this module must not smooth over
 *
 * - **`runway.days` is null more often than not, and the reason is the payload.** A
 *   projection may not honestly be asserted from three days of history, and the server
 *   says which of four reasons applies (`basis`). A hook that defaulted it to 0 would
 *   turn "we cannot tell yet" into "you run out today" on a brand-new account, which is
 *   the exact sentence that makes an owner top up money they do not need to.
 * - **`minutes_left: null` is not zero.** Null means this deployment quotes no rate;
 *   zero means the wallet is empty. Rendering the first as the second tells a client
 *   with money in their wallet that they cannot call.
 * - **Money is a STRING both ways** (hard rule 7). Every rupee value on these types is an
 *   exact decimal string and stays one to the DOM. Nothing in this file or its screens
 *   calls `Number()` on one — `formatINR` formats the DIGITS, because `Number("10159.00")`
 *   is how ₹10,159.00 becomes ₹10,158.999999999998 on the screen a client checks against
 *   their own books.
 *
 * Types come from `schema.d.ts` (`pnpm gen:api`), never hand-mirrored.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** Balance, the dial gate's verdict, the runway and the drawdown — one read. */
export type Wallet = Schemas["WalletOut"];
/** How long the balance lasts, and when it may not be said, WHY not. */
export type Runway = Schemas["RunwayOut"];
/** Where the money went, over the same window the runway was measured on. */
export type Drawdown = Schemas["DrawdownOut"];
/** The entries, plus one line per payment behind them. */
export type WalletLedger = Schemas["LedgerOut"];
/**
 * One line of the wallet. Named apart from the admin console's `LedgerEntry` on the
 * server too (`billing/wallet_routes.WalletEntryOut`), because two schemas under one
 * name make the generator emit fully-qualified names for both.
 */
export type WalletEntry = Schemas["WalletEntryOut"];
/** One payment, as the wallet holds it — what a receipt is issued against. */
export type WalletPayment = Schemas["WalletPaymentOut"];
/** A payment that was started, whatever became of it. */
export type TopUpAttempt = Schemas["TopUpAttemptOut"];
/** A receipt. NOT a tax invoice — `document_type` says so and the screen reads it. */
export type PaymentReceipt = Schemas["ReceiptOut"];

/**
 * How many entries the screen asks for. Sent EXPLICITLY rather than left to the route's
 * default, the convention `credits.LEDGER_LIMIT` set: the request the console makes is
 * visible in one place, and the query key, the path and the fixtures cannot drift apart.
 * The route bounds it at 200.
 */
export const WALLET_LEDGER_LIMIT = 50;

export function walletKey(slug: string): readonly unknown[] {
  return ["wallet", slug];
}

export function walletLedgerKey(slug: string): readonly unknown[] {
  return ["wallet", slug, "ledger"];
}

export function walletAttemptsKey(slug: string): readonly unknown[] {
  return ["wallet", slug, "topups"];
}

/**
 * The balance, the runway and the drawdown.
 *
 * `wallet:read` — which `staff` holds and `billing:read` is not. That is the whole point
 * of the separate permission (`core/rbac.py`): the thing that stops a staff member
 * dialling is an empty wallet, so everyone on the team can see the balance and only the
 * owner can buy.
 */
export function useWallet(session: Session): UseQueryResult<Wallet> {
  return useQuery({
    queryKey: walletKey(session.orgSlug),
    queryFn: () => apiRequest<Wallet>(session, "/v1/billing/wallet"),
  });
}

/**
 * The ledger and the payments behind it. Its OWN query rather than a field on the
 * summary, so a failure to read a year of history cannot blank the balance — which is the
 * one figure a client came to this screen for.
 */
export function useWalletLedger(session: Session): UseQueryResult<WalletLedger> {
  return useQuery({
    queryKey: walletLedgerKey(session.orgSlug),
    queryFn: () =>
      apiRequest<WalletLedger>(
        session,
        `/v1/billing/wallet/ledger?limit=${WALLET_LEDGER_LIMIT}`,
      ),
  });
}

/**
 * Payments that were started — including the ones that failed or never landed.
 *
 * Takes no page size, because the route offers none: this is the "what happened just now"
 * list, and an older attempt is answered by the ledger if it became money and by nothing
 * if it did not.
 */
export function useTopUpAttempts(session: Session): UseQueryResult<TopUpAttempt[]> {
  return useQuery({
    queryKey: walletAttemptsKey(session.orgSlug),
    queryFn: () => apiRequest<TopUpAttempt[]>(session, "/v1/billing/wallet/topups"),
  });
}

/**
 * One payment's receipt, fetched only when the client asks for it.
 *
 * `enabled` on the reference rather than a mount-time fetch: a wallet page showing fifty
 * entries would otherwise make fifty requests for documents nobody opened.
 */
export function usePaymentReceipt(
  session: Session,
  paymentRef: string | null,
): UseQueryResult<PaymentReceipt> {
  return useQuery({
    queryKey: ["wallet", session.orgSlug, "receipt", paymentRef],
    queryFn: () =>
      apiRequest<PaymentReceipt>(
        session,
        `/v1/billing/wallet/receipts/${encodeURIComponent(paymentRef ?? "")}`,
      ),
    enabled: paymentRef !== null,
  });
}

/**
 * The runway, as a SENTENCE — the most useful number on the page, and the one place it is
 * worded.
 *
 * Four bases, four different next actions, and the honest answer for three of them is not
 * a number. This function is where that honesty lives, so no screen has to decide for
 * itself what to print when the server declined to project:
 *
 * - `projected` → "about 9 days of calling left", or "more than a year" past the horizon.
 * - `too_new` → say how long we have been watching and how long we need. A brand-new
 *   account is the FIRST thing a client sees, and "0 days left" would be a lie on day one.
 * - `no_burn` → we measured, and nothing has been spent. Different from "we could not
 *   measure", and a client who has not started calling yet should read it that way.
 * - `empty` → there is no runway to project. The screen says the balance is empty above
 *   this line; repeating a zero here would just be the same fact twice.
 */
export function runwaySentence(runway: Runway): string {
  if (runway.beyond_horizon) return "More than a year of calling at your current pace";
  switch (runway.basis) {
    case "projected":
      return runway.days === null
        ? "We cannot work out how long this lasts yet"
        : `About ${runway.days.toLocaleString("en-IN")} ${
            runway.days === 1 ? "day" : "days"
          } of calling left at your recent pace`;
    case "no_burn":
      return "You have not spent anything recently, so there is nothing to work a pace from";
    case "too_new":
      return `We need about ${runway.min_history_days} days of calling to work out how long your credit lasts — we have ${runway.history_days} so far`;
    case "empty":
      return "There is no credit left to work a pace from";
    default:
      // A basis this build has no word for still says something true rather than
      // rendering blank — the direction `creditReasonLabel` takes for an unknown reason.
      return "We cannot work out how long this lasts yet";
  }
}

/**
 * What the wallet is DOING to this account right now, as one of four states.
 *
 * Derived here rather than in the page so the hero, the banner and the assistant's
 * declared facts cannot disagree about the same wallet. `stopped` is the SERVER's
 * `outbound_stopped` — the dial gate's own verdict — never a balance comparison made
 * here, because that comparison is tier-blind and would stop an invoiced client over a
 * wallet they never bought.
 */
export type WalletState = "stopped" | "low" | "healthy" | "not-prepaid";

export function walletState(wallet: Wallet): WalletState {
  if (!wallet.prepaid) return "not-prepaid";
  if (wallet.outbound_stopped) return "stopped";
  if (wallet.is_low) return "low";
  return "healthy";
}
