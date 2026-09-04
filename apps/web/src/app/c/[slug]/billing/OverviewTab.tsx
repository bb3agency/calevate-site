"use client";

import type { Wallet } from "@/lib/api/wallet";
import type { Session } from "@/lib/api/client";

import { UnfinishedPayments } from "./UnfinishedPayments";
import { WalletHero } from "./WalletHero";
import { WhatCallsCost } from "./WhatCallsCost";
import { WhereItWent } from "./WhereItWent";

/**
 * OVERVIEW — the tab that answers "what am I paying?" without being asked twice.
 *
 * The landing tab of the billing hub (D-525), and the reason the hub exists: that question
 * used to be split across four sidebar entries, and a client had to know which of them held
 * their answer before they could ask it.
 *
 * The order IS the argument, and it is the order the old wallet screen settled on:
 *
 * 1. **Balance and runway, as a pair and at the same weight.** A rupee figure means
 *    nothing to a clinic owner — ₹3,400 is a fortnight or an afternoon depending on how
 *    much they call — and the number they plan around is the days. `WalletHero` also
 *    carries the talk time the balance buys, which is the same fact in the unit a person
 *    running a phone line thinks in.
 * 2. **Unfinished payments**, when there are any, before anything that would start
 *    another one.
 * 3. **Where it went** over the same window the runway was measured on, so a spike is
 *    explained on the screen it appears on.
 * 4. **What calls cost** — the rules the balance goes down by, stated plainly and with
 *    the GST position said out loud. It is the same component the Credits tab renders.
 *
 * ## It computes nothing
 *
 * Every rupee figure is the server's, formatted from its digits and never parsed (hard
 * rule 7 reaches the browser); the runway, the burn rate and the drawdown buckets are all
 * `billing/wallet.py`'s arithmetic. And it re-derives no verdict: "outgoing calls have
 * stopped" is `outbound_stopped`, the dial gate's own answer, not a balance comparison
 * made here.
 *
 * ## Day one and an empty wallet are the same number and different news
 *
 * `outbound_stopped` is identically true for an account that has spent everything and for
 * one that has never had anything, and those are different sentences. `funded` — has
 * anything ever moved on this wallet — is what tells them apart, and it comes from the
 * ledger the hub already reads. `null` while it is in flight, never `false`: an unknown is
 * not an answer (§52).
 */
export function OverviewTab({
  session,
  wallet,
  funded,
  listRate,
}: {
  session: Session;
  wallet: Wallet;
  /** Has anything ever moved on this wallet? `null` while the history is in flight. */
  funded: boolean | null;
  /** The server's `list_rate_inr_per_min`, or `null` when this session may not read it. */
  listRate: string | null;
}) {
  return (
    <div className="space-y-5">
      <WalletHero wallet={wallet} funded={funded} />
      <UnfinishedPayments session={session} />
      <WhereItWent drawdown={wallet.drawdown} windowDays={wallet.runway.window_days} />
      <WhatCallsCost listRate={listRate} />
    </div>
  );
}
