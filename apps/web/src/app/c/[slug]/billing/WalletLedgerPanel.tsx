"use client";

import { useState } from "react";
import { Receipt } from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatINR,
  formatIST,
  formatRupeeRate,
} from "@/components/ui";
import { takesCreditAway } from "@/lib/api/credits";
import {
  WALLET_LEDGER_LIMIT,
  useWalletLedger,
  walletReasonLabel,
  type WalletEntry,
} from "@/lib/api/wallet";
import type { Session } from "@/lib/api/client";

import { ReceiptSheet } from "./ReceiptSheet";
import { readLotSplits, type LotSplit, type TierLabels } from "./lots";

/**
 * Every movement on the wallet, newest first, with a receipt beside each payment.
 *
 * **THE DIRECTION TEST COMES FROM `lib/api/credits.ts`, NOT FROM A COPY; THE WORDS DO
 * NOT.** `takesCreditAway` is the admin console's and is realm-neutral — it decides which
 * way an entry moved the balance from the DIGITS rather than through `Number()`, and two
 * copies of it is where the two screens start pointing one entry in opposite directions.
 * The LABELS are `walletReasonLabel`, this realm's own: the admin map reads "Payment
 * recorded" and "Compensating adjustment", which is the right register for an operator
 * reconciling a bank statement and the wrong one for the person whose money it is. Both
 * maps fail VISIBLE — a reason this build has no word for prints as the server sent it,
 * because an unrecognised row on a money ledger is exactly the row worth reading.
 *
 * **DIRECTION IS NEVER ONLY A COLOUR.** Every debit carries a literal minus in its
 * formatted amount (`formatINR` keeps the leading sign) and the row's label says what the
 * entry IS. The tint is the third channel (WCAG 1.4.1), which matters most on the one
 * table in the product where a misread sign is money.
 *
 * **A DEBIT EXPANDS TO THE CREDIT IT CAME OUT OF (D-547).** Since a wallet holds several
 * purchases at several frozen rates, one `usage` row can be two or three draws at two or
 * three different per-minute prices — and the row's own rupee figure cannot show that. The
 * splits are the ledger's own (`meta.lots`, plan §2.3 invariant 5), so this expands rather
 * than derives: nothing here divides a charge by a rate or guesses which lot paid for what.
 * A row whose splits the API does not publish simply does not expand, and the quality is
 * named by the SERVER's word for it — a split whose name we do not have prints its rate and
 * its minutes without one, never the vendor's.
 *
 * **THE RECEIPT IS A PRINT VIEW, not a download.** It is the pattern
 * `c/[slug]/invoice/page.tsx` already uses — the document is real HTML with `print:` rules,
 * and the browser's own "Save as PDF" is the file. A blob download would be a second way to
 * produce a document this console already knows how to produce.
 */
export function WalletLedgerPanel({
  session,
  labels,
}: {
  session: Session;
  /** What a client calls each voice quality, from the pack card the hub already read. */
  labels: TierLabels | undefined;
}) {
  const ledger = useWalletLedger(session);
  // Which payment's receipt is open, by its reference. `null` is closed — never a
  // boolean beside a value, which is the pair that eventually disagrees.
  const [openReceipt, setOpenReceipt] = useState<string | null>(null);

  return (
    <Card title="Your credit history">
      {ledger.isLoading && <Skeleton rows={5} label="Loading your credit history" />}
      {ledger.error && (
        <ProblemNotice error={ledger.error} onRetry={() => void ledger.refetch()} />
      )}
      {ledger.data &&
        (ledger.data.entries.length === 0 ? (
          /* DAY ONE. The first thing a brand-new client sees on this screen, and it is
             designed rather than defaulted: it says what will appear here and why the
             table is empty, instead of showing headers over nothing. */
          <EmptyState
            title="Nothing has moved on your credit yet"
            hint="Payments you make and calls your agents handle will both show up here, newest first."
          />
        ) : (
          <>
            <ScrollRegion label="Credit history">
              <table className="w-full min-w-[34rem] border-collapse text-sm">
                <caption className="sr-only">
                  Your credit history, newest first — {ledger.data.entries.length} entries
                </caption>
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-muted">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      When
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      What
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      Amount
                    </th>
                    <th scope="col" className="py-2 pr-3 text-right font-medium">
                      Balance after
                    </th>
                    <th scope="col" className="py-2 font-medium">
                      <span className="sr-only">Receipt</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.data.entries.map((entry) => (
                    <LedgerRow
                      key={entry.id}
                      entry={entry}
                      labels={labels}
                      onReceipt={() => setOpenReceipt(entry.payment_ref)}
                    />
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
            {ledger.data.entries.length >= WALLET_LEDGER_LIMIT && (
              /* HONEST ABOUT THE PAGE. The list is bounded, so a client looking for an
                 entry from six months ago has to be told it is not missing — it is off
                 the end. Saying nothing is how a support ticket starts. */
              <p className="mt-3 text-xs text-ink-muted">
                Showing your {WALLET_LEDGER_LIMIT} most recent entries. Ask us if you need
                anything older.
              </p>
            )}
          </>
        ))}

      <ReceiptSheet
        session={session}
        paymentRef={openReceipt}
        onClose={() => setOpenReceipt(null)}
      />
    </Card>
  );
}

function LedgerRow({
  entry,
  labels,
  onReceipt,
}: {
  entry: WalletEntry;
  labels: TierLabels | undefined;
  onReceipt: () => void;
}) {
  // Read off the DIGITS, never `Number()` — `formatINR` keeps a leading minus and so does
  // this, which is the same rule the admin ledger row follows (hard rule 7).
  const isCredit = !takesCreditAway(entry);
  const splits = readLotSplits(entry);
  const [open, setOpen] = useState(false);
  const detailId = `${entry.id}-splits`;
  return (
    <>
      <tr className="border-b border-line/60">
        <td className="py-3 pr-3 whitespace-nowrap text-ink-muted">
          {formatIST(entry.occurred_at)}
        </td>
        <td className="py-3 pr-3 text-ink">
          {splits === undefined ? (
            walletReasonLabel(entry.reason)
          ) : (
            /* A DISCLOSURE, not a link and not a second row always open: the splits are
               the answer to "why is this figure what it is", which most readers never ask
               of most rows. `aria-expanded` + `aria-controls` are what make it one control
               and one region to a screen reader; the accessible name carries the AMOUNT
               because a column of buttons all reading "Calls" is a column of identical
               names. */
            <button
              type="button"
              onClick={() => setOpen((was) => !was)}
              aria-expanded={open}
              aria-controls={detailId}
              className="rounded-sm text-left underline decoration-dotted underline-offset-4 outline-none hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
            >
              {walletReasonLabel(entry.reason)}{" "}
              <span className="text-ink-muted">
                ({splits.length === 1 ? "1 purchase" : `${splits.length} purchases`})
              </span>
            </button>
          )}
        </td>
        <td
          className={`py-3 pr-3 text-right font-medium tabular-nums ${
            isCredit ? "text-brand-strong" : "text-ink"
          }`}
        >
          {formatINR(entry.delta_inr)}
        </td>
        <td className="py-3 pr-3 text-right tabular-nums text-ink-muted">
          {formatINR(entry.balance_after_inr)}
        </td>
        <td className="py-3 text-right">
          {entry.payment_ref !== null && (
            <button
              type="button"
              onClick={onReceipt}
              className={SECONDARY_BUTTON_SM}
              /* The accessible name carries the AMOUNT: a column of buttons all reading
                 "Receipt" is a column of identically-named controls in a screen reader's
                 list, and the one thing that tells them apart is the row's figure. */
              aria-label={`Receipt for the payment of ${formatINR(entry.delta_inr)}`}
            >
              <Receipt className="mr-1 inline h-3.5 w-3.5" aria-hidden />
              Receipt
            </button>
          )}
        </td>
      </tr>
      {splits !== undefined && (
        /* The region EXISTS whether or not it is open, and is hidden with `hidden` rather
           than by not rendering it: `aria-controls` has to point at an element that is in
           the document, or a screen reader announces a control that governs nothing. */
        <tr id={detailId} hidden={!open} className="border-b border-line/60 bg-app">
          <td colSpan={5} className="px-3 py-3">
            <ul className="space-y-1 text-xs text-ink-muted">
              {splits.map((split, index) => (
                <li key={`${split.lot_id}-${index}`} className="tabular-nums">
                  {splitSentence(split, labels)}
                </li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * One split, in words: what came out of which purchase, and at what price.
 *
 * The two kinds are different sentences because they are different things (plan ADDENDUM 2
 * §2.1). A `call` split bought MINUTES at the rate frozen on that purchase; an `ai_assist`
 * split bought rupees of help from the dashboard assistant, and carries no rate, no minutes
 * and no voice at all — so nothing here invents a "—" for a field that is absent by design.
 *
 * The quality is named only when the server told us its name: an unnamed rate is still a
 * true and useful sentence, and the vendor's word is never a fallback.
 */
function splitSentence(split: LotSplit, labels: TierLabels | undefined): string {
  if (split.kind === "ai_assist") {
    return `${formatINR(split.credits)} of extra AI help, from credit bought earlier`;
  }
  const quality = labels ? ` on ${labels[split.voice_tier]}` : "";
  return `${formatINR(split.credits)} — ${split.minutes} min at ${formatRupeeRate(
    split.inr_per_min,
  )}/min${quality}, from credit bought at that rate`;
}
