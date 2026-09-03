"use client";

import { MonoValue, formatINR, formatIST } from "@/components/ui";
import type { PaymentReceipt } from "@/lib/api/wallet";

/**
 * THE receipt sheet for one credit payment — a document, not a panel.
 *
 * It lives beside `invoiceDocument.tsx` for the same two reasons that one does, and the
 * second is mechanical rather than aesthetic:
 *
 * ## Why the paper is not tokenised (the design system's one exception)
 *
 * `bg-surface`/`text-ink` would make the sheet follow the console's theme, and browsers
 * drop background colours when printing: in dark mode that is near-white ink on the
 * paper's own white — a receipt that prints blank. A document that is identical on every
 * screen and on paper is the property this component exists for, so the sheet is white
 * with dark ink and says why. `tests/contrast.test.ts` scopes its grey-literal ban to
 * `src/app/` precisely so a document under `src/components/` can argue this where it
 * lives; the chrome around the sheet (the close and print buttons) belongs to the DIALOG
 * and is `print:hidden` there.
 *
 * ## Why it is not called a tax invoice, and why that word is not decided here
 *
 * The business is not registered for GST and is not required to be at present turnover,
 * so there is no GSTIN to print and no tax may lawfully be collected (CGST s.32;
 * `billing/gst.py` refuses to render a tax invoice without one). What this is, is a
 * RECEIPT: an acknowledgement that money was received for prepaid calling credit.
 *
 * `document_type` and the qualifying sentence both come off the WIRE, exactly as the
 * monthly statement's heading does, because whether a document is a lawful tax invoice
 * depends on facts only the server holds — and a browser that printed a tax heading over
 * a document with no GSTIN would be manufacturing the exact defect that rule prevents. An
 * unrecognised value prints as a plain "Receipt": failing towards the weaker claim is the
 * only safe direction.
 *
 * ## Money
 *
 * Every figure is an exact decimal STRING and is never parsed (hard rule 7's frontend
 * shadow). `formatINR` groups the digits the server sent; nothing here adds, subtracts or
 * rounds — `amount_inr` is the total the SERVER summed across every ledger row that
 * belongs to this payment, including rows that have scrolled off the client's page.
 */
export function ReceiptDocument({ data }: { data: PaymentReceipt }) {
  return (
    <div className="rounded-card bg-white p-6 text-slate-900 print:rounded-none print:p-0 print:shadow-none">
      <h1 className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
        {data.document_type === "receipt" ? "Receipt" : data.document_type}
      </h1>
      <p className="mt-3 text-3xl font-bold tabular-nums">{formatINR(data.amount_inr)}</p>
      <p className="mt-1 text-sm text-slate-600">
        Received on {formatIST(data.received_at)}
      </p>

      <dl className="mt-6 space-y-2 text-sm">
        <Line label="Paid by" value={data.organization_name} />
        {data.organization_billing_email !== null && (
          <Line label="Billing email" value={data.organization_billing_email} />
        )}
        {data.supplier_legal_name !== null && (
          <Line label="Paid to" value={data.supplier_legal_name} />
        )}
        {data.supplier_address !== null && (
          <Line label="Address" value={data.supplier_address} />
        )}
        <Line label="For" value="Calling credit" />
      </dl>

      <p className="mt-4 text-xs text-slate-600">
        Reference <MonoValue>{data.payment_ref}</MonoValue>
      </p>
      {/* A payment recorded across more than one entry is one we later corrected upwards.
          The amount above is the TOTAL, and saying how it got there is what stops a client
          comparing a single ledger row against a bank statement and finding it short. */}
      {data.entries > 1 && (
        <p className="mt-1 text-xs text-slate-600">
          This payment was recorded in {data.entries} parts; the amount above is the total.
        </p>
      )}
      <p className="mt-4 border-t border-slate-200 pt-3 text-xs text-slate-600">{data.note}</p>
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
