"use client";

import { useRef, useState } from "react";
import { Printer } from "lucide-react";

import { InvoiceDocument } from "@/components/invoiceDocument";
import { FIELD_INLINE, PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { currentISTMonth, useInvoice, type AdminInvoice } from "@/lib/api/invoice";
import { useTenant } from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { printDocument } from "@/lib/printDocument";

/**
 * INVOICE — this client's statement for a month, and why it is not a tax invoice.
 *
 * The SHEET is `components/invoiceDocument.tsx`, shared with the client's own screen: one
 * renderer, because it is one document. What is here is the operator's chrome — the month,
 * Print, and the operator-only `document_blockers` (D-659), which name the settings a GST
 * registration would need. Unset is the normal state while Calevate is below the threshold,
 * so they are a plain note and never part of the sheet: a settings name on a client's
 * statement is an internal, not an explanation.
 *
 * Print goes through `printDocument` rather than `window.print()`: the console's shell is a
 * fixed-height box that scrolls internally, so the browser's print would carry the sidebar
 * and only the visible part of the sheet.
 */
export function InvoiceScreen({ tenantId }: { tenantId: string }) {
  // The current IST billing month — the clock the API bills on.
  const [month, setMonth] = useState(currentISTMonth);
  const invoice = useInvoice(tenantId, month);
  const tenantName = useTenant(tenantId).data?.name;
  const data = invoice.data;
  const sheet = useRef<HTMLDivElement>(null);

  /*
   * THE STATEMENT, DECLARED TO THE ASSISTANT. `organization.billing_email` is a person's
   * inbox, so it stays on the sheet; `gstin` is left out because nobody asks an assistant
   * about a number they can read on screen. `document_blockers` is the answer to the one
   * question worth asking here — "why is this not a tax invoice" — in the server's words.
   * The month is read-only: it decides which statement is on the paper about to print.
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
    // A section, so the page header is not a second banner beside the sheet's own header.
    <section className="space-y-5">
      <PageHeader
        className="print:hidden"
        title="Invoice"
        description="This client's statement for a billing month."
        actions={
          <>
            <input
              type="month"
              value={month}
              // No future months: a blank 2027 statement reads like a failure (F-9a).
              max={currentISTMonth()}
              onChange={(e) => setMonth(e.target.value)}
              className={FIELD_INLINE}
              aria-label="Billing month"
            />
            <button
              type="button"
              // Disabled until there is a statement: printing a skeleton or an error box
              // produces a sheet of paper that looks like an invoice and is not one.
              disabled={!data}
              onClick={() =>
                sheet.current &&
                void printDocument(sheet.current, {
                  title: `${tenantName ?? "Statement"} ${month}`,
                })
              }
              className={PRIMARY_BUTTON}
            >
              <Printer aria-hidden className="h-4 w-4" />
              Print or save as PDF
            </button>
          </>
        }
      />

      {invoice.error && <ProblemNotice error={invoice.error} onRetry={() => invoice.refetch()} />}

      {data && <DocumentBlockers data={data} />}

      {/* A skeleton is not a document and a failure is not a ₹0.00 invoice. */}
      {!data ? (
        invoice.error ? null : <Skeleton rows={8} />
      ) : (
        <div ref={sheet} className="max-w-3xl">
          <InvoiceDocument data={data} />
        </div>
      )}
    </section>
  );
}

/**
 * Operator-only: what a registration would need before this could be a tax invoice, in the
 * server's own words. A fact, not a fault (D-659), so a plain note rather than a warning, and
 * nothing at all when the list is empty.
 */
function DocumentBlockers({ data }: { data: AdminInvoice }) {
  if (data.document_blockers.length === 0) return null;
  return (
    <section
      aria-labelledby="invoice-blockers"
      className="border-l-2 border-line py-1 pl-4 text-body print:hidden"
    >
      <h3 id="invoice-blockers" className="font-medium text-ink">
        Not a tax invoice yet
      </h3>
      <p className="mt-0.5 text-meta text-ink-muted">
        Only you see this. The client&apos;s copy carries the GST note on the sheet below.
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-meta text-ink-muted">
        {data.document_blockers.map((blocker) => (
          <li key={blocker} className="break-words">
            {blocker}
          </li>
        ))}
      </ul>
    </section>
  );
}
