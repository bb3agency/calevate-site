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

import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect } from "react";

import { formatIST } from "@/components/ui";
import { lookup } from "@/lib/lookup";

import { agreementsKey } from "./agreements";
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
 * The wallet the client shell already read, without asking again (D-697). Every client
 * screen mounts under the shell, whose trial strip reads `useWallet`; a screen that only
 * needs to know whether the account is on a test-calls-only trial reads that same cache
 * entry and never sends a request of its own. `undefined` until the shell's read lands.
 */
export function useShellWallet(session: Session): Wallet | undefined {
  return useQuery({
    queryKey: walletKey(session.orgSlug),
    queryFn: () => apiRequest<Wallet>(session, "/v1/billing/wallet"),
    enabled: false,
  }).data;
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
    queryFn: () => apiRequest<TopUpAttempt[]>(session, TOPUP_ATTEMPTS_PATH),
  });
}

const TOPUP_ATTEMPTS_PATH = "/v1/billing/wallet/topups";

/** How often a verified payment's credit is looked for, and for how long at most. */
export const CREDIT_POLL_MS = 4_000;
export const CREDIT_WAIT_MS = 3 * 60_000;

/** A payment this page saw verified, and the instant it stops waiting for the credit. */
export interface AwaitedCredit {
  receipt: string;
  until: number;
}

function captured(attempts: TopUpAttempt[] | undefined, receipt: string): boolean {
  return attempts?.some((row) => row.receipt === receipt && row.outcome === "captured") ?? false;
}

/**
 * Has the credit for a payment this page just saw verified reached the wallet?
 *
 * The Checkout callback proves the payment and credits NOTHING
 * (`payment_routes.confirm_topup_callback`): the webhook credits, seconds later, and marks
 * the attempt `captured` in the same transaction. So the refetch `useConfirmTopUp` makes
 * on the callback almost always reads the balance from before the payment — and nothing
 * else re-reads it while the client stays on the page, because the payment window is an
 * overlay and closing it is not a window focus. A client told "your balance updates as
 * soon as the provider confirms it" then watched a balance that never moved, which is the
 * screen most likely to make them pay twice.
 *
 * Polls the attempts list for THIS receipt rather than the balance, because a balance can
 * move for other reasons (a call ending, an operator's grant) and would stop the wait on
 * the wrong event. Stops when the attempt is captured or at `until`, and on capture
 * re-reads everything the credit moved.
 */
export function useCreditLanding(session: Session, awaited: AwaitedCredit | null): boolean {
  const client = useQueryClient();
  const attempts = useQuery({
    queryKey: walletAttemptsKey(session.orgSlug),
    queryFn: () => apiRequest<TopUpAttempt[]>(session, TOPUP_ATTEMPTS_PATH),
    enabled: awaited !== null,
    refetchInterval: (query) =>
      awaited !== null &&
      !captured(query.state.data, awaited.receipt) &&
      Date.now() < awaited.until
        ? CREDIT_POLL_MS
        : false,
  });
  const landed = awaited !== null && captured(attempts.data, awaited.receipt);

  useEffect(() => {
    if (!landed) return;
    // The wallet prefix covers the balance, the ledger, the lots and this list; readiness
    // carries the `no_credits` blocker a first top-up clears.
    void client.invalidateQueries({ queryKey: walletKey(session.orgSlug) });
    void client.invalidateQueries({ queryKey: ["usage", session.orgSlug] });
    void client.invalidateQueries({ queryKey: agreementsKey(session.orgSlug) });
  }, [landed, client, session.orgSlug]);

  return landed;
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
 * What one line of the wallet IS, in the words a client uses.
 *
 * **This is NOT `credits.creditReasonLabel`, and the difference is the reader.** That map
 * is the admin console's and says "Payment recorded" and "Compensating adjustment" —
 * accurate operator vocabulary, and two phrases no clinic owner has ever used. The
 * founder's standard for client-facing copy bans exactly that register (the API's own
 * `tests/plain_language_guard_test.py` states the same rule one tier down), so the two
 * realms carry two vocabularies for one ledger on purpose.
 *
 * What is NOT duplicated is the part where a disagreement would be a defect:
 * `takesCreditAway` — which way an entry moved the balance — stays imported from the admin
 * module, so the two screens can word an entry differently and can never point it in
 * opposite directions.
 *
 * Fails VISIBLE, like every other wire lookup here: a reason this build has no word for
 * prints as the server sent it, because an unrecognised row on a money ledger is precisely
 * the row worth reading.
 */
const WALLET_REASON_LABEL: Record<string, string> = {
  topup: "Credit added",
  usage: "Calls",
  adjustment: "Correction we made",
  refund: "Refunded to you",
};

export function walletReasonLabel(reason: string): string {
  return lookup(WALLET_REASON_LABEL, reason) ?? reason;
}

/**
 * The name a client reads for one wallet row: the server's `label` when it sent one, else
 * the reason's word. A rental debit is `reason = usage` (the ledger's reason enum is
 * fixed), so without the label it would read "Calls" (D-665).
 */
export function walletEntryLabel(entry: Pick<WalletEntry, "label" | "reason">): string {
  return entry.label ?? walletReasonLabel(entry.reason);
}

/**
 * What the wallet is DOING to this account right now, as one of four states.
 *
 * Derived here rather than in the page so the hero, the banner and the assistant's
 * declared facts cannot disagree about the same wallet. `stopped` is the SERVER's
 * `outbound_stopped` — the dial gate's own verdict — never a balance comparison made
 * here, because that comparison is tier-blind and would stop an invoiced client over a
 * wallet they never bought.
 *
 * ⚠ **`stopped` MEANS BOTH DIRECTIONS (D-551), THOUGH THE WIRE FIELD IS NAMED
 * `outbound_stopped`.** The same verdict that refuses a dial silences the agents' ANSWERING
 * (`agents/service.py::reconcile_inbound_answering`), so copy rendered under this state
 * must not tell a client that people ringing them still get through — it is the one thing
 * they will be asked within the hour, and `tests/credit_stop_copy_test.py` fails if any
 * surface says it again.
 */
export type WalletState = "trial" | "stopped" | "low" | "healthy" | "not-prepaid";

/**
 * CREDIT AS MINUTES FIRST (founder, REDESIGN-2): "About 240 minutes left", from the
 * server's own `minutes_left` per voice tier, never a rate computed here. One tier is one
 * figure; two tiers that differ are a range, because what a minute costs depends on the
 * voice. `null` (this deployment quotes no rate) returns null and the caller shows rupees
 * alone; it is never read as zero.
 */
export function minutesLeftPhrase(wallet: Pick<Wallet, "minutes_left">): string | null {
  const tiers = wallet.minutes_left;
  if (!tiers || tiers.length === 0) return null;
  const counts = tiers.map((t) => t.minutes);
  const low = Math.min(...counts);
  const high = Math.max(...counts);
  const n = (v: number) => v.toLocaleString("en-IN");
  if (high === 0) return "No minutes left";
  if (low === high) return `About ${n(low)} ${low === 1 ? "minute" : "minutes"} left`;
  return `About ${n(low)} to ${n(high)} minutes left`;
}

/**
 * `trial` is checked BEFORE `low` because `is_low` is a plain balance comparison and stays
 * true for a ₹0.00 wallet throughout a trial (D-536), when an empty wallet stops nothing.
 * The server already answers `outbound_stopped: false` during a trial; without this arm the
 * same wallet would fall through to `low` and every screen would warn that calls are about
 * to stop.
 */
export function walletState(wallet: Wallet): WalletState {
  if (!wallet.prepaid) return "not-prepaid";
  if (activeTrial(wallet) !== null) return "trial";
  if (wallet.outbound_stopped) return "stopped";
  if (wallet.is_low) return "low";
  return "healthy";
}

/** This client's trial, as the wallet read publishes it — dates and a count, never a cost. */
export type WalletTrial = Schemas["WalletTrialOut"];

/**
 * The trial this account is inside right now, or null.
 *
 * Reads the server's `active`, which asks the clock as well as the stored status
 * (`billing/trials.TrialState.is_active`), so a trial past its end date that the nightly
 * sweep has not yet closed is already null here. An invoiced account can be on a trial
 * too, so this does not look at `prepaid`.
 */
export function activeTrial(wallet: Wallet | undefined): WalletTrial | null {
  return wallet?.trial?.active === true ? wallet.trial : null;
}

/** How much of a running trial is left, for the countdown and the last-day prompt. */
export interface TrialTimeLeft {
  /** Inside the final 24 hours: count in hours, and ask for a top-up. */
  lastDay: boolean;
  /** "3 days left", or on the last day "24 hours left" down to "1 hour left". */
  text: string;
}

const HOUR_MS = 3_600_000;

/**
 * The countdown, in days, or in hours on the last day.
 *
 * The day count is the SERVER's `days_remaining`, which rounds up (four hours left is
 * "1 day", never "0"), so this screen and the operator's trial panel cannot disagree about
 * how many days a client has. The last day is `days_remaining === 1`, i.e. 24 hours or less;
 * only that day is split into hours, from `ends_at` and the browser clock, rounded up for
 * the same reason. The hour figure is the only thing derived here and it is never money.
 */
export function trialTimeLeft(trial: WalletTrial, now: Date = new Date()): TrialTimeLeft {
  const days = trial.days_remaining ?? 0;
  if (days > 1) return { lastDay: false, text: `${days} days left` };
  const ms = new Date(trial.ends_at).getTime() - now.getTime();
  const hours = Number.isNaN(ms) ? 1 : Math.min(24, Math.max(1, Math.ceil(ms / HOUR_MS)));
  return { lastDay: true, text: `${hours} ${hours === 1 ? "hour" : "hours"} left` };
}

/**
 * When the trial ends, as a client reads it: "10 Oct, 10:58 pm IST". `IST` is written out
 * because the screen is also opened by people whose laptop clock is not in India, and an
 * unlabelled time would read as theirs.
 */
export function trialEndsAt(trial: WalletTrial): string {
  return `${formatIST(trial.ends_at)} IST`;
}
