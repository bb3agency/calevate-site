"use client";

import { useRef } from "react";
import { Printer, X } from "lucide-react";

import { ReceiptDocument } from "@/components/receiptDocument";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { useFocusTrap } from "@/lib/focusTrap";
import { usePaymentReceipt } from "@/lib/api/wallet";
import type { Session } from "@/lib/api/client";

/**
 * The dialog that holds one payment's receipt — chrome only.
 *
 * The DOCUMENT is `components/receiptDocument.tsx`, beside the monthly statement's, and
 * the split is the same one `c/[slug]/invoice/page.tsx` makes: the sheet prints on white
 * paper in both themes and argues for its own colours where it lives, while everything
 * around it is console chrome and is `print:hidden` here. So what comes out of the printer
 * is the receipt and nothing else.
 *
 * **PRINT IS THE DOWNLOAD.** `window.print()` against a `print:`-styled document is what
 * this console already does for the monthly statement, and the browser's own "Save as PDF"
 * is the file. A blob download would be a second way to produce a document we already
 * produce — and one that several browsers refuse anyway.
 *
 * **It is a real dialog**: labelled, focus-trapped, Escape closes, and focus returns to
 * the row's button when it does. `useFocusTrap` owns all three — a second Escape listener
 * beside it is exactly the partial copy that hook was extracted to end.
 *
 * **The three states are designed, not defaulted** (§52): a skeleton while the document is
 * being fetched, the server's own refusal if it cannot be, and the document when it is.
 * None of them is a blank sheet, which on a money document reads as "there is no receipt".
 */
export function ReceiptSheet({
  session,
  paymentRef,
  onClose,
}: {
  session: Session;
  paymentRef: string | null;
  onClose: () => void;
}) {
  const receipt = usePaymentReceipt(session, paymentRef);
  const panel = useRef<HTMLDivElement>(null);
  // "container": this is a document to be READ before a decision, so a screen reader
  // should announce the receipt rather than a button — the same choice the money dialog
  // makes, and for the same reason (`lib/focusTrap.ts`).
  useFocusTrap(panel, paymentRef !== null, onClose, "container");

  if (paymentRef === null) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Payment receipt"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-6 print:static print:bg-transparent print:p-0"
    >
      <div
        ref={panel}
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-card bg-surface p-4 shadow-xl sm:rounded-card sm:p-6 print:max-h-none print:overflow-visible print:rounded-none print:bg-transparent print:p-0 print:shadow-none"
      >
        <div className="flex items-center justify-between gap-3 print:hidden">
          <p className="text-[17px] font-semibold text-ink">Payment receipt</p>
          <button
            type="button"
            onClick={onClose}
            className={SECONDARY_BUTTON}
            aria-label="Close the receipt"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div className="mt-4">
          {receipt.isLoading && <Skeleton rows={4} label="Loading your receipt" />}
          {receipt.error && (
            <ProblemNotice error={receipt.error} onRetry={() => void receipt.refetch()} />
          )}
          {receipt.data && (
            <>
              <ReceiptDocument data={receipt.data} />
              <div className="mt-4 flex justify-end print:hidden">
                <button type="button" onClick={() => window.print()} className={PRIMARY_BUTTON}>
                  <Printer className="mr-1.5 inline h-4 w-4" aria-hidden />
                  Print or save as PDF
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
