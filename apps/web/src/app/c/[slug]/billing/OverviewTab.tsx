"use client";

import type { Wallet } from "@/lib/api/wallet";
import type { CreditPacks } from "@/lib/api/billing";
import type { Session } from "@/lib/api/client";

import { LotsPanel } from "./LotsPanel";
import { UnfinishedPayments } from "./UnfinishedPayments";
import { WalletHero } from "./WalletHero";
import { WhatCallsCost } from "./WhatCallsCost";
import { WhereItWent } from "./WhereItWent";
import type { TierLabels, WalletLots } from "./lots";

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
 * 2. **The credit itself, purchase by purchase** (`LotsPanel`). Since D-547 a balance is
 *    several purchases at several frozen rates, spent oldest first, so "what have I got"
 *    and "what does a minute cost" are one question with a list for an answer.
 * 3. **Unfinished payments**, when there are any, before anything that would start
 *    another one.
 * 4. **Where it went** over the same window the runway was measured on, so a spike is
 *    explained on the screen it appears on.
 * 5. **What calls cost** — the rules the balance goes down by, stated plainly and with
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
  lots,
  card,
  labels,
}: {
  session: Session;
  wallet: Wallet;
  /** Has anything ever moved on this wallet? `null` while the history is in flight. */
  funded: boolean | null;
  /** This wallet's open lots and per-quality runway, when the server can answer for them. */
  lots: WalletLots | undefined;
  /** The pack card, or `undefined` when this session may not read prices. */
  card: CreditPacks | undefined;
  /** What a client calls each voice quality, from that card. */
  labels: TierLabels | undefined;
}) {
  return (
    <div className="space-y-5">
      <WalletHero wallet={wallet} funded={funded} lots={lots} />
      {lots && <LotsPanel lots={lots} />}
      <UnfinishedPayments session={session} />
      <WhereItWent drawdown={wallet.drawdown} windowDays={wallet.runway.window_days} />
      <WhatCallsCost card={card} labels={labels} />
    </div>
  );
}
