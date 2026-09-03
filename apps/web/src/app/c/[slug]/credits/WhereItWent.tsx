"use client";

import { BadgeIndianRupee, PhoneCall, Sparkles, SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";

import { Card, EmptyState, formatINR, hasNonZeroDigit } from "@/components/ui";
import type { Drawdown } from "@/lib/api/wallet";

/**
 * Where the money went — so a spike is explained on the same screen it appears on.
 *
 * **THERE ARE EXACTLY THREE OUTGOING ROWS AND MESSAGING IS NOT ONE.** Nothing on this
 * platform debits the wallet for a WhatsApp message or an SMS, so a "Messaging ₹0.00" row
 * would be a category invented to look complete — and a client who saw it would reasonably
 * conclude they are being charged for messages. The screen says which things draw the
 * wallet down instead of listing one that does not.
 *
 * **A ZERO ROW IS HIDDEN, and the total is not.** An "AI help ₹0.00" line invites a
 * question about nothing; the same rule the usage panel's overage rows follow. The total
 * always shows, because "you spent nothing in the last 30 days" is itself an answer.
 *
 * **NO ARITHMETIC HAPPENS HERE.** `spent_inr` is summed in SQL over `NUMERIC` from the same
 * pass that produced the buckets (`billing/wallet.py`), so the total is by construction the
 * sum of the rows beneath it. A browser subtracting rupee strings to find it would be a
 * second implementation of a bill, in the one language with no exact decimal type
 * (hard rule 7).
 */
export function WhereItWent({
  drawdown,
  windowDays,
}: {
  drawdown: Drawdown;
  windowDays: number;
}) {
  const rows: { key: string; label: string; value: string; icon: ReactNode; hint: string }[] = [
    {
      key: "calls",
      label: "Calls",
      value: drawdown.calls_inr,
      icon: <PhoneCall className="h-4 w-4" aria-hidden />,
      hint: "Outgoing and incoming calls your agents handled",
    },
    {
      key: "ai",
      label: "Extra AI help",
      value: drawdown.ai_assist_inr,
      icon: <Sparkles className="h-4 w-4" aria-hidden />,
      hint: "Extra dashboard AI you chose to buy",
    },
    {
      key: "adjustments",
      label: "Corrections",
      value: drawdown.adjustments_inr,
      icon: <SlidersHorizontal className="h-4 w-4" aria-hidden />,
      hint: "Credit we took back to correct an earlier mistake",
    },
  ].filter((row) => hasNonZeroDigit(row.value));

  const added = hasNonZeroDigit(drawdown.added_inr);
  const refunded = hasNonZeroDigit(drawdown.refunded_inr);

  return (
    <Card title={`Where your credit went in the last ${windowDays} days`}>
      {rows.length === 0 && !added && !refunded ? (
        <EmptyState
          title="Nothing has moved on your credit yet"
          hint="Once your agents start taking and making calls, this is where you will see what each part costs."
        />
      ) : (
        <dl className="space-y-3 text-sm">
          {rows.map((row) => (
            <div key={row.key} className="flex items-start justify-between gap-4">
              <dt className="flex min-w-0 items-start gap-2 text-ink-muted">
                <span className="mt-0.5 text-brand" aria-hidden>
                  {row.icon}
                </span>
                <span className="min-w-0">
                  <span className="block text-ink">{row.label}</span>
                  <span className="block text-xs text-ink-faint">{row.hint}</span>
                </span>
              </dt>
              <dd className="shrink-0 tabular-nums text-ink">{formatINR(row.value)}</dd>
            </div>
          ))}
          <div className="flex items-start justify-between gap-4 border-t border-line pt-3">
            <dt className="flex items-center gap-2 font-semibold text-ink">
              <BadgeIndianRupee className="h-4 w-4 text-brand" aria-hidden />
              Spent in total
            </dt>
            <dd className="shrink-0 font-semibold tabular-nums text-ink">
              {formatINR(drawdown.spent_inr)}
            </dd>
          </div>
          {/* Money that came IN, kept below the line and named for its direction. A
              positive correction lands in "added" rather than in "corrections", because
              that is where a client looks for money appearing. */}
          {added && (
            <div className="flex items-start justify-between gap-4">
              <dt className="text-ink-muted">Credit added</dt>
              <dd className="shrink-0 tabular-nums text-ink-muted">
                {formatINR(drawdown.added_inr)}
              </dd>
            </div>
          )}
          {refunded && (
            <div className="flex items-start justify-between gap-4">
              <dt className="text-ink-muted">Refunded to you</dt>
              <dd className="shrink-0 tabular-nums text-ink-muted">
                {formatINR(drawdown.refunded_inr)}
              </dd>
            </div>
          )}
        </dl>
      )}
    </Card>
  );
}
