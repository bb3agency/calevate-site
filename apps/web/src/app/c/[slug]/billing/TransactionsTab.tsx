"use client";

import { Download, Printer } from "lucide-react";

import { InvoiceDocument } from "@/components/invoiceDocument";
import {
  Card,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  istDateStamp,
} from "@/components/ui";
import { useClientInvoice } from "@/lib/api/invoice";
import { useWalletLedger } from "@/lib/api/wallet";
import type { Session } from "@/lib/api/client";

import { WalletLedgerPanel } from "./WalletLedgerPanel";
import { walletStatementCsv } from "./statementCsv";

/**
 * TRANSACTIONS — every movement on the wallet, a receipt for each payment, and the
 * month's statement.
 *
 * The Transactions tab of the billing hub (D-525). It answers the question a client asks
 * with a bank statement open beside them — "what did you take, and when" — and it holds
 * the two DOCUMENTS this product can produce:
 *
 * 1. **A receipt per payment**, opened from the history below (`ReceiptSheet`). It is a
 *    print view, not a download: the document is real HTML with `print:` rules and the
 *    browser's own "Save as PDF" is the file.
 * 2. **The month's statement** — `GET /v1/billing/invoice`, the SAME computation and the
 *    SAME renderer the admin console prints (`components/invoiceDocument.tsx`), so what a
 *    client prints is byte-for-byte what ops prints.
 *
 * plus one thing neither of them is: a **CSV of the movements**, for the client who
 * reconciles in a spreadsheet. `statementCsv.ts` argues why the browser builds it and why
 * the sentence beside the button says exactly which rows are in it.
 *
 * ## THE STATEMENT IS A BILL OF SUPPLY, AND THE DOCUMENT SAYS SO ITSELF
 *
 * Calevate is not registered for GST (`billing/gst.py`: a sole proprietor, not registered
 * and not required to be at present turnover), so under CGST s.32 no tax may be collected
 * and under Rule 49 what is issued is a bill of supply, which confers no input tax credit.
 * `document_type` is the SERVER's field and the heading is rendered from it — the browser
 * never writes the words "tax invoice" itself, because a sheet that looks like one and is
 * not is worse than one that admits what it is. The Overview tab states the same position
 * in plain words BEFORE a client buys.
 *
 * ## Permissions, split across the tab
 *
 * The history and its receipts are `wallet:read`, which `staff` holds. The statement is
 * `billing:read`, which staff does not — spend is an owner's business (SEC-COMP §5) — so
 * a staff member gets the movements and a sentence where the statement would be, rather
 * than a 403 that reads like an outage.
 *
 * ## It computes nothing
 *
 * Not one figure on this tab is arithmetic done here. The ledger rows are the server's,
 * the statement's totals and its GST split are the server's, and the CSV writes the
 * digits it was given (hard rule 7 reaches the browser).
 */
export function TransactionsTab({
  session,
  month,
  onMonthChange,
  billingRefused,
}: {
  session: Session;
  /** The IST billing month the statement is showing, `YYYY-MM`. */
  month: string;
  onMonthChange: (month: string) => void;
  /** True when this session does NOT hold `billing:read`. */
  billingRefused: boolean;
}) {
  return (
    <div className="space-y-5">
      <WalletExport session={session} />
      <WalletLedgerPanel session={session} />
      <Statement
        session={session}
        month={month}
        onMonthChange={onMonthChange}
        refused={billingRefused}
      />
    </div>
  );
}

/**
 * The CSV button, and the sentence that keeps it honest.
 *
 * It reads the SAME query key the table below reads, so it costs no second request —
 * TanStack serves it from the cache — and it can therefore say exactly how many rows the
 * file will hold. A button that silently exports "the last 50" while a client believes
 * they have their whole history is the kind of quiet wrongness a reconciliation finds six
 * weeks later.
 *
 * Disabled with a reason rather than hidden while the history is loading or empty: a
 * control that appears and disappears is one a client cannot find twice.
 */
function WalletExport({ session }: { session: Session }) {
  const ledger = useWalletLedger(session);

  /* §52, and the two arms are deliberately different shapes. IN FLIGHT: nothing at all,
     because the panel below is already announcing its own skeleton and a second live
     region saying the same thing is noise to a screen reader. FAILED: also nothing —
     `WalletLedgerPanel` renders the server's refusal directly underneath, and a second
     copy of it would tell a client their history failed to load twice. What must NOT
     happen is the third thing, which is what the guard caught: `?? []` here would have
     printed "there is nothing to download" over a read that FAILED, which is a claim
     about an account rather than about a request. */
  if (ledger.isPending || ledger.isError) return null;
  const entries = ledger.data.entries;

  const download = () => {
    /* The BOM is not decoration: Excel does not sniff UTF-8, and without U+FEFF a rupee
       or a Telugu agent name opens as mojibake. Same reasoning as the leads export
       (`lib/api/leads.ts`), which is where this repo already settled the question. */
    const blob = new Blob(["﻿", walletStatementCsv(entries)], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `calevate-transactions-${istDateStamp()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-ink-muted">
        {entries.length === 0
          ? "There is nothing to download yet."
          : `The ${formatCount(entries.length)} most recent movements on your credit, newest first.`}
      </p>
      <button
        type="button"
        disabled={entries.length === 0}
        onClick={download}
        className={SECONDARY_BUTTON_SM}
      >
        <Download className="mr-1.5 inline h-4 w-4" aria-hidden />
        Download these as a spreadsheet
      </button>
    </div>
  );
}

/**
 * The month's statement — the document, not a client-flavoured summary of one.
 *
 * It does not WRITE. Rendering a statement used to append the onboarding setup fee the
 * first time anyone opened it (D-64); that moved to a scheduled job, and putting a side
 * effect back on this path would mean a support person in a read-only "view as client"
 * session (D-22) triggering a billing write by opening a tab.
 */
function Statement({
  session,
  month,
  onMonthChange,
  refused,
}: {
  session: Session;
  month: string;
  onMonthChange: (month: string) => void;
  refused: boolean;
}) {
  const invoice = useClientInvoice(session, month);

  if (refused) {
    return (
      <Card title="Your statement">
        <RestrictionNote reason="Statements are limited to the account owner. Ask them to share this month's statement, or to give you owner access." />
      </Card>
    );
  }

  const data = invoice.data;

  return (
    <Card title="Your statement">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <p className="text-sm text-ink-muted">
          Your statement for a billing month, in Indian Standard Time. Print it, or save it
          as a PDF from the print window.
        </p>
        <div className="flex items-center gap-2">
          <input
            type="month"
            value={month}
            onChange={(event) => onMonthChange(event.target.value)}
            className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
            aria-label="Billing month for the statement"
          />
          <button
            type="button"
            // Disabled until there is a statement: printing a skeleton or an error box
            // produces a sheet of paper that looks like a statement and is not one.
            disabled={!data}
            onClick={() => window.print()}
            className={SECONDARY_BUTTON_SM}
          >
            <Printer className="mr-1.5 inline h-4 w-4" aria-hidden />
            Print
          </button>
        </div>
      </div>

      {invoice.error && (
        <ProblemNotice error={invoice.error} onRetry={() => void invoice.refetch()} />
      )}

      {/* §52: loading is a skeleton, failure is a refusal, and neither is a ₹0.00
          statement. "You owe nothing" is a claim about a month's business, and a 500 is
          not evidence for it — least of all on a printable sheet. */}
      <div className="mt-4">
        {!data ? (
          invoice.error ? null : <Skeleton rows={8} label="Loading your statement" />
        ) : (
          <InvoiceDocument data={data} />
        )}
      </div>
    </Card>
  );
}
