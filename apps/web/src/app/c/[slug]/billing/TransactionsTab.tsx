"use client";

import { Download } from "lucide-react";

import { SECONDARY_BUTTON_SM, istDateStamp } from "@/components/ui";
import { useWalletLedger } from "@/lib/api/wallet";
import type { Session } from "@/lib/api/client";

import { WalletLedgerPanel } from "./WalletLedgerPanel";
import type { TierLabels } from "./lots";
import { walletStatementCsv } from "./statementCsv";

/**
 * TRANSACTIONS — every movement on the wallet, with a receipt for each payment and a CSV
 * of the movements for the client who reconciles in a spreadsheet.
 *
 * The history and its receipts are `wallet:read`, which `staff` holds; the month's
 * statements are `billing:read` and live in the Statements view. The view computes
 * nothing: every figure is the server's string through `formatINR` (hard rule 7).
 */
export function TransactionsTab({
  session,
  labels,
}: {
  session: Session;
  labels: TierLabels | undefined;
}) {
  return (
    <WalletLedgerPanel
      session={session}
      labels={labels}
      action={<WalletExport session={session} />}
    />
  );
}

/**
 * The CSV of what the history shows. Nothing while the history loads or fails: the panel
 * below already shows its own skeleton or refusal, and "there is nothing to download"
 * over a read that FAILED would be a claim about the account rather than the request.
 */
function WalletExport({ session }: { session: Session }) {
  const ledger = useWalletLedger(session);
  if (ledger.isPending || ledger.isError) return null;
  const entries = ledger.data.entries;
  if (entries.length === 0) {
    return <span className="text-xs text-ink-muted">There is nothing to download yet.</span>;
  }
  const download = () => {
    // A BOM so Excel opens the file as UTF-8 — a ₹ or a Telugu agent name otherwise opens
    // as mojibake (the leads export settled the same question, `lib/api/leads.ts`).
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
    <button type="button" onClick={download} className={SECONDARY_BUTTON_SM}>
      <Download className="h-4 w-4" aria-hidden />
      Download CSV
    </button>
  );
}
