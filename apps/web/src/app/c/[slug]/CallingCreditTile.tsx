"use client";

import Link from "next/link";

import { Card, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatINR } from "@/components/ui";
import { Metric } from "@/components/console/metric";
import {
  activeTrial,
  trialEndsAt,
  trialTimeLeft,
  minutesLeftPhrase,
  useWallet,
  walletState,
  type WalletTrial,
} from "@/lib/api/wallet";

import { HOME } from "./setup/_ui/copy";

/**
 * How much calling credit is left, and what that means today.
 *
 * **THE STATE IS NEVER CARRIED BY THE FIGURE ALONE.** ₹0.00 means nothing to somebody
 * skimming a dashboard on a phone; "outgoing calls have stopped" does. So each state has
 * a SENTENCE under the number, and colour only ever repeats what that sentence says
 * (WCAG 1.4.1) — which matters most on
 * the one tile where a misread is a business day of missed calls.
 *
 * **THE EMPTY STATE'S SENTENCE CARRIES THE REASSURANCE**, in the same order the wallet's
 * own screen uses: what still works, then what stopped. A client who reads "your credit
 * has run out" on a dashboard concludes their phone has stopped being answered, and
 * nothing on the tile is big enough to correct that afterwards.
 *
 * **AN INVOICED ACCOUNT GETS NO TILE.** `prepaid: false` is a tenant with nothing to top
 * up, not one whose balance is zero; a ₹0.00 here would be the same false alarm the
 * credit screen refuses to raise. It is a fact the read RETURNED, so nothing is being
 * hidden on our own ignorance — the loading and failed arms above it say so themselves.
 */
export function CallingCreditTile({
  wallet,
  href,
}: {
  wallet: ReturnType<typeof useWallet>;
  href: string;
}) {
  if (wallet.isLoading) {
    return (
      <Card density="compact" title="Calling credit" className="rounded-none border-0 shadow-none">
        <Skeleton rows={2} label="Loading your calling credit" />
      </Card>
    );
  }
  // `|| !wallet.data` for the PAUSED query (offline): `isLoading` is false, `error` is
  // null and `data` is undefined, and a tile that fell through all three would print
  // "—" to a client whose wallet may be empty (§52).
  if (wallet.error || !wallet.data) {
    return (
      <Card density="compact" title="Calling credit" className="rounded-none border-0 shadow-none">
        <ProblemNotice
          error={wallet.error ?? new Error("Your calling credit did not load.")}
          onRetry={() => void wallet.refetch()}
        />
      </Card>
    );
  }

  const state = walletState(wallet.data);
  if (state === "not-prepaid") return null;
  const trial = activeTrial(wallet.data);

  return (
    <Metric
      className="py-4"
      label="Calling credit left"
      value={minutesLeftPhrase(wallet.data) ?? formatINR(wallet.data.balance_inr)}
      flashValue={wallet.data.balance_inr}
      tone={
        state === "stopped"
          ? "danger"
          : state === "low" || (trial !== null && trialTimeLeft(trial).lastDay)
            ? "warn"
            : "default"
      }
      hint={
        <>
        {minutesLeftPhrase(wallet.data) !== null ? (
          <span className="block text-body text-ink-muted">{formatINR(wallet.data.balance_inr)} in your account</span>
        ) : null}
        {trial !== null && !trialTimeLeft(trial).lastDay ? (
          // A trial with days to go asks nothing: its line is a status, quiet, still a way in.
          <Link href={href} className="underline decoration-ink/30 underline-offset-2 hover:text-ink touch:inline-flex touch:min-h-11 touch:items-center">
            {trialHint(trial)}
          </Link>
        ) : (
          <Link href={href} className={`${state === "stopped" ? PRIMARY_BUTTON_SM : SECONDARY_BUTTON_SM} mt-2`}>
            {trial !== null
              ? trialHint(trial)
              : state === "stopped"
                ? HOME.creditStoppedHint
                : state === "low"
                  ? HOME.creditLowHint
                  : HOME.creditOkHint}
          </Link>
        )}
        </>
      }
    />
  );
}

/**
 * During a trial the balance limits nothing (D-536), so the low-credit warning would be
 * false. The tile says why a ₹0.00 wallet is still calling, and on the last day asks for
 * the top-up that keeps it calling afterwards.
 */
function trialHint(trial: WalletTrial): string {
  const left = trialTimeLeft(trial);
  // The last day counts down in hours ("5 hours left"), which a date would hide.
  return left.lastDay ? HOME.trialLastDay(left.text) : HOME.trialFree(trialEndsAt(trial));
}
