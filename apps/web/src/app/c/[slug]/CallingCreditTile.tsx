"use client";

import Link from "next/link";
import { Wallet } from "lucide-react";

import {
  Card,
  ProblemNotice,
  Skeleton,
  StatTile,
  formatINR,
} from "@/components/ui";
import { useWallet, walletState } from "@/lib/api/wallet";

/**
 * How much calling credit is left, and what that means today.
 *
 * **THE STATE IS NEVER CARRIED BY THE FIGURE ALONE.** ₹0.00 means nothing to somebody
 * skimming a dashboard on a phone; "outgoing calls have stopped" does. So each state has
 * a SENTENCE under the number, the empty one has an icon that is not the healthy one's,
 * and none of the three is distinguished by colour (WCAG 1.4.1) — which matters most on
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
      <Card title="Calling credit" bodyClassName="p-4 sm:p-5">
        <Skeleton rows={2} label="Loading your calling credit" />
      </Card>
    );
  }
  // `|| !wallet.data` for the PAUSED query (offline): `isLoading` is false, `error` is
  // null and `data` is undefined, and a tile that fell through all three would print
  // "—" to a client whose wallet may be empty (§52).
  if (wallet.error || !wallet.data) {
    return (
      <Card title="Calling credit" bodyClassName="p-4 sm:p-5">
        <ProblemNotice
          error={wallet.error ?? new Error("Your calling credit did not load.")}
          onRetry={() => void wallet.refetch()}
        />
      </Card>
    );
  }

  const state = walletState(wallet.data);
  if (state === "not-prepaid") return null;

  return (
    <StatTile
      label="Calling credit left"
      value={formatINR(wallet.data.balance_inr)}
      icon={<Wallet className="h-5 w-5" />}
      tone={state === "stopped" ? "strong" : "soft"}
      hint={
        <Link href={href} className="underline hover:text-ink">
          {state === "stopped"
            ? "Calls have stopped, outgoing and incoming. Add credit to start both again"
            : state === "low"
              ? "Running low — top up before outgoing calls stop"
              : "Add credit or see where it went"}
        </Link>
      }
    />
  );
}
