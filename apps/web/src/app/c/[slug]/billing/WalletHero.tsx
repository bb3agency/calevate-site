"use client";

import { CircleAlert, CircleDashed, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { FlashValue } from "@/components/console/valueFlash";
import { formatINR, hasNonZeroDigit } from "@/components/ui";
import {
  activeTrial,
  trialEndsAt,
  walletState,
  type Runway,
  type Wallet as WalletData,
} from "@/lib/api/wallet";

import { TierRunwayLines } from "./LotsPanel";
import { Why } from "./_ui/Why";
import { firstLapse, formatISTDate, type WalletLots } from "./lots";

/**
 * The summary card: the balance, how long it lasts, when any of it lapses, and the screen's
 * one primary action.
 *
 * **The runway line is printed only when the server made a projection.** "We need 7 days of
 * history" and "nothing to work a pace from" are true and useless to an owner glancing at
 * a balance, so they are not shown at all; a projection that is shown is never invented
 * (`days` and `beyond_horizon` are the server's). The copilot still reads the full reason
 * through `runwaySentence`.
 *
 * **MONEY IS NEVER CONVEYED BY COLOUR ALONE.** Every state carries an icon and a sentence
 * (WCAG 1.4.1). The run-out notice is `role="alert"` because something has already stopped.
 *
 * **THE EMPTY-WALLET NOTICE MAY NOT REASSURE ABOUT INCOMING CALLS.** At zero the agents
 * are silenced at the engine (`agents/service.py::reconcile_inbound_answering`, D-551), so
 * the notice states, in this order, the same three facts as
 * `crm/attention.BLOCK_REMEDIES["no_credits"]` and the low-balance email: both directions
 * have stopped, callers hear an apology that says nothing about the account, and adding
 * credit restarts both.
 *
 * **AN EMPTY WALLET AND A BRAND-NEW ONE ARE THE SAME NUMBER AND DIFFERENT NEWS.**
 * `outbound_stopped` is true on both; `funded` (has anything ever moved on this wallet)
 * tells them apart, so day one reads as "not started", never as "ran out".
 */
export function WalletHero({
  wallet,
  funded,
  lots,
  action,
}: {
  wallet: WalletData;
  /** Has this wallet ever had anything on it? `null` while the history is in flight. */
  funded: boolean | null;
  /**
   * The lot queue, when the server can answer for it: the minutes per voice quality and
   * each lot's lapse date. Absent, no minutes figure is printed — `wallet.minutes_left`
   * divides one balance by one list rate, which lots exist to stop being true (D-547).
   */
  lots: WalletLots | undefined;
  /** The screen's one primary action (Add credit). */
  action?: ReactNode;
}) {
  const state = walletState(wallet);
  const trial = activeTrial(wallet);
  const dayOne = state === "stopped" && funded === false;
  const negative = wallet.balance_inr.trimStart().startsWith("-");
  /* What is owed, from the lot queue when it was read, else from the sign of the balance —
     string work only, no arithmetic on money (hard rule 7). */
  const owed =
    lots && hasNonZeroDigit(lots.overdraft_inr)
      ? lots.overdraft_inr
      : negative && hasNonZeroDigit(wallet.balance_inr)
        ? wallet.balance_inr.trimStart().slice(1)
        : null;
  const runway = runwayLine(wallet.runway);
  const lapse = firstLapse(lots);
  const lapseDay = lapse ? formatISTDate(lapse.expires_at) : null;

  return (
    <section
      aria-label="Your calling credit"
      className="overflow-hidden rounded-card border border-line bg-surface"
    >
      {state === "stopped" && (
        <Notice
          /* `alert` interrupts; `status` waits its turn. Something has stopped on an
             account that was running, and nothing has on a new one. */
          role={dayOne ? "status" : "alert"}
          tone={dayOne ? "neutral" : "stop"}
          title={dayOne ? HERO_COPY.dayOneTitle : HERO_COPY.stoppedTitle}
          why={
            /* `funded === null`: the history has not arrived, so the sentence must be
               true of both a spent wallet and one that never had credit. */
            dayOne || funded === null ? HERO_COPY.dayOneWhy : HERO_COPY.stoppedWhy
          }
        >
          {dayOne ? HERO_COPY.dayOneLine : HERO_COPY.stoppedLine}
        </Notice>
      )}
      {state === "low" && (
        <Notice role="status" tone="warn" title={HERO_COPY.lowTitle}>
          {formatINR(wallet.balance_inr)} left. All calls stop at ₹0.
        </Notice>
      )}

      <div className="flex flex-col gap-5 p-5 sm:flex-row sm:items-end sm:justify-between sm:gap-8 sm:p-6">
        <div className="min-w-0 space-y-1.5">
          <p className="text-meta font-medium text-ink-muted">Calling credit</p>
          {/* `formatINR` formats the server's digits and never parses them (hard rule 7). */}
          <p
            className={`text-[clamp(1.75rem,8vw,2.25rem)] font-semibold leading-none tracking-tight tabular-nums [overflow-wrap:anywhere] ${
              negative ? "text-danger" : "text-ink"
            }`}
          >
            <FlashValue value={wallet.balance_inr}>{formatINR(wallet.balance_inr)}</FlashValue>
          </p>
          {owed !== null && (
            <div className="pt-1 text-body">
              <p className="font-medium text-danger">You owe {formatINR(owed)}</p>
              {/* Read off the SIGN of the server's string, never a parsed number. */}
              <p className="text-ink-muted">Your next top-up clears this first.</p>
              <Why>
                <p>
                  A call in progress is finished rather than cut off, so the balance can dip a
                  little below zero.
                </p>
              </Why>
            </div>
          )}
          {runway && (
            <p className="pt-1 text-body text-ink [text-wrap:pretty]">
              {runway}
              {/* The working, so an owner who doubts the days can see what they came from. */}
              {wallet.runway.daily_burn_inr !== null && runway !== BEYOND && (
                <span className="text-ink-muted">
                  {" "}· about {formatINR(wallet.runway.daily_burn_inr)} a day
                </span>
              )}
            </p>
          )}
          {/* One figure per voice quality, from the lot queue (D-547). */}
          {lots && <TierRunwayLines lots={lots} />}
          {lapse && lapseDay && (
            /* D-900: the date is on screen; the term behind it is under "Credit, by
               purchase" and in "What calls cost". */
            <p className="text-meta text-ink-muted">
              {formatINR(lapse.credits_remaining)} expires on {lapseDay} if unused
            </p>
          )}
          {trial !== null && (
            /* D-536: while a trial runs nothing is debited and an empty balance stops no
               calls, so the trial is a quiet fact here rather than a paragraph. */
            <p className="flex items-center gap-1.5 pt-1 text-meta text-brand-strong dark:text-brand-bright">
              <CircleDashed aria-hidden className="h-3.5 w-3.5 shrink-0" />
              <span>Free trial · calls free until {trialEndsAt(trial)}</span>
            </p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </section>
  );
}

/**
 * The hero's words. The empty-wallet pair says the same three facts as
 * `crm/attention.BLOCK_REMEDIES["no_credits"]` and the low-balance email: both directions
 * have stopped (D-551), callers hear an apology that says nothing about the account, and
 * adding credit restarts both. The first is on screen; the other two are behind "Why?".
 */
export const HERO_COPY = {
  stoppedTitle: "Credit ran out. All calls stopped.",
  stoppedLine: "No outgoing calls. Agents don't answer incoming ones.",
  stoppedWhy:
    "Callers hear a short apology that gives no reason and says nothing about your account. Add credit and answering, campaigns and call-backs all start again straight away.",
  dayOneTitle: "Add credit to start calling",
  dayOneLine: "Until then, agents won't call or answer.",
  dayOneWhy:
    "Callers hear a short apology that gives no reason and says nothing about your account. Add credit and answering, campaigns and call-backs start straight away.",
  lowTitle: "Credit is running low",
} as const;

const BEYOND = "Lasts over a year at this pace";

/**
 * How long the credit lasts, or `null` when the server made no projection. Only the
 * `projected` basis and the beyond-a-year cap are printed: every other basis is a reason
 * there is no number, and a reason is not worth a line on the balance.
 */
export function runwayLine(runway: Runway): string | null {
  if (runway.beyond_horizon) return BEYOND;
  if (runway.basis !== "projected" || runway.days === null) return null;
  return `About ${runway.days.toLocaleString("en-IN")} ${runway.days === 1 ? "day" : "days"} left`;
}

const NOTICE_TONES = {
  stop: { bar: "bg-danger-soft text-danger", icon: CircleAlert },
  warn: { bar: "bg-warn-soft text-warn", icon: TriangleAlert },
  neutral: { bar: "bg-surface-muted text-ink-muted", icon: CircleDashed },
} as const;

/** The state strip across the top of the card: an icon, a bold line, one short line, "Why?". */
function Notice({
  role,
  tone,
  title,
  why,
  children,
}: {
  role: "alert" | "status";
  tone: keyof typeof NOTICE_TONES;
  title: string;
  why?: string;
  children: ReactNode;
}) {
  const { bar, icon: Icon } = NOTICE_TONES[tone];
  return (
    <div role={role} className={`flex gap-3 border-b border-line px-5 py-3.5 sm:px-6 ${bar}`}>
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 text-body">
        <p className="font-semibold text-ink">{title}</p>
        <p className="mt-0.5 text-ink-muted">{children}</p>
        {why && (
          <Why className="mt-0.5">
            <p>{why}</p>
          </Why>
        )}
      </div>
    </div>
  );
}
