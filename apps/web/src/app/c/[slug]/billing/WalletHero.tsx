"use client";

import { AlertTriangle, PhoneIncoming, Timer, Wallet } from "lucide-react";

import { NOTICE_TONES, formatINR } from "@/components/ui";
import { runwaySentence, walletState, type Wallet as WalletData } from "@/lib/api/wallet";

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
 * **The empty-wallet banner leads with the reassurance.** An owner who reads "your credit
 * has run out" concludes their phone has stopped being answered. It has not — the gate is
 * outbound-only (`compliance/service.py`) — and that is the single most expensive wrong
 * belief this product can create, so the first clause is "people calling you still get
 * through" and the second is what actually stopped.
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
}) {
  const state = walletState(wallet);
  /* DAY ONE IS NOT AN OUTAGE. A zero balance and an empty history is an account that
     has not started, and "your calling credit has run out" is false about it — it says
     something broke, on the first screen a new client opens, before they have done
     anything wrong. Both sentences lead with the same reassurance, so the two variants
     say the same thing to somebody who reads the first line and stops. */
  const dayOne = state === "stopped" && funded === false;
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
            <PhoneIncoming className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {/* NOT "answering is free": a low balance never BLOCKS an incoming call (the
                dispatch gate is outbound-only), but an inbound minute is metered and
                debited like any other — `charge_for_call` takes no direction. The two are
                different facts and this line used to merge them. */}
            {dayOne
              ? "People calling you already get through — a low balance never blocks an incoming call, though answering one uses credit like any other."
              : "People calling you still get through — a low balance never blocks an incoming call, though answering one uses credit like any other."}
          </p>
          {dayOne ? (
            <p className="mt-2">
              Your agents cannot make outgoing calls until there is credit on the account.
              Add some below and your campaigns and call-backs start straight away.
            </p>
          ) : funded === null ? (
            /* THE HISTORY HAS NOT ARRIVED, so neither sentence may be asserted. This one
               is true of both: it names what stopped without claiming money ran out on an
               account that may never have had any (BUILD-LOG §52 — an unknown is not a
               state). */
            <p className="mt-2">
              Outgoing calls need credit on the account, and there is none on it right now.
              Campaigns and call-backs run again as soon as you add credit below.
            </p>
          ) : (
            <p className="mt-2">
              Outgoing calls have stopped because your calling credit has run out. Campaigns
              and call-backs start again as soon as you add credit below.
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
            reaches zero your outgoing calls stop — people calling you still get through
            either way. We email the account owner at this point too.
          </p>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {/* THE BALANCE. `formatINR` formats the digits the server sent and never parses
            them — `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998 on
            the screen a client checks against their own books (hard rule 7). */}
        <div className="rounded-card border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] sm:p-6">
          <p className="flex items-center gap-2 text-[13px] font-medium text-ink-muted">
            <Wallet className="h-4 w-4 text-brand" aria-hidden />
            Calling credit
          </p>
          <p className="mt-2 text-4xl font-bold tracking-tight tabular-nums text-ink">
            {formatINR(wallet.balance_inr)}
          </p>
          <p className="mt-2 text-xs text-ink-muted">
            Outgoing calls stop when this reaches zero. Incoming calls are never affected.
          </p>
          {/* ⚠ "STOP WHEN THIS REACHES ZERO" SAT OVER A FIGURE THAT CAN BE NEGATIVE, and
              the sentence that explains a negative balance lives in `LotsPanel`, which
              only renders when the lot read SUCCEEDED — so a hero reading "−₹120.00" could
              appear with nothing on the screen but a sentence about zero. A call already
              running when the credit went is finished rather than cut off, which is the
              only way a balance goes below zero, and the next top-up repays it first (plan
              §0 Q5, ADDENDUM 2 §2.2).

              Read off the SIGN of the string the server sent — no arithmetic, no
              comparison against a parsed number (hard rule 7) — and rendered only when it
              applies: an edge case explained to every client on every visit is noise, and
              this one is a fact about a figure that is on screen or it is not. */}
          {wallet.balance_inr.trimStart().startsWith("-") && (
            <p className="mt-2 text-xs text-ink-muted">
              It can go a little below zero when a call is already in progress — we finish
              that call rather than cut it off. Your next top-up clears what is owed first,
              and the rest opens as new credit.
            </p>
          )}
        </div>

        {/* THE RUNWAY, at the same weight as the balance — see the module comment. */}
        <div className="rounded-card border border-line bg-brand-soft p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] sm:p-6">
          <p className="flex items-center gap-2 text-[13px] font-medium text-brand-strong">
            <Timer className="h-4 w-4" aria-hidden />
            How long this lasts
          </p>
          <p className="mt-2 text-xl font-semibold leading-snug tracking-tight text-ink">
            {runwaySentence(wallet.runway)}
          </p>
          {/* THE WORKING, not just the conclusion. An owner who disagrees with "nine
              days" can see the ₹340 a day it came from and knows straight away whether
              the platform or their memory is wrong. */}
          {wallet.runway.daily_burn_inr !== null && (
            <p className="mt-2 text-xs text-ink-muted">
              Worked out from {formatINR(wallet.runway.daily_burn_inr)} a day over the last{" "}
              {wallet.runway.window_days} days.
            </p>
          )}
          {/* THE MINUTES, ONE FIGURE PER VOICE QUALITY — and the reason there are two is
              the reason the old single line had to go. It read "about N minutes of calling
              at today's rate", and under D-547 there is no "today's rate": what a minute
              costs depends on the voice the agent speaks with AND on which purchase the
              credit is drawn from. Two figures, both the server's, or none. */}
          {lots && <TierRunwayLines lots={lots} />}
        </div>
      </div>
    </div>
  );
}
