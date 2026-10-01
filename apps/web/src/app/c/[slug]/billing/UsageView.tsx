"use client";

import type { CreditPacks } from "@/lib/api/billing";
import type { Session } from "@/lib/api/client";
import type { Wallet } from "@/lib/api/wallet";

import { SpendOverTime } from "./SpendChart";
import { UsageTab } from "./UsageTab";
import { WhatCallsCost } from "./WhatCallsCost";
import { WhereItWent } from "./WhereItWent";
import type { TierLabels } from "./lots";

/**
 * The Usage view: spending over time, this month's charges and limit, then — for a
 * prepaid wallet — where the credit went and what calls cost.
 *
 * The wallet panels render only for a PREPAID account: an invoiced one has no credit to
 * draw down and no packs to price, and a rate card on its screen would be a price for
 * something it cannot buy.
 */
export function UsageView({
  session,
  slug,
  month,
  onMonthChange,
  billingAllowed,
  wallet,
  card,
  labels,
}: {
  session: Session;
  slug: string;
  month: string;
  onMonthChange: (month: string) => void;
  /** `billing:read`, or `null` while `/v1/me` is in flight. */
  billingAllowed: boolean | null;
  wallet: Wallet | undefined;
  card: CreditPacks | undefined;
  labels: TierLabels | undefined;
}) {
  return (
    <div className="space-y-6">
      {/* Owner-only. A refused session gets one sentence, from `UsageTab` below, not two. */}
      {billingAllowed !== false && (
        <SpendOverTime session={session} allowed={billingAllowed} />
      )}
      <UsageTab
        session={session}
        slug={slug}
        month={month}
        onMonthChange={onMonthChange}
        refused={billingAllowed === false}
      />
      {wallet?.prepaid && (
        <>
          <WhereItWent drawdown={wallet.drawdown} windowDays={wallet.runway.window_days} />
          <WhatCallsCost card={card} labels={labels} />
        </>
      )}
    </div>
  );
}
