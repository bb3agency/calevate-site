"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, Printer } from "lucide-react";

import { ProblemNotice, Skeleton, formatINR, formatIST } from "@/components/ui";
import { useInvoice } from "@/lib/api/invoice";

/**
 * Printable tax-invoice statement for one tenant-month.
 *
 * Unlike the rest of the admin console this page is a WHITE document: its purpose is
 * print / save-as-PDF from the browser, so it renders like the paper it will become.
 * The chrome (back link, month picker, print button) is screen-only via `print:hidden`
 * and is built from the design tokens like every other screen.
 *
 * **The paper is deliberately NOT tokenised, and that is the one exception on this
 * screen.** `bg-surface`/`text-ink` would make the document follow the console's theme,
 * and browsers drop background colours when printing: in dark mode that is near-white
 * ink on the paper's own white, i.e. an invoice that prints blank. A document that is
 * the same on every screen and on paper is the property this page exists for, so the
 * sheet stays white with dark ink and says why.
 *
 * ## MONEY — the reason this screen is read before it is edited
 *
 * Every figure arrives as an exact decimal STRING and is never parsed (hard rule 7's
 * frontend shadow): `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998
 * on a document an accountant files.
 *
 * TOTALS and line AMOUNTS go through `formatINR`, which formats the digits without
 * parsing them and groups them the Indian way. They used to be interpolated raw as
 * `₹{string}`, which printed `₹1015900.00` on a statement whose whole job is to be
 * read by a human — and would print `₹1015900.0` for any field the server ever sent
 * with one decimal place.
 *
 * The `Unit ₹` column does NOT go through `formatINR`, and that is the load-bearing
 * decision on this page. `overage_rate_inr` is NUMERIC(12,4) published unrounded on
 * purpose (`billing/service.py::rate_to_display`, and the client's own usage screen
 * makes the same exception): the invoice promises `qty × unit = amount`, and rounding
 * ₹7.1250/min to ₹7.12 breaks that arithmetic IN OUR FAVOUR — which is the version of
 * wrong a client notices and a regulator asks about. `qty` is a decimal string for the
 * same reason and is printed as sent. So: the column an accountant ADDS UP is formatted,
 * the column they MULTIPLY BY is verbatim.
 */
export default function TenantInvoicePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  // Default to the current IST billing month — same clock the API bills on, so the
  // picker and the statement agree on which month "now" is.
  const [month, setMonth] = useState(currentISTMonth);
  const invoice = useInvoice(tenantId, month);
  const data = invoice.data;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to client
        </Link>
        <div className="flex items-center gap-2">
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
            aria-label="Billing month"
          />
          <button
            type="button"
            // Disabled until there is a statement: printing a skeleton or an error box
            // produces a sheet of paper that looks like an invoice and is not one.
            disabled={!data}
            onClick={() => window.print()}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Printer className="h-4 w-4" />
            Print
          </button>
        </div>
      </div>

      {invoice.error && <ProblemNotice error={invoice.error} onRetry={() => invoice.refetch()} />}

      {/* A skeleton is not a document and a failure is not a ₹0.00 invoice: with nothing
          landed, neither the sheet nor a reassuring blank is rendered. */}
      {!data ? (
        invoice.error ? null : <Skeleton rows={8} />
      ) : (
        // The document proper: white regardless of console theme, because this is the
        // artifact an accountant prints and files (see the module note).
        <div className="rounded-card bg-white p-8 text-slate-900 shadow print:rounded-none print:p-0 print:shadow-none">
          <header className="flex items-start justify-between border-b border-slate-200 pb-4">
            <div>
              <h1 className="text-lg font-bold tracking-wide">TAX INVOICE</h1>
              <p className="mt-1 text-sm text-slate-600">Calevate · {data.month}</p>
            </div>
            <div className="text-right text-sm">
              <p className="font-mono font-medium">{data.invoice_number}</p>
              <p className="mt-1 text-slate-600">Generated {formatIST(data.generated_at)}</p>
            </div>
          </header>

          <section className="mt-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Billed to
            </h2>
            <p className="mt-1 text-sm font-medium">{data.organization.name}</p>
            <p className="text-sm text-slate-600">
              {data.organization.billing_email ?? "no billing email on file"}
            </p>
          </section>

          <div className="-mx-4 mt-6 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[600px] text-sm">
              <thead>
                <tr className="border-b border-slate-300 text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 text-left font-semibold">Description</th>
                  <th className="py-2 text-right font-semibold">Qty</th>
                  <th className="py-2 text-right font-semibold">Unit ₹</th>
                  <th className="py-2 text-right font-semibold">Amount ₹</th>
                </tr>
              </thead>
              <tbody>
                {data.line_items.map((item, idx) => (
                  <tr key={idx} className="border-b border-slate-100">
                    <td className="py-2 pr-2">{item.description}</td>
                    {/* Qty and unit as the server sent them — this is the multiplication
                        a client checks by hand. */}
                    <td className="py-2 text-right tabular-nums">{item.qty}</td>
                    <td className="py-2 text-right tabular-nums">₹{item.unit_inr}</td>
                    <td className="py-2 text-right tabular-nums">{formatINR(item.amount_inr)}</td>
                  </tr>
                ))}
                {data.line_items.length === 0 && (
                  // Empty on purpose (no plan fee, no billable overage): the API still
                  // returns totals so this renders as a usage-only statement.
                  <tr className="border-b border-slate-100">
                    <td colSpan={4} className="py-3 text-center text-slate-500">
                      No charges this month — usage statement only.
                    </td>
                  </tr>
                )}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={3} className="py-2 text-right text-slate-600">
                    Subtotal
                  </td>
                  <td className="py-2 text-right tabular-nums">{formatINR(data.subtotal_inr)}</td>
                </tr>
                <tr>
                  {/* A RATE, printed as published: 18, not ₹18.00. */}
                  <td colSpan={3} className="py-1 text-right text-slate-600">
                    GST @ {data.gst_rate_pct}%
                  </td>
                  <td className="py-1 text-right tabular-nums">{formatINR(data.gst_inr)}</td>
                </tr>
                <tr className="border-t border-slate-300 font-bold">
                  <td colSpan={3} className="py-2 text-right">
                    Total
                  </td>
                  <td className="py-2 text-right tabular-nums">{formatINR(data.total_inr)}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <footer className="mt-6 border-t border-slate-200 pt-3 text-xs text-slate-500">
            {data.usage.minutes_used} minutes across {data.usage.calls} calls this month
            {data.usage.included_minutes > 0
              ? ` (${data.usage.included_minutes} minutes included in plan).`
              : "."}
          </footer>
        </div>
      )}
    </div>
  );
}

/** Current billing month in IST (YYYY-MM) — en-CA formats as YYYY-MM-DD. */
function currentISTMonth(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }).slice(0, 7);
}
