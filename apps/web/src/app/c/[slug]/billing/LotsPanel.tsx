"use client";

import { Layers } from "lucide-react";

import { Card, NOTICE_TONES, formatINR, formatIST, formatRupeeRate } from "@/components/ui";

import { formatWhole, isVoiceTier, lotRate, type WalletLots } from "./lots";

/**
 * THE LOT QUEUE — what credit is left, at which rates, in the order it will be spent.
 *
 * ## The sentence this panel exists to make readable
 *
 * *"3,200 credits at ₹4.70 / ₹6.50, then 2,000 at ₹5.00 / ₹8.00."* Under D-547 a balance
 * is no longer one number with one price: each purchase freezes the two per-minute rates it
 * was sold at, credit is spent oldest purchase first, and a wallet can therefore hold
 * several rates at once. A screen showing only the rupee total would be arithmetically
 * right and commercially blind — a client who bought a ₹15,000 pack cannot see the cheaper
 * minute they paid for, and one who tops up small cannot see that their good rate is about
 * to run out.
 *
 * ## Oldest first, and the order is the fact
 *
 * The rows are in spend order (the server sends them that way, and `consume` walks the same
 * queue), so the first row is what the NEXT call is charged at. That is why it carries the
 * "spent first" marker rather than the newest purchase carrying a "latest" one: what a
 * client needs to know is which price is live, not which payment was most recent.
 *
 * ## Names, money and the two absences
 *
 * The column headings are the SERVER's names for the two qualities and the panel does not
 * render without them (`lots.ts`) — no client-facing surface names a vendor as a tier.
 *
 * ⚠ **THE HEADINGS AND THE CELLS USED TO COME FROM TWO DIFFERENT ARRAYS.** The `<th>`s
 * iterated `lots.tiers` — the server's order — and the `<td>`s iterated the browser
 * constant `VOICE_TIERS`, so the table was correct only while two independently declared
 * orderings happened to agree. The first person to reorder the server's tiers, or add a
 * third, would have put a Studio rate under a Clear heading with nothing failing anywhere:
 * a wrong per-minute price, on the screen a client checks their bill against, delivered
 * silently. One array drives both now, and each cell picks its rate BY THE HEADING'S OWN
 * `provider` through `lotRate`. A quality the server names but this browser cannot price
 * gets a heading and an EMPTY cell — an absent figure renders as absent (D-458), never as
 * the other voice's rate. `tests/credits.test.tsx` feeds a reversed tier order.
 *
 * Every
 * figure is an exact decimal string formatted from its digits: `formatINR` for credits (a
 * credit is ₹1) and `formatRupeeRate` for the rates, which keeps the server's full
 * NUMERIC(12,4) precision because ₹4.7000/min rounded to two places stops multiplying out.
 *
 * Two states are deliberately not rendered as an empty table. A wallet with no open lot and
 * nothing owed renders NOTHING at all — the hero above already says the balance is empty,
 * and a table of headings over no rows says it a second time in a worse register. An
 * OVERDRAWN wallet renders the notice and no table, because there is no credit left to
 * price: what a client needs there is what they owe and what clears it.
 */
export function LotsPanel({ lots }: { lots: WalletLots }) {
  const owed = /[1-9]/.test(lots.overdraft_inr);
  if (lots.lots.length === 0 && !owed) return null;

  return (
    <Card title="Your credit and what it costs a minute">
      {owed && (
        <p role="status" className={`mb-3 rounded-card border p-3 text-sm ${NOTICE_TONES.warn}`}>
          Your calls have run {formatINR(lots.overdraft_inr)} past the credit on the account.
          Your next top-up clears that first, and whatever is left opens as new credit at
          that purchase&rsquo;s rates.
        </p>
      )}

      {lots.lots.length > 0 && (
        <>
          <p className="text-sm text-ink-muted">
            Each purchase keeps the per-minute rates it was bought at, and your calls are
            charged against the oldest one first.
          </p>
          <table className="mt-3 w-full border-collapse text-sm">
            <caption className="sr-only">
              Your credit, in the order it will be spent — {lots.lots.length}{" "}
              {lots.lots.length === 1 ? "purchase" : "purchases"}
            </caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-muted">
                <th scope="col" className="py-2 pr-3 font-medium">
                  Credit left
                </th>
                {lots.tiers.map((tier) => (
                  <th key={tier.provider} scope="col" className="py-2 pr-3 text-right font-medium">
                    {tier.label}
                  </th>
                ))}
                <th scope="col" className="py-2 text-right font-medium">
                  Bought
                </th>
              </tr>
            </thead>
            <tbody>
              {lots.lots.map((lot, index) => (
                <tr key={lot.lot_id} className="border-b border-line/60">
                  <th scope="row" className="py-3 pr-3 text-left font-medium tabular-nums text-ink">
                    {formatINR(lot.credits_remaining)}
                    {index === 0 && (
                      <span className="ml-2 rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-semibold text-brand-strong">
                        Spent first
                      </span>
                    )}
                  </th>
                  {lots.tiers.map((tier) => (
                    <td
                      key={tier.provider}
                      className="py-3 pr-3 text-right tabular-nums text-ink-muted"
                    >
                      {isVoiceTier(tier.provider)
                        ? `${formatRupeeRate(lotRate(lot, tier.provider))}/min`
                        : null}
                    </td>
                  ))}
                  <td className="py-3 text-right text-ink-muted">{formatIST(lot.opened_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Card>
  );
}

/**
 * The runway, as a figure per voice quality (plan §0 Q7) — for a wallet that HAS credit.
 *
 * ⚠ **A DAY-ONE WALLET USED TO READ "about 0 minutes on Clear", BESIDE A BANNER THAT HAD
 * ALREADY SAID THE ACCOUNT HAS NO CREDIT YET.** Two zeroes for one fact, and the second one
 * in the unit a client plans in — which is how a brand-new account's first screen came to
 * report its own emptiness twice. The decision: **no open lots, no runway lines.** This
 * component answers "how long does what you have last", and a wallet with nothing in it has
 * no answer to give; the hero above already says so once, in the register that belongs to
 * it (day one is not an outage). The same applies to a spent-out or overdrawn wallet, where
 * every lot is closed and there is no rate left to run down.
 *
 * The condition is the LOTS, not the minutes being zero: a wallet with credit whose runway
 * the server declines to price sends `null`, which is filtered below and is a different
 * fact — "we cannot say" is not "you have none".
 *
 * One balance can no longer buy one number of minutes: the wallet holds several lots at
 * several rates and the answer depends on which voice the agent that takes the call speaks
 * with. The server sums it lot by lot at each lot's own rate — the same walk the debit
 * makes — so nothing here divides anything, which is exactly what the old
 * `minutes_left` (one balance ÷ one list rate) did and why it is not rendered any more.
 *
 * A quality the server declines to answer for prints nothing rather than a zero.
 */
export function TierRunwayLines({ lots }: { lots: WalletLots }) {
  if (lots.lots.length === 0) return null;
  const priced = lots.tiers.filter((tier) => tier.minutes_left !== null);
  if (priced.length === 0) return null;
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
      <Layers className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {priced.map((tier) => (
        <span key={tier.provider}>
          about{" "}
          <strong className="font-semibold tabular-nums text-ink">
            {formatWhole(tier.minutes_left ?? "")} minutes
          </strong>{" "}
          on {tier.label}
        </span>
      ))}
    </p>
  );
}
