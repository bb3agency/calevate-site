"use client";

import { AlertTriangle, PhoneIncoming, Timer, Wallet } from "lucide-react";

import { NOTICE_TONES, formatCount, formatINR } from "@/components/ui";
import { runwaySentence, walletState, type Wallet as WalletData } from "@/lib/api/wallet";

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
 */
export function WalletHero({ wallet }: { wallet: WalletData }) {
  const state = walletState(wallet);
  return (
    <div className="space-y-4">
      {state === "stopped" && (
        <div role="alert" className={`rounded-card border p-4 text-sm ${NOTICE_TONES.stop}`}>
          <p className="flex items-start gap-2 font-semibold">
            <PhoneIncoming className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            People calling you still get through — answering calls never uses your credit.
          </p>
          <p className="mt-2">
            Outgoing calls have stopped because your calling credit has run out. Campaigns
            and call-backs start again as soon as you add credit below.
          </p>
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
          {wallet.minutes_left !== null && (
            <p className="mt-1 text-xs text-ink-muted">
              That is about{" "}
              <strong className="font-semibold tabular-nums text-ink">
                {formatCount(wallet.minutes_left)} minutes
              </strong>{" "}
              of calling at today&apos;s rate.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
