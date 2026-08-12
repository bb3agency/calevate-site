"use client";

import Link from "next/link";
import { use, useState } from "react";

import { ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { useInvoice } from "@/lib/api/invoice";

/**
 * Printable tax-invoice statement for one tenant-month.
 *
 * Unlike the rest of the admin console this page is a WHITE document: its purpose is
 * print / save-as-PDF from the browser, so it renders like the paper it will become.
 * The chrome (back link, month picker, print button) is screen-only via `print:hidden`.
 *
 * Money arrives as exact decimal strings and is rendered VERBATIM as ₹{string} —
 * never parsed into a JS number (hard rule 7's frontend shadow).
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

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between gap-3 print:hidden">
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="text-sm text-sky-400 hover:underline"
        >
          ← Back to client
        </Link>
        <div className="flex items-center gap-2">
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100"
            aria-label="Billing month"
          />
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-md bg-slate-100 px-3 py-1 text-sm font-medium text-slate-900"
          >
            Print
          </button>
        </div>
      </div>

      {invoice.isLoading && <Skeleton rows={8} />}
      {invoice.error && (
        <ProblemNotice error={invoice.error} onRetry={() => invoice.refetch()} />
      )}

      {invoice.data && (
        // The document proper: white regardless of console theme, because this is the
        // artifact an accountant prints and files.
        <div className="rounded-xl bg-white p-8 text-slate-900 shadow print:rounded-none print:p-0 print:shadow-none">
          <header className="flex items-start justify-between border-b border-slate-200 pb-4">
            <div>
              <h1 className="text-lg font-bold tracking-wide">TAX INVOICE</h1>
              <p className="mt-1 text-sm text-slate-600">Calevate · {invoice.data.month}</p>
            </div>
            <div className="text-right text-sm">
              <p className="font-mono font-medium">{invoice.data.invoice_number}</p>
              <p className="mt-1 text-slate-600">
                Generated {formatIST(invoice.data.generated_at)}
              </p>
            </div>
          </header>

          <section className="mt-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Billed to
            </h2>
            <p className="mt-1 text-sm font-medium">{invoice.data.organization.name}</p>
            <p className="text-sm text-slate-600">
              {invoice.data.organization.billing_email ?? "no billing email on file"}
            </p>
          </section>

          <table className="mt-6 w-full text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-xs uppercase tracking-wide text-slate-500">
                <th className="py-2 text-left font-semibold">Description</th>
                <th className="py-2 text-right font-semibold">Qty</th>
                <th className="py-2 text-right font-semibold">Unit ₹</th>
                <th className="py-2 text-right font-semibold">Amount ₹</th>
              </tr>
            </thead>
            <tbody>
              {invoice.data.line_items.map((item, idx) => (
                <tr key={idx} className="border-b border-slate-100">
                  <td className="py-2 pr-2">{item.description}</td>
                  <td className="py-2 text-right tabular-nums">{item.qty}</td>
                  <td className="py-2 text-right tabular-nums">₹{item.unit_inr}</td>
                  <td className="py-2 text-right tabular-nums">₹{item.amount_inr}</td>
                </tr>
              ))}
              {invoice.data.line_items.length === 0 && (
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
                <td className="py-2 text-right tabular-nums">
                  ₹{invoice.data.subtotal_inr}
                </td>
              </tr>
              <tr>
                <td colSpan={3} className="py-1 text-right text-slate-600">
                  GST @ {invoice.data.gst_rate_pct}%
                </td>
                <td className="py-1 text-right tabular-nums">₹{invoice.data.gst_inr}</td>
              </tr>
              <tr className="border-t border-slate-300 font-bold">
                <td colSpan={3} className="py-2 text-right">
                  Total
                </td>
                <td className="py-2 text-right tabular-nums">₹{invoice.data.total_inr}</td>
              </tr>
            </tfoot>
          </table>

          <footer className="mt-6 border-t border-slate-200 pt-3 text-xs text-slate-500">
            {invoice.data.usage.minutes_used} minutes across {invoice.data.usage.calls}{" "}
            calls this month
            {invoice.data.usage.included_minutes > 0
              ? ` (${invoice.data.usage.included_minutes} minutes included in plan).`
              : "."}
          </footer>
        </div>
      )}
    </div>
  );
}

/** Current billing month in IST (YYYY-MM) — en-CA formats as YYYY-MM-DD. */
function currentISTMonth(): string {
  return new Date()
    .toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })
    .slice(0, 7);
}
