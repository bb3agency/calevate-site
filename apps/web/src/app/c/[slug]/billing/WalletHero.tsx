"use client";

import type { ReactNode } from "react";
import { AlertTriangle, PhoneOff } from "lucide-react";

import { FlashValue } from "@/components/console/valueFlash";
import { NOTICE_TONES, formatINR, hasNonZeroDigit } from "@/components/ui";
import {
  activeTrial,
  runwaySentence,
  walletState,
  type Wallet as WalletData,
} from "@/lib/api/wallet";

import { TierRunwayLines } from "./LotsPanel";
import type { WalletLots } from "./lots";

/**
 * The hero: what you have, and how long it lasts.
 *
 * **"HOW LONG WILL THIS LAST" IS THE POINT OF THIS SCREEN, and it is why the runway is
 * set in the same type size as the balance rather than as a caption under it.** A rupee
 * figure means nothing to a clinic owner — ₹3,400 is either a fortnight or an afternoon
 * depending on how much they call — and the number they actually plan around is the days.
 * So the two are a PAIR, not a figure and its footnote.
 *
 * **The sentence is never invented.** `runwaySentence` refuses to print a projection the
 * server declined to make, and says which of four reasons applies. On a brand-new account
 * — the first thing every client ever sees here — that reads "we need about 7 days of
 * calling to work out how long your credit lasts", which is true, and not "0 days left",
 * which is a lie that would make an owner buy credit they do not need.
 *
 * **MONEY IS NEVER CONVEYED BY COLOUR ALONE.** Every state carries an icon and a sentence;
 * the tint is the third channel, not the only one (WCAG 1.4.1). The empty state is a
 * `role="alert"` because it names something that has already stopped happening.
 *
 * ⚠ **THE EMPTY-WALLET BANNER MAY NOT REASSURE ABOUT INCOMING CALLS.** At zero the agents
 * are silenced at the engine (`agents/service.py::reconcile_inbound_answering`, D-551) and
 * a caller hears a short apology, so "people calling you still get through" would be the
 * most expensive false sentence in the product: the owner reads it, does nothing, and their
 * callers are turned away all night.
 *
 * So the banner leads with what has actually happened, then with the two things the owner
 * will be asked about within the hour: what their own customers hear (an apology that
 * gives no reason and says nothing about their account, because a caller who works out
 * that the business has not paid is a harm we inflicted on our client), and that topping
 * up is the whole fix. Same three facts, same order, as
 * `crm/attention.BLOCK_REMEDIES["no_credits"]` and the low-balance email — a client must
 * not get two accounts of one event on two screens.
 *
 * **AN EMPTY WALLET AND A BRAND-NEW ONE ARE THE SAME NUMBER AND DIFFERENT NEWS**, and
 * since prepaid became the motion every account starts on, the second one is what most
 * clients meet first. `outbound_stopped` is true on both, so the server's verdict alone
 * cannot tell them apart; `funded` — has anything ever moved on this wallet — is what
 * does, and it comes from the ledger the panel below already reads (same query key, so no
 * second request). "Your calling credit has run out" on day one is a sentence about a
 * failure to a client who has not had a chance to have one yet.
 */
export function WalletHero({
  wallet,
  funded,
  lots,
  action,
}: {
  wallet: WalletData;
  /**
   * Has this wallet ever had anything on it? `null` while the history is still in
   * flight — see the day-one paragraph in the module comment.
   */
  funded: boolean | null;
  /**
   * The lot queue, when the server can answer for it. It carries the RUNWAY IN MINUTES —
   * one figure per voice quality, summed lot by lot at each lot's own frozen rate (D-547).
   * Absent, no minutes figure is printed at all: `wallet.minutes_left` divides one balance
   * by one LIST rate, which is precisely the arithmetic lots exist to stop being true, and
   * a wrong minute count is worse on this screen than none.
   */
  lots: WalletLots | undefined;
  /** The screen's one primary action (Add credit), set beside the figures. */
  action?: ReactNode;
}) {
  const state = walletState(wallet);
  const trial = activeTrial(wallet);
  /* DAY ONE IS NOT AN OUTAGE. A zero balance and an empty history is an account that
     has not started, and "your calling credit has run out" is false about it — it says
     something broke, on the first screen a new client opens, before they have done
     anything wrong. Both sentences lead with the same reassurance, so the two variants
     say the same thing to somebody who reads the first line and stops. */
  const dayOne = state === "stopped" && funded === false;
  const negative = wallet.balance_inr.trimStart().startsWith("-");
  /* WHAT IS OWED, from the lot queue's `overdraft_inr` when it was read, else from the sign
     of the balance — string work only, no arithmetic on money (hard rule 7). */
  const owed =
    lots && hasNonZeroDigit(lots.overdraft_inr)
      ? lots.overdraft_inr
      : negative && hasNonZeroDigit(wallet.balance_inr)
        ? wallet.balance_inr.trimStart().slice(1)
        : null;
  return (
    <div className="space-y-4">
      {state === "stopped" && (
        <div
          /* `alert` interrupts; `status` waits its turn. Something HAS stopped on an
             account that was running, and nothing has on a new one — so the day-one
             variant is polite and the run-out is not. */
          role={dayOne ? "status" : "alert"}
          className={`rounded-card border p-4 text-sm ${
            dayOne ? NOTICE_TONES.neutral : NOTICE_TONES.stop
          }`}
        >
          <p className="flex items-start gap-2 font-semibold">
            <PhoneOff className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {/* THE HEADLINE FACT ON BOTH VARIANTS IS THE PHONE, not the campaigns: an
                owner whose agents have gone quiet is about to be asked by their own
                customers, and that is the sentence they must not have to hunt for. Day one
                differs only in tense — nothing has stopped on an account that never
                started, so it says what will not happen rather than what has. */}
            {dayOne
              ? "Until there is credit on the account your agents cannot make outgoing calls and will not answer incoming ones."
              : "Your calling credit has run out, so outgoing calls have stopped and your agents are no longer answering incoming ones."}
          </p>
          {dayOne ? (
            <p className="mt-2">
              Anyone ringing you meanwhile hears a short apology asking them to try again
              later; it gives no reason and says nothing about your account. Add credit
              below and your agents start answering, and your campaigns and call-backs
              start going out, straight away.
            </p>
          ) : funded === null ? (
            /* THE HISTORY HAS NOT ARRIVED, so neither sentence may be asserted. This one
               is true of both: it names what stopped without claiming money ran out on an
               account that may never have had any (BUILD-LOG §52 — an unknown is not a
               state). */
            <p className="mt-2">
              There is no credit on the account right now, and calling needs it in both
              directions. People ringing you hear a short apology asking them to try again
              later — it gives no reason and says nothing about your account. Add credit
              below and answering, campaigns and call-backs all start again straight away.
            </p>
          ) : (
            <p className="mt-2">
              People ringing you hear a short apology asking them to try again later — it
              gives no reason and says nothing about your account. Add credit below and
              answering, campaigns and call-backs all start again straight away.
            </p>
          )}
        </div>
      )}
      {state === "low" && (
        <div role="status" className={`rounded-card border p-4 text-sm ${NOTICE_TONES.warn}`}>
          <p className="flex items-start gap-2 font-semibold">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            Your calling credit is running low.
          </p>
          <p className="mt-2">
            You have {formatINR(wallet.balance_inr)} left, which is below the{" "}
            {formatINR(wallet.low_balance_threshold_inr)} we start warning at. When it
            reaches zero your calls stop in both directions: nothing goes out, and your
            agents stop answering the phone. We email the account owner at this point too.
          </p>
        </div>
      )}

      {/* THE WALLET HEADER: the balance and the runway side by side on whitespace, not in
          two cards — they are one fact (what you have, and how long it lasts) — with the
          screen's one primary action beside them. */}
      <section
        aria-label="Your calling credit"
        className="flex flex-col gap-5 border-b border-line pb-6 lg:flex-row lg:items-end lg:justify-between"
      >
        <div className="grid flex-1 gap-6 sm:grid-cols-2">
          {/* THE BALANCE. `formatINR` formats the digits the server sent and never parses
              them — `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998 on
              the screen a client checks against their own books (hard rule 7). */}
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-ink-muted">Calling credit</p>
            <p
              className={`mt-1 text-4xl font-semibold tracking-tight tabular-nums ${
                negative ? "text-danger" : "text-ink"
              }`}
            >
              <FlashValue value={wallet.balance_inr}>{formatINR(wallet.balance_inr)}</FlashValue>
            </p>
            {owed !== null && (
              <p className="mt-1 text-sm font-medium text-danger">
                You owe {formatINR(owed)}
              </p>
            )}
            {/* Both directions stop at zero (D-551); during a trial neither does (D-536). */}
            <p className="mt-2 text-xs text-ink-muted">
              {trial !== null
                ? "During your free trial nothing is taken from this credit, and an empty balance stops no calls."
                : "Outgoing calls stop when this reaches zero, and your agents stop answering incoming ones."}
            </p>
            {/* THE BALANCE CAN BE NEGATIVE and the sentence above talks about zero, so the
                explanation has to be here: a call already running when the credit went is
                finished rather than cut off — the only way a balance goes below zero — and
                the next top-up repays it first. Read off the SIGN of the server's string,
                never a parsed number, and shown only when it applies. */}
            {negative && (
              <p className="mt-2 text-xs text-ink-muted">
                It can go a little below zero when a call is already in progress — we finish
                that call rather than cut it off. Your next top-up clears what is owed first,
                and the rest opens as new credit.
              </p>
            )}
          </div>

          {/* THE RUNWAY, at the weight of the balance — see the module comment. */}
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-ink-muted">How long this lasts</p>
            <p className="mt-1 text-lg font-semibold leading-snug tracking-tight text-ink">
              {runwaySentence(wallet.runway)}
            </p>
            {/* THE WORKING, not just the conclusion: an owner who disagrees with "nine
                days" can see the ₹340 a day it came from. */}
            {wallet.runway.daily_burn_inr !== null && (
              <p className="mt-1 text-xs text-ink-muted">
                Worked out from {formatINR(wallet.runway.daily_burn_inr)} a day over the last{" "}
                {wallet.runway.window_days} days.
              </p>
            )}
            {/* ONE FIGURE PER VOICE QUALITY (D-547): what a minute costs depends on the
                agent's voice AND the purchase it is drawn from, so two server figures or
                none — never one balance divided by one list rate. */}
            {lots && <TierRunwayLines lots={lots} />}
          </div>
        </div>
        {action && <div className="shrink-0 lg:pb-1">{action}</div>}
      </section>
    </div>
  );
}
