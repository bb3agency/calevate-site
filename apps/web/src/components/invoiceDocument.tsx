"use client";

import { ScrollRegion, formatINR, formatIST } from "@/components/ui";
import type { Invoice } from "@/lib/api/invoice";

/**
 * THE invoice sheet — one component, rendered by both realms (SLICE AL).
 *
 * The admin console and the client console print the SAME document, because it is the
 * same document: `build_invoice` is the only thing that derives a bill, and this is the
 * only thing that draws one. A "client version" of this markup is the exact accumulation
 * CLAUDE.md forbids — two renderers drift, and the first thing they drift on is a figure.
 *
 * ## Why the paper is not tokenised (the one exception in the design system)
 *
 * `bg-surface`/`text-ink` would make the sheet follow the console's theme, and browsers
 * drop background colours when printing: in dark mode that is near-white ink on the
 * paper's own white, i.e. an invoice that prints blank. A document that is identical on
 * every screen and on paper is the property this component exists for, so the sheet stays
 * white with dark ink and says why. The chrome around it (back link, month picker, print
 * button) belongs to the PAGE and is `print:hidden` there.
 *
 * ## MONEY — the reason this file is read before it is edited
 *
 * Every figure arrives as an exact decimal STRING and is never parsed (hard rule 7's
 * frontend shadow): `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998
 * on a document an accountant files.
 *
 * TOTALS and line AMOUNTS go through `formatINR`, which formats the digits without
 * parsing them and groups them the Indian way.
 *
 * The `Unit ₹` column does NOT, and that is the load-bearing decision here.
 * `overage_rate_inr` is NUMERIC(12,4) published unrounded on purpose
 * (`billing/service.py::rate_to_display`, and the client's own usage screen makes the
 * same exception): the invoice promises `qty × unit = amount`, and rounding ₹7.1250/min
 * to ₹7.12 breaks that arithmetic IN OUR FAVOUR — which is the version of wrong a client
 * notices and a regulator asks about. `qty` is a decimal string for the same reason and
 * is printed as sent. So: the column an accountant ADDS UP is formatted, the column they
 * MULTIPLY BY is verbatim.
 *
 * ## Why the heading comes off the wire
 *
 * `document_type` decides whether this says TAX INVOICE or PROFORMA INVOICE. The words
 * are never chosen here, because whether this is a lawful tax invoice depends on facts
 * only the server holds (Rule 46's particulars, `billing/gst.py`), and a browser that
 * printed "TAX INVOICE" over a document with no GSTIN would be manufacturing the exact
 * defect this slice removes. An unrecognised value is treated as NOT a tax invoice —
 * failing towards the weaker claim is the only safe direction.
 */
export function InvoiceDocument({ data }: { data: Invoice }) {
  const isTaxInvoice = data.document_type === "tax_invoice";

  return (
    <div className="rounded-card bg-white p-8 text-slate-900 shadow print:rounded-none print:p-0 print:shadow-none">
      <header className="flex items-start justify-between border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-lg font-bold tracking-wide">
            {isTaxInvoice ? "TAX INVOICE" : "PROFORMA INVOICE"}
          </h1>
          {/* The supplier's LEGAL NAME, not the brand. The literal string "Calevate"
              used to sit here, which is a trading name and not the entity that would be
              party to the supply. */}
          <p className="mt-1 text-sm font-medium">{data.supplier.legal_name ?? "Calevate"}</p>
          {data.supplier.address && (
            <p className="mt-0.5 whitespace-pre-line text-sm text-slate-600">
              {data.supplier.address}
            </p>
          )}
          {data.supplier.gstin && (
            <p className="mt-0.5 text-sm text-slate-600">
              GSTIN <span className="font-mono">{data.supplier.gstin}</span>
              {data.supplier.state_name ? ` · ${data.supplier.state_name}` : ""}
            </p>
          )}
          <p className="mt-1 text-sm text-slate-600">Billing month {data.month}</p>
        </div>
        <div className="text-right text-sm">
          <p className="font-mono font-medium">{data.invoice_number}</p>
          <p className="mt-1 text-slate-600">Generated {formatIST(data.generated_at)}</p>
        </div>
      </header>

      {!isTaxInvoice && <NotATaxInvoice blockers={data.document_blockers} />}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Billed to
          </h2>
          <p className="mt-1 text-sm font-medium">{data.organization.name}</p>
          <p className="text-sm text-slate-600">
            {data.organization.billing_email ?? "no billing email on file"}
          </p>
          {/* Rule 46(e)-(f). The absence is stated rather than left blank: a client
              looking for their own GSTIN on a bill they cannot claim credit against
              needs to know that WE do not hold one, not to wonder where it went. */}
          <p className="mt-0.5 text-sm text-slate-600">
            {data.organization.gstin ? (
              <>
                GSTIN <span className="font-mono">{data.organization.gstin}</span>
              </>
            ) : (
              "GSTIN not on file — no input tax credit is claimable against this document."
            )}
          </p>
        </section>

        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Place of supply
          </h2>
          {/* Rule 46(n) wants the place of supply with the name of the State on an
              inter-State supply; it is shown on both because a reader asking why they
              were charged IGST rather than CGST+SGST needs it either way. */}
          <p className="mt-1 text-sm font-medium">
            {data.place_of_supply.state_name
              ? `${data.place_of_supply.state_name} (${data.place_of_supply.state_code})`
              : "Not determined"}
          </p>
          <p className="text-sm text-slate-600">{data.place_of_supply.basis}</p>
        </section>
      </div>

      <ScrollRegion label="Invoice line items" className="-mx-4 mt-6 px-4 sm:mx-0 sm:px-0">
        <table className="w-full min-w-[600px] text-sm">
          <thead>
            <tr className="border-b border-slate-300 text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2 text-left font-semibold">Description</th>
              {/* Rule 46(g): the SAC of the supply, on the line. */}
              <th className="py-2 text-left font-semibold">SAC</th>
              <th className="py-2 text-right font-semibold">Qty</th>
              <th className="py-2 text-right font-semibold">Unit ₹</th>
              <th className="py-2 text-right font-semibold">Amount ₹</th>
            </tr>
          </thead>
          <tbody>
            {data.line_items.map((item, idx) => (
              <tr key={idx} className="border-b border-slate-100">
                <td className="py-2 pr-2">{item.description}</td>
                <td className="py-2 font-mono text-xs">{item.sac ?? "—"}</td>
                {/* Qty and unit as the server sent them — this is the multiplication a
                    client checks by hand. */}
                <td className="py-2 text-right tabular-nums">{item.qty}</td>
                <td className="py-2 text-right tabular-nums">₹{item.unit_inr}</td>
                <td className="py-2 text-right tabular-nums">{formatINR(item.amount_inr)}</td>
              </tr>
            ))}
            {data.line_items.length === 0 && (
              // Empty on purpose (no plan fee, no billable overage): the API still
              // returns totals so this renders as a usage-only statement.
              <tr className="border-b border-slate-100">
                <td colSpan={5} className="py-3 text-center text-slate-500">
                  No charges this month — usage statement only.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4} className="py-2 text-right text-slate-600">
                Subtotal
              </td>
              <td className="py-2 text-right tabular-nums">{formatINR(data.subtotal_inr)}</td>
            </tr>
            {/* ONE ROW PER HEAD OF TAX (Rule 46(l)-(m)). The single "GST @ 18%" line this
                replaces was not merely terse: CGST, SGST/UTGST and IGST are three
                different ledgers on the recipient's side, and tax charged without saying
                which one cannot be claimed. The components are the server's and sum to
                `gst_inr` exactly — nothing is added up here. */}
            {data.tax_components.map((component) => (
              <tr key={component.label}>
                <td colSpan={4} className="py-1 text-right text-slate-600">
                  {/* A RATE, printed as published: 9, not ₹9.00. */}
                  {component.label} @ {component.rate_pct}%
                </td>
                <td className="py-1 text-right tabular-nums">{formatINR(component.amount_inr)}</td>
              </tr>
            ))}
            <tr className="border-t border-slate-300 font-bold">
              <td colSpan={4} className="py-2 text-right">
                Total
              </td>
              <td className="py-2 text-right tabular-nums">{formatINR(data.total_inr)}</td>
            </tr>
          </tfoot>
        </table>
      </ScrollRegion>

      <footer className="mt-6 space-y-1 border-t border-slate-200 pt-3 text-xs text-slate-500">
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
    </div>
  );
}

/**
 * The refusal, on the face of the document.
 *
 * §52's rule is that a failure is a refusal and never a confident emptiness. This is the
 * same rule applied to a LEGAL claim rather than to a failed request: the document cannot
 * be a tax invoice, so it says so, says what that means for the reader, and — for the
 * operator who can fix it — names the configuration that is missing.
 *
 * It is `role="note"` rather than `role="alert"`: nothing has gone wrong at request time,
 * and an alert here would be announced on a document a client opens every month.
 */
function NotATaxInvoice({ blockers }: { blockers: string[] }) {
  return (
    <div
      role="note"
      className="mt-4 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
    >
      <p className="font-semibold">This is not a tax invoice.</p>
      <p className="mt-1">
        Calevate&apos;s GST registration is not yet on record, so this document cannot be
        used to claim input tax credit and no tax may be collected against it. It is a
        statement of what this month&apos;s service comes to. A tax invoice will be issued
        once the registration is in place.
      </p>
      {blockers.length > 0 && (
        // For US, not for the client — but on the same sheet, because the person who can
        // fix it is the person most likely to be looking at it, and a refusal that does
        // not say what would satisfy it is half an answer.
        <p className="mt-2 text-xs">
          Missing configuration: <span className="font-mono">{blockers.join(", ")}</span>
        </p>
      )}
    </div>
  );
}
