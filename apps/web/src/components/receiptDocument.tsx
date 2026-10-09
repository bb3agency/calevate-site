"use client";

// Layout adapted from Invoicely (https://github.com/legions-developer/invoicely), commit
// 820d3c51604faa10d44126e019c1fad51b54d96f, apps/web/src/components/pdf/default.tsx.
// MIT licence, Copyright (c) 2025 Invoicely. Full notice: ./billing/LICENSE.

import {
  DocumentSheet,
  Masthead,
  MetaRows,
  PartyCard,
  PartyDetail,
  TotalsBlock,
} from "@/components/billing/documentParts";
import { formatINR, formatIST } from "@/components/ui";
import type { PaymentReceipt } from "@/lib/api/wallet";

/**
 * THE receipt sheet for one credit payment — a document, not a panel.
 *
 * The paper is white with slate ink for `invoiceDocument.tsx`'s reason (a themed sheet
 * prints blank in dark mode). `tests/contrast.test.ts` scopes its grey-literal ban to
 * `src/app/` so a document under `src/components/` can argue this where it lives; the
 * chrome around the sheet belongs to the drawer and is `print:hidden` there.
 *
 * Saving it as a PDF is the browser's print-to-PDF of this markup, through
 * `lib/printDocument.ts` from `ReceiptSheet.tsx`; `billing/documentParts.tsx` says why that
 * was kept over a PDF library.
 *
 * ## Why it is not called a tax invoice, and why that word is not decided here
 *
 * The business is not registered for GST, being below the registration threshold (D-659),
 * so there is no GSTIN to print and no tax may lawfully be collected (CGST s.32;
 * `billing/gst.py` refuses to render a tax invoice without one). What this is, is a
 * RECEIPT: an acknowledgement that money was received for prepaid calling credit.
 *
 * `document_type` and the qualifying sentence both come off the WIRE, because whether a
 * document is a lawful tax invoice depends on facts only the server holds. An unrecognised
 * value prints as itself rather than as a stronger claim.
 *
 * ## Money
 *
 * Every figure is an exact decimal STRING and is never parsed (hard rule 7's frontend
 * shadow). `formatINR` groups the digits the server sent; nothing here adds, subtracts or
 * rounds — `amount_inr` is the total the SERVER summed across every ledger row that
 * belongs to this payment, including rows that have scrolled off the client's page. It is
 * printed ONCE, in the totals block: a one-item receipt has no line table whose row would
 * only repeat the same figure.
 */
export function ReceiptDocument({ data }: { data: PaymentReceipt }) {
  const showSupplier = data.supplier_legal_name !== null || data.supplier_address !== null;

  return (
    <DocumentSheet className="p-6">
      <Masthead
        title={data.document_type === "receipt" ? "Receipt" : data.document_type}
        numberLabel="Reference"
        number={data.payment_ref}
      />

      <MetaRows
        rows={[
          ["Received on", formatIST(data.received_at)],
          ["For", "Calling credit"],
        ]}
      />

      <div className={showSupplier ? "mt-5 grid gap-3 sm:grid-cols-2" : "mt-5"}>
        <PartyCard heading="Paid by">
          <p className="font-medium">{data.organization_name}</p>
          {data.organization_billing_email !== null && (
            <PartyDetail>{data.organization_billing_email}</PartyDetail>
          )}
        </PartyCard>
        {showSupplier && (
          <PartyCard heading="Paid to">
            {data.supplier_legal_name !== null && (
              <p className="font-medium">{data.supplier_legal_name}</p>
            )}
            {data.supplier_address !== null && (
              <PartyDetail preLine>{data.supplier_address}</PartyDetail>
            )}
          </PartyCard>
        )}
      </div>

      <div className="mt-6 flex flex-col items-end gap-1">
        <TotalsBlock rows={[]} totalLabel="Amount received" total={formatINR(data.amount_inr)} />
        {/* A payment recorded across more than one entry is one we later corrected upwards.
            The amount above is the TOTAL, and saying how it got there is what stops a client
            comparing a single ledger row against a bank statement and finding it short. */}
        {data.entries > 1 && (
          <p className="text-xs text-slate-600">
            This payment was recorded in {data.entries} parts; the amount above is the total.
          </p>
        )}
      </div>

      <div className="mt-6 border-t border-slate-200 pt-3 text-xs text-slate-600">
        <p>{data.note}</p>
      </div>
    </DocumentSheet>
  );
}
