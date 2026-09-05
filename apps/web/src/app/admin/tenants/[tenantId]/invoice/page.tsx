"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, Printer } from "lucide-react";

import { InvoiceDocument } from "@/components/invoiceDocument";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { currentISTMonth, useInvoice } from "@/lib/api/invoice";
import { useTenant } from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

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
  // WHOSE statement the chrome is driving. The sheet names the organization once it has
  // loaded, but the month picker and Print sit in chrome that never did — and that chrome
  // is where the operator acts (ux-audit F-1). The document render does not wait on this.
  const tenantQuery = useTenant(tenantId);
  const tenantName = tenantQuery.data?.name;
  const data = invoice.data;

  /*
   * THE STATEMENT, DECLARED TO THE SCREEN ASSISTANT.
   *
   * One tenant, named by the route. The interesting decision here is what NOT to send from
   * a document that is otherwise entirely money: `organization.billing_email` is a person's
   * inbox at that business, so it stays on the sheet — and `assert_redacted` would refuse
   * the whole question if it did not, on a screen whose sole purpose is to be read.
   * `gstin` is a REGISTRATION identifying a business rather than a natural person (the same
   * line the KYC screen draws), so it may go; it is left out anyway because nobody asks an
   * assistant about a GSTIN they can read on screen, and it is one fewer thing on the wire.
   *
   * `document_blockers` is the whole reason this screen has an assistant worth opening —
   * "why is this a proforma and not an invoice" is the question, and the blockers are the
   * answer, in the server's own words.
   *
   * The month picker is READ-ONLY: it changes which statement is on the paper an operator
   * is about to print, and the print button is right beside it.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/invoice",
    title: "Invoice",
    realm: "admin",
    fields: [
      {
        id: "invoice-month",
        label: "Billing month",
        type: "text",
        value: month,
        writable: false,
        help: "IST billing month as YYYY-MM. It decides which statement prints.",
      },
    ],
    facts: data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "client", label: "Client", value: data.organization.name },
          { key: "month", label: "Month", value: data.month },
          { key: "document_type", label: "Document type", value: data.document_type },
          { key: "invoice_number", label: "Invoice number", value: data.invoice_number },
          {
            key: "document_blockers",
            label: "Why this is not a tax invoice yet",
            value: data.document_blockers.join("; ") || "nothing is blocking it",
          },
          { key: "subtotal_inr", label: "Subtotal (₹)", value: data.subtotal_inr },
          { key: "gst_inr", label: `GST at ${data.gst_rate_pct}% (₹)`, value: data.gst_inr },
          { key: "total_inr", label: "Total (₹)", value: data.total_inr },
          {
            key: "place_of_supply",
            label: "Place of supply",
            value: `${data.place_of_supply.state_name} (${data.place_of_supply.supply_type}, basis ${data.place_of_supply.basis})`,
          },
          { key: "calls", label: "Calls billed", value: String(data.usage.calls) },
          { key: "minutes_used", label: "Minutes used", value: data.usage.minutes_used },
          { key: "line_items", label: "Line items on the sheet", value: String(data.line_items.length) },
        ]
      : [
          { key: "client", label: "Client", value: tenantName ?? "not read yet" },
          {
            key: "statement",
            label: "The statement",
            value: invoice.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <div>
          <Link
            href={`/admin/tenants/${tenantId}`}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {tenantName ?? "Back to client"}
          </Link>
          <h1 className="mt-1 text-xl font-semibold text-ink">Invoice</h1>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="month"
            value={month}
            // No future months: a blank 2027 statement reads like a failure (F-9a).
            max={currentISTMonth()}
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
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
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
