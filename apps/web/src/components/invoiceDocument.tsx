"use client";

// Layout adapted from Invoicely (https://github.com/legions-developer/invoicely), commit
// 820d3c51604faa10d44126e019c1fad51b54d96f, apps/web/src/components/pdf/default.tsx and
// apps/web/src/components/pdf/vercel.tsx. MIT licence, Copyright (c) 2025 Invoicely.
// Full notice: ./billing/LICENSE.

import {
  DocumentSheet,
  Masthead,
  MetaRows,
  PartyCard,
  PartyDetail,
  TotalsBlock,
} from "@/components/billing/documentParts";
import { ScrollRegion, formatINR, formatIST, formatRupeeRate } from "@/components/ui";
import type { Invoice } from "@/lib/api/invoice";
import { GST_STATUS_SENTENCE } from "@/lib/gstStatus";

/**
 * THE invoice sheet — one component, rendered by both realms (SLICE AL).
 *
 * The admin console and the client console print the SAME document, because it is the
 * same document: `build_invoice` is the only thing that derives a bill, and this is the
 * only thing that draws one. A "client version" of this markup is the exact accumulation
 * CLAUDE.md forbids — two renderers drift, and the first thing they drift on is a figure.
 * Saving it as a PDF is the browser's print-to-PDF of this markup through
 * `lib/printDocument.ts`; `billing/documentParts.tsx` says why no PDF library draws a
 * second copy.
 *
 * ## Why the paper is not tokenised (the one exception in the design system)
 *
 * `bg-surface`/`text-ink` would make the sheet follow the console's theme, and browsers
 * drop background colours when printing: in dark mode that is near-white ink on the
 * paper's own white, i.e. an invoice that prints blank. A document that is identical on
 * every screen and on paper is the property this component exists for, so the sheet stays
 * white with dark ink. The chrome around it (back link, month picker, print button)
 * belongs to the PAGE and is `print:hidden` there.
 *
 * ## MONEY — the reason this file is read before it is edited
 *
 * Every figure arrives as an exact decimal STRING and is never parsed (hard rule 7's
 * frontend shadow): `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998
 * on a document an accountant files. TOTALS and line AMOUNTS go through `formatINR`, which
 * formats the digits without parsing them and groups them the Indian way.
 *
 * The `Unit ₹` column does NOT, and that is the load-bearing decision here.
 * `overage_rate_inr` is NUMERIC(12,4) published unrounded on purpose
 * (`billing/service.py::rate_to_display`): the invoice promises `qty × unit = amount`, and
 * rounding ₹7.1250/min to ₹7.12 breaks that arithmetic IN OUR FAVOUR — which is the
 * version of wrong a client notices and a regulator asks about. `qty` is a decimal string
 * for the same reason and is printed as sent. So: the column an accountant ADDS UP is
 * formatted, the column they MULTIPLY BY is verbatim.
 *
 * ## Why the heading comes off the wire
 *
 * `document_type` decides whether this says TAX INVOICE or BILL OF SUPPLY. The words
 * are never chosen here, because whether this is a lawful tax invoice depends on facts
 * only the server holds (Rule 46's particulars, `billing/gst.py`), and a browser that
 * printed "TAX INVOICE" over a document with no GSTIN would be manufacturing the exact
 * defect this slice removes. An unrecognised value is treated as NOT a tax invoice —
 * failing towards the weaker claim is the only safe direction.
 */
export function InvoiceDocument({ data }: { data: Invoice }) {
  const isTaxInvoice = data.document_type === "tax_invoice";

  return (
    <DocumentSheet className="p-8 shadow">
      <Masthead
        title={isTaxInvoice ? "TAX INVOICE" : "BILL OF SUPPLY"}
        numberLabel="Invoice number"
        number={data.invoice_number}
      />

      <MetaRows
        rows={[
          ["Billing month", data.month],
          ["Generated", formatIST(data.generated_at)],
        ]}
      />

      {!isTaxInvoice && <NotATaxInvoice note={data.tax_note} />}

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <PartyCard heading="Billed by">
          {/* The supplier's LEGAL NAME from config, never a literal. Calevate is a trade
              name of a sole proprietor (`docs/legal/LEGAL-OPS-PLAYBOOK.md:16`, `:80-96`),
              so the party to the supply is the individual and what an accountant needs to
              see is whatever `GST_SUPPLIER_LEGAL_NAME` is set to — which is a decision
              taken with a CA, not one this component may make. The fallback is the trade
              name the founder contracts under (`lib/legal/placeholders.ts`,
              LEGAL_ENTITY_NAME), so an unconfigured document still names somebody. */}
          <p className="font-medium">{data.supplier.legal_name ?? "Calevate"}</p>
          {data.supplier.address && <PartyDetail preLine>{data.supplier.address}</PartyDetail>}
          {data.supplier.gstin && (
            <PartyDetail>
              GSTIN <span className="font-mono">{data.supplier.gstin}</span>
              {data.supplier.state_name ? ` · ${data.supplier.state_name}` : ""}
            </PartyDetail>
          )}
        </PartyCard>

        <PartyCard heading="Billed to">
          <p className="font-medium">{data.organization.name}</p>
          <PartyDetail>{data.organization.billing_email ?? "no billing email on file"}</PartyDetail>
          {/* Rule 46(e)-(f). The absence is stated rather than left blank: a client
              looking for their own GSTIN on a bill they cannot claim credit against
              needs to know that WE do not hold one, not to wonder where it went. */}
          <PartyDetail>
            {data.organization.gstin ? (
              <>
                GSTIN <span className="font-mono">{data.organization.gstin}</span>
              </>
            ) : (
              "GSTIN not on file — no input tax credit is claimable against this document."
            )}
          </PartyDetail>
        </PartyCard>

        <PartyCard heading="Place of supply">
          {/* Rule 46(n) wants the place of supply with the name of the State on an
              inter-State supply; it is shown on both because a reader asking why they
              were charged IGST rather than CGST+SGST needs it either way. */}
          <p className="font-medium">
            {data.place_of_supply.state_name
              ? `${data.place_of_supply.state_name} (${data.place_of_supply.state_code})`
              : "Not determined"}
          </p>
          <PartyDetail>{data.place_of_supply.basis}</PartyDetail>
        </PartyCard>
      </div>

      <ScrollRegion
        label="Invoice line items"
        className="-mx-4 mt-6 px-4 sm:mx-0 sm:px-0 print:mx-0 print:overflow-visible print:px-0"
      >
        <table className="w-full min-w-[600px] text-sm print:min-w-0">
          <thead>
            <tr className="bg-slate-900 text-xs uppercase tracking-wide text-white">
              <th className="rounded-l px-3 py-2 text-left font-semibold">Description</th>
              {/* Rule 46(g): the SAC of the supply, on the line. */}
              <th className="px-3 py-2 text-left font-semibold">SAC</th>
              <th className="px-3 py-2 text-right font-semibold">Qty</th>
              <th className="px-3 py-2 text-right font-semibold">Unit ₹</th>
              <th className="rounded-r px-3 py-2 text-right font-semibold">Amount ₹</th>
            </tr>
          </thead>
          <tbody>
            {data.line_items.map((item, idx) => (
              <tr key={idx} className="break-inside-avoid border-b border-slate-100 even:bg-slate-50">
                <td className="px-3 py-2.5 font-medium">{item.description}</td>
                <td className="px-3 py-2.5 font-mono text-xs">{item.sac ?? "—"}</td>
                {/* Qty and unit as the server sent them — this is the multiplication a
                    client checks by hand. */}
                <td className="px-3 py-2.5 text-right font-mono tabular-nums">{item.qty}</td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                  {formatRupeeRate(item.unit_inr)}
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                  {formatINR(item.amount_inr)}
                </td>
              </tr>
            ))}
            {data.line_items.length === 0 && (
              // Empty on purpose (no plan fee, no billable overage): the API still
              // returns totals so this renders as a usage-only statement.
              <tr className="border-b border-slate-100">
                <td colSpan={5} className="px-3 py-3 text-center text-slate-600">
                  No charges this month — usage statement only.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </ScrollRegion>

      <div className="mt-6 flex flex-col-reverse gap-6 sm:flex-row sm:items-end sm:justify-between">
        <footer className="space-y-1 text-xs text-slate-600 sm:max-w-sm">
          <p>
            {data.usage.minutes_used} minutes across {data.usage.calls} calls this month
            {data.usage.included_minutes > 0
              ? ` (${data.usage.included_minutes} minutes included in plan).`
              : "."}
          </p>
          {isTaxInvoice && (
            // The proviso to Rule 46 (inserted by Notification 74/2018-Central Tax) removes
            // the signature requirement for an electronically issued invoice. Said on the
            // document rather than assumed, so a recipient's accounts team does not send it
            // back asking for one.
            <p>
              Electronically issued; signature not required (proviso to Rule 46, CGST Rules
              2017).
            </p>
          )}
        </footer>

        {/* ONE ROW PER HEAD OF TAX (Rule 46(l)-(m)): CGST, SGST/UTGST and IGST are three
            different ledgers on the recipient's side, and tax charged without saying which
            one cannot be claimed. The components are the server's and sum to `gst_inr`
            exactly — nothing is added up here. A rate is printed as published: 9, not
            ₹9.00. */}
        <TotalsBlock
          rows={[
            ["Subtotal", formatINR(data.subtotal_inr)],
            ...data.tax_components.map(
              (component) =>
                [`${component.label} @ ${component.rate_pct}%`, formatINR(component.amount_inr)] as const,
            ),
          ]}
          totalLabel="Total"
          total={formatINR(data.total_inr)}
        />
      </div>
    </DocumentSheet>
  );
}

/**
 * What the document is, on its face: the server's tax note, which carries the one GST
 * sentence every client surface uses (D-659).
 *
 * Unregistered is the normal state, not a fault, so this is a plain note: no warning
 * colour and no settings names (the operator's screen lists those from `AdminInvoiceOut`).
 * `role="note"` rather than `role="alert"` on a document a client opens every month. The
 * shared sentence is the fallback for a server that sent no note.
 */
function NotATaxInvoice({ note }: { note: string | null }) {
  return (
    <div
      role="note"
      className="mt-4 rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700"
    >
      <p className="font-semibold">This is not a tax invoice.</p>
      <p className="mt-1">{note ?? GST_STATUS_SENTENCE}</p>
    </div>
  );
}
