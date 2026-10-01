"use client";

import { useRef, useState } from "react";
import { Printer } from "lucide-react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { InvoiceDocument } from "@/components/invoiceDocument";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatINR,
} from "@/components/ui";
import { useStatements, type StatementSummary } from "@/lib/api/billingHistory";
import type { Session } from "@/lib/api/client";
import { useClientInvoice } from "@/lib/api/invoice";
import { formatBillingMonth } from "@/lib/billingMonth";
import { printDocument } from "@/lib/printDocument";

/**
 * One row per IST month since the account opened, newest first, each opening that
 * month's statement. The list is the server's (`useStatements`); a row's document is the
 * existing statement fetch for that month, so the sheet a client prints is the same one
 * an operator sees — this screen never assembles a statement of its own.
 */
export function StatementsView({ session, allowed }: { session: Session; allowed: boolean | null }) {
  const statements = useStatements(session, { enabled: allowed === true });
  const [open, setOpen] = useState<string | null>(null);

  if (allowed === false) {
    return (
      <RestrictionNote reason="Statements are limited to the account owner. Ask them to share this month's statement, or to give you owner access." />
    );
  }

  const rows = statements.data?.pages.flatMap((page) => page.statements) ?? [];
  const columns: DataColumn<StatementSummary>[] = [
    {
      id: "month",
      header: "Month",
      cell: (row) => (
        <span className="block">
          <span className="font-medium text-ink">{formatBillingMonth(row.month)}</span>
          {!row.closed && <span className="ml-1.5 text-xs text-ink-muted">so far</span>}
          <span className="block font-mono text-xs text-ink-faint">{row.invoice_number}</span>
        </span>
      ),
    },
    {
      id: "total",
      header: "Statement total",
      align: "right",
      cell: (row) => <span className="font-semibold tabular-nums">{formatINR(row.total_inr)}</span>,
    },
    {
      id: "added",
      header: "Credit added",
      align: "right",
      hideBelow: "md",
      cell: (row) => <span className="tabular-nums text-ink-muted">{formatINR(row.credit_added_inr)}</span>,
    },
    {
      id: "spent",
      header: "Spent",
      align: "right",
      hideBelow: "sm",
      cell: (row) => <span className="tabular-nums text-ink-muted">{formatINR(row.wallet_spent_inr)}</span>,
    },
    {
      id: "calls",
      header: "Calls",
      align: "right",
      hideBelow: "md",
      cell: (row) => <span className="tabular-nums text-ink-muted">{formatCount(row.calls)}</span>,
    },
    {
      id: "open",
      header: "Statement",
      align: "right",
      cell: (row) => (
        <button
          type="button"
          onClick={() => setOpen(row.month)}
          aria-label={`Open the statement for ${formatBillingMonth(row.month)}`}
          className={SECONDARY_BUTTON_SM}
        >
          Open
        </button>
      ),
    },
  ];

  return (
    <section className="space-y-3">
      {statements.error ? (
        <ProblemNotice error={statements.error} onRetry={() => void statements.refetch()} />
      ) : !statements.data ? (
        <Skeleton rows={4} label="Loading your statements" />
      ) : rows.length === 0 ? (
        <EmptyState message="No statements yet. Your first one appears at the end of your first month." />
      ) : (
        <>
          <DataTable
            label="Your monthly statements, newest first"
            columns={columns}
            rows={rows}
            getRowId={(row) => row.month}
            className="rounded-card border border-line bg-surface"
          />
          {statements.hasNextPage && (
            <button
              type="button"
              onClick={() => void statements.fetchNextPage()}
              disabled={statements.isFetchingNextPage}
              className={SECONDARY_BUTTON}
            >
              {statements.isFetchingNextPage ? "Loading…" : "Show earlier months"}
            </button>
          )}
        </>
      )}
      {open !== null && (
        <StatementDrawer session={session} month={open} onClose={() => setOpen(null)} />
      )}
    </section>
  );
}

/**
 * One month's statement, read from the existing statement fetch and printed through
 * `printDocument`, which copies only the document into a hidden frame — `window.print()`
 * printed the console's fixed-height shell and cut the statement off after one screen.
 * The document itself is the shared `InvoiceDocument`, unchanged: its tax wording is the
 * server's (`tax_note`, `document_type`).
 */
function StatementDrawer({
  session,
  month,
  onClose,
}: {
  session: Session;
  month: string;
  onClose: () => void;
}) {
  const invoice = useClientInvoice(session, month);
  const sheet = useRef<HTMLDivElement>(null);
  const label = formatBillingMonth(month);
  return (
    <Drawer
      open
      onClose={onClose}
      title={`Statement for ${label}`}
      description="Indian Standard Time. Print it, or save it as a PDF from the print window."
      width="lg"
      initialFocus="container"
      footer={
        <button
          type="button"
          disabled={!invoice.data}
          onClick={() => {
            if (sheet.current) void printDocument(sheet.current, { title: `Statement ${month}` });
          }}
          className={PRIMARY_BUTTON}
        >
          <Printer className="h-4 w-4" aria-hidden />
          Print
        </button>
      }
    >
      {/* §52: loading is a skeleton and failure is a refusal; neither is a ₹0.00 sheet. */}
      {invoice.error ? (
        <ProblemNotice error={invoice.error} onRetry={() => void invoice.refetch()} />
      ) : !invoice.data ? (
        <Skeleton rows={8} label="Loading your statement" />
      ) : (
        <div ref={sheet}>
          <InvoiceDocument data={invoice.data} />
        </div>
      )}
    </Drawer>
  );
}
