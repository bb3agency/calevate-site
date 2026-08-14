"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, Printer } from "lucide-react";

import { InvoiceDocument } from "@/components/invoiceDocument";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { currentISTMonth, useInvoice } from "@/lib/api/invoice";

/**
 * Ops's copy of one tenant's statement for a billing month.
 *
 * The SHEET itself lives in `components/invoiceDocument.tsx` and is shared with the
 * client's own screen (`/c/[slug]/invoice`) — one renderer, because it is one document.
 * What is here is the CHROME: back link, month picker, print button, and the two
 * not-a-document states. All of it is `print:hidden`, so what leaves the printer is the
 * sheet and nothing else.
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
      {!data ? invoice.error ? null : <Skeleton rows={8} /> : <InvoiceDocument data={data} />}
    </div>
  );
}
