"use client";

import { Card, RestrictionNote } from "@/components/ui";
import type { CreditPacks } from "@/lib/api/billing";
import type { Session } from "@/lib/api/client";

import { LotsPanel } from "./LotsPanel";
import { TopUp } from "./TopUp";
import { UnfinishedPayments } from "./UnfinishedPayments";
import { WhatCallsCost } from "./WhatCallsCost";
import type { TierLabels, WalletLots } from "./lots";

/**
 * CREDITS — the purchase surface: what a pack costs, what it buys, and the button.
 *
 * The Credits tab of the billing hub (D-525). The order on it is the argument:
 *
 * 1. **Unfinished payments**, when there are any — ABOVE the control that would start
 *    another (UX-DOCTRINE §4). A client who has just paid must not have to look past a
 *    rate card to find out whether it worked, and the failure mode of getting this wrong
 *    is two orders for one top-up.
 * 2. **The credit already on the account, purchase by purchase** (`LotsPanel`), because
 *    what a new pack is worth depends on what is already queued in front of it: credit is
 *    spent oldest first, so a client buying the ₹15,000 rates today still spends last
 *    month's ₹5.00 minutes before they reach them. The same component the Overview tab
 *    renders; the copy exists once.
 * 3. **The rate card and the button** (`TopUp`): what you pay, the credits, and the two
 *    per-minute rates with the talk time each buys. Every figure is the server's.
 * 4. **What calls cost** — the rules the balance goes down by, on the same tab a client
 *    buys from. It is the same component the Overview tab renders; the copy exists once.
 *
 * ## The rate card renders even when the buttons cannot
 *
 * `TopUp` keeps that branch: on a deployment with no payment provider configured it drops
 * the BUTTONS and keeps the PRICES, with the bank-transfer path named. A client cannot
 * decide what to transfer without knowing what a pack buys, and this screen used to
 * return before the table on exactly the deployments that needed it most.
 *
 * ## Seeing is not buying
 *
 * The tab reads on the hub's `wallet:read`. The pack catalogue and the payment-capability
 * hint are `billing:read` (`payment_routes.py`), which `staff` does not hold, so a staff
 * session is told that in a sentence rather than being shown a red refusal where the rate
 * card should be. BUYING is `org:manage` and `TopUp` gates itself on that through
 * `useWriteAccess`, which also refuses an impersonating operator (D-22): support can see a
 * client's wallet and can never spend from it.
 */
export function CreditsTab({
  session,
  lots,
  card,
  labels,
  billingRefused,
}: {
  session: Session;
  /** This wallet's open lots, when the server can answer for them. */
  lots: WalletLots | undefined;
  /** The pack card, or `undefined` when this session may not read prices. */
  card: CreditPacks | undefined;
  /** What a client calls each voice quality, from that card. */
  labels: TierLabels | undefined;
  /** True when this session does NOT hold `billing:read`. */
  billingRefused: boolean;
}) {
  return (
    <div className="space-y-5">
      <UnfinishedPayments session={session} />

      {lots && <LotsPanel lots={lots} />}

      <Card title="Add credit">
        {billingRefused ? (
          <RestrictionNote reason="Prices and payment are limited to the account owner. Ask them to top up the account, or to give you owner access." />
        ) : (
          <TopUp session={session} />
        )}
      </Card>

      <WhatCallsCost card={card} labels={labels} />
    </div>
  );
}
