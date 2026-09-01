"use client";

import { useState } from "react";
import { Printer } from "lucide-react";

import { InvoiceDocument } from "@/components/invoiceDocument";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { currentISTMonth, useClientInvoice } from "@/lib/api/invoice";
import { useClientSession } from "@/lib/api/session";
import { useMe } from "@/lib/api/hooks";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/**
 * The client's own invoice (SLICE AL / BRD §51 — the persona that pays it).
 *
 * Until this screen the only way to see a Calevate invoice was the admin console, so a
 * client who wanted their own bill had to ask us for it. What they get here is not a
 * client-flavoured summary but THE document: `components/invoiceDocument.tsx` is shared
 * with `/admin/tenants/[tenantId]/invoice`, and the API is one computation behind two
 * routes, so what they print is byte-for-byte what ops prints.
 *
 * ## What this screen deliberately does NOT do
 *
 * It does not compute, sum, or re-derive anything. Every figure — including the split of
 * GST into its heads — is the server's, because the moment a browser adds two of these
 * numbers together it becomes a second implementation of a bill (`billing/invoice.py`).
 *
 * It does not WRITE. Rendering an invoice used to append the onboarding setup fee the
 * first time anyone opened it (D-64); that moved to a scheduled job, and putting a
 * side effect back on this path would mean a support person in a read-only "view as
 * client" session (D-22) triggering a billing write by opening a page.
 *
 * ## Permission, and why the gate is here as well as on the server
 *
 * `GET /v1/billing/invoice` requires `billing:read`, which `staff` does not hold — spend
 * is an owner's business (SEC-COMP §5), the same rule `/usage` follows. The nav shows
 * this screen to everyone, so without the check below a staff member would reach it and
 * collect a red 403 that reads like an outage.
 *
 * Read off `/v1/me` rather than from a role list this build would have to keep in step
 * with `core/rbac.py`. NOT `useWriteAccess`: that refuses every permission to an
 * impersonating operator, which is right for a control that writes and wrong here —
 * `billing:read` is not a mutating permission, an operator holds it, and blanking this
 * screen for the person on the support call would be a refusal the server never made.
 * While `/v1/me` is in flight nothing is refused, so the screen never flashes an
 * explanation it is about to withdraw.
 */
export default function ClientInvoicePage() {
  const session = useClientSession();
  const me = useMe(session);
  const [month, setMonth] = useState(currentISTMonth);
  const invoice = useClientInvoice(session, month);

  /*
   * THE STATEMENT, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * The month picker is the only control, and the only writable field — same rule and
   * same `YYYY-MM` guard as `/c/{slug}/spend`, which is the screen next door.
   *
   * THE INVOICE'S OWN LINES ARE NOT SENT. The document carries the client's registered
   * business name and address; the assistant is told the totals and how many lines there
   * are, which is what "why is this month higher" needs, and none of the identity block.
   */
  useCopilotSurface({
    route: "/c/{slug}/invoice",
    title: "Your statement",
    realm: "client",
    fields: [
      {
        id: "invoice-month",
        label: "Billing month",
        type: "text",
        value: month,
        help: "YYYY-MM, in Indian Standard Time.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value:
          me.data !== undefined && !me.data.permissions.includes("billing:read")
            ? "a refusal — invoices are limited to the account owner, so no statement is shown"
            : invoice.data
              ? "the statement below has loaded and can be printed"
              : invoice.error
                ? "the statement failed to load — the Print button is disabled"
                : "still loading",
      },
      { key: "month_requested", label: "Month asked for", value: month },
    ],
    apply: (items) => {
      for (const item of items) {
        const wanted = asText(item.value);
        if (item.field_id === "invoice-month" && /^\d{4}-(0[1-9]|1[0-2])$/.test(wanted)) {
          setMonth(wanted);
        }
      }
    },
  });

  const refused = me.data !== undefined && !me.data.permissions.includes("billing:read");
  if (refused) {
    return (
      <RestrictionNote reason="Invoices are limited to the account owner. Ask them to share this month's statement, or to give you owner access." />
    );
  }

  const data = invoice.data;

  return (
    <div className="mx-auto max-w-2xl space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <p className="text-sm text-ink-muted">
          Your statement for a billing month, in Indian Standard Time.
        </p>
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
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Printer className="h-4 w-4" />
            Print
          </button>
        </div>
      </div>

      {invoice.error && (
        <ProblemNotice error={invoice.error} onRetry={() => void invoice.refetch()} />
      )}

      {/* §52: loading is a skeleton, failure is a refusal, and neither is a ₹0.00
          invoice. "You owe nothing" is a claim about a month's business, and a 500 is not
          evidence for it — least of all on a printable sheet. */}
      {!data ? invoice.error ? null : <Skeleton rows={8} /> : <InvoiceDocument data={data} />}
    </div>
  );
}
