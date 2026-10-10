"use client";

import { formatINR, formatIST, formatRupeeRate } from "@/components/ui";
import type { RestatementResult } from "@/lib/api/credits";
import type { CreditLot } from "@/lib/api/creditLots";

/**
 * One lot, as the rows of the wallet's Lots view and the receipts of the writes that open
 * or restate one.
 *
 * Named by RUNG (the label the client reads), not by vendor. Which company speaks a rung
 * depends on the engine (D-687) and can change under a lot while its frozen rate does not:
 * the rate is the RUNG's, never the vendor's. An operator reconciling an invoice reads the
 * vendor on the model-pricing panel.
 */
export function lotRates(lot: CreditLot): string {
  return `${lot.clear_label} ${formatRupeeRate(lot.clear_inr_per_min)}/min · ${lot.studio_label} ${formatRupeeRate(lot.studio_inr_per_min)}/min`;
}

/**
 * THE LOT A WRITE OPENED, on the receipt for that write.
 *
 * Rendered from the write's OWN answer, never from the wallet re-read: the point is to name
 * the object this click created, and a list read a moment later cannot say which of five
 * lots that was. `null` is the wire's own answer for a write that restated an existing lot
 * rather than opening one, so nothing is claimed.
 */
export function LotReceipt({ lot, lead }: { lot: CreditLot | null; lead: string }) {
  if (lot === null) return null;
  return (
    <p className="mt-2 text-meta">
      {lead} <span className="font-mono">{lot.lot_id}</span> — {formatINR(lot.credits_total)} at
      {lot.clear_label} {formatRupeeRate(lot.clear_inr_per_min)}/min and {lot.studio_label}{" "}
      {formatRupeeRate(lot.studio_inr_per_min)}/min. Those rates are frozen on it: a later change to the rate
      card does not move them.
    </p>
  );
}

/**
 * WHAT A RESTATEMENT DID TO THE LOT — totals moved, rates untouched, and the shortfall.
 *
 * A restatement is the one write on this screen that touches an existing lot, so it is the
 * one an operator would reasonably fear had re-priced a client's credit; saying it did not,
 * at the moment it did not, is what makes the promise checkable rather than merely true.
 */
export function LotRestatementReceipt({ result }: { result: RestatementResult }) {
  const lot = result.lot;
  if (lot === null) return null;
  const shortfall_inr = result.lot_shortfall_inr;
  return (
    <>
      <p className="mt-2 text-meta">
        Lot <span className="font-mono">{lot.lot_id}</span> now holds{" "}
        {formatINR(lot.credits_remaining)} of {formatINR(lot.credits_total)}. Its rates are
        unchanged at {lot.clear_label} {formatRupeeRate(lot.clear_inr_per_min)}/min and{" "}
        {lot.studio_label} {formatRupeeRate(lot.studio_inr_per_min)}/min —{" "}
        <span className="font-semibold">a restatement moves totals, never rates.</span>
      </p>
      {shortfall_inr && (
        <p className="mt-2 text-meta">
          {formatINR(shortfall_inr)} of the correction was more than the lot had left, so it
          became overdraft on the wallet. The next payment repays that before it opens a new
          lot.
        </p>
      )}
    </>
  );
}

/** The lot's provenance line: when it opened, from what, and any operator re-pricing. */
export function LotOrigin({ lot }: { lot: CreditLot }) {
  return (
    <>
      opened {formatIST(lot.opened_at)} · {lot.source}
      {lot.pack_id ? ` · ${lot.pack_id}` : ""}
      {lot.override_of_pack_id ? (
        <>
          {" "}
          · sold at <span className="font-mono">{lot.override_of_pack_id}</span>&apos;s rates by an
          operator — recorded in the audit log
        </>
      ) : null}
    </>
  );
}
