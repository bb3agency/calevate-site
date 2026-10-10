"use client";

import { EmptySketch } from "@/components/console/emptySketch";
import { useState } from "react";

import { Section } from "@/components/console/section";
import { FilterChip, ScrollRegion, formatINR, formatIST } from "@/components/ui";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { RowMenu } from "@/components/console/rowMenu";
import {
  CREDIT_REASON_LABEL,
  LEDGER_LIMIT,
  correctableEntries,
  creditReasonLabel,
  isFullyReversed,
  type Credits,
  type LedgerEntry,
  type Payment,
} from "@/lib/api/credits";
import type { CreditLot } from "@/lib/api/creditLots";

import type { Act } from "./acts";
import { LotOrigin, lotRates } from "./lots";
import { NoPackLadder } from "./OverrideForm";

/**
 * THE WALLET, THREE WAYS — the ledger's rows, the bank transfers behind them, and the
 * priced lots the balance is made of. Peer views of one wallet, so one segmented control
 * (D-655) rather than three stacked cards; the ledger opens first because it is the record
 * every write on this screen appends to.
 *
 * Each row's menu opens the act that repairs THAT row with it pre-selected; the act's own
 * select still shows the choice, so a mis-click is visible before anything is typed.
 */
/**
 * ONE HISTORY, NEWEST FIRST, WITH A TYPE FILTER (founder, 10 Oct 2026). "Payments" is the
 * one filter that groups rather than narrows: a restated payment is two ledger rows and one
 * bank transfer, and the transfer is what reconciliation keys on — so that filter shows one
 * line per transfer, with its restate and refund actions. The lots are not history (they
 * are what the balance is made of now) and have their own section below.
 */
type Filter = "all" | "payments" | "usage" | "adjustment" | "refund";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "payments", label: "Payments" },
  { value: "usage", label: CREDIT_REASON_LABEL.usage },
  { value: "adjustment", label: "Adjustments" },
  { value: "refund", label: CREDIT_REASON_LABEL.refund },
];

export function WalletHistory({
  wallet,
  onAct,
}: {
  wallet: Credits;
  onAct: (act: Act) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  return (
    <>
      <Section title="Wallet history" description="Every entry on this client's wallet, newest first.">
        <ScrollRegion label="Filter the history" className="-mx-1 px-1 pb-3 [scrollbar-width:none]">
          <div className="flex w-max items-center gap-1.5">
            {FILTERS.map((option) => (
              <FilterChip
                key={option.value}
                label={option.label}
                active={filter === option.value}
                onClick={() => setFilter(option.value)}
              />
            ))}
          </div>
        </ScrollRegion>
        {filter === "payments" ? (
          <PaymentsView wallet={wallet} onAct={onAct} />
        ) : (
          <LedgerView wallet={wallet} onAct={onAct} reason={filter === "all" ? null : filter} />
        )}
      </Section>
      <Section title="Credit lots — what the balance is made of">
        <LotsView wallet={wallet} onAct={onAct} />
      </Section>
    </>
  );
}

function ViewCaption({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 pb-2">
      <h3 className="text-meta font-medium text-ink-muted">{title}</h3>
      {children}
    </div>
  );
}

function signed(delta: string): string {
  // The sign is in the DIGITS (`formatINR` keeps a leading minus); a credit gets its "+".
  return `${delta.startsWith("-") ? "" : "+"}${formatINR(delta)}`;
}

function LedgerView({
  wallet,
  onAct,
  reason,
}: {
  wallet: Credits;
  onAct: (act: Act) => void;
  /** The one entry type shown, or null for every entry. */
  reason: string | null;
}) {
  if (wallet.entries.length === 0) {
    // A REAL empty state, reachable only through a successful read: the failed read is
    // `LedgerUnreadable` and never arrives here.
    return (
      <EmptyState
        message="Nothing has ever been written to this ledger"
        illustration={
          <EmptySketch kind="deliveries" />
        }
      />
    );
  }
  const rows = reason === null ? wallet.entries : wallet.entries.filter((entry) => entry.reason === reason);
  if (rows.length === 0) {
    return <EmptyState message="No entry of this type among the newest on the ledger." />;
  }
  const correctable = new Set(correctableEntries(wallet.entries).map((entry) => entry.id));
  const columns: DataColumn<LedgerEntry>[] = [
    {
      id: "when",
      header: "When",
      cell: (entry) => <span className="whitespace-nowrap">{formatIST(entry.occurred_at)}</span>,
    },
    {
      id: "movement",
      header: "Movement",
      align: "right",
      cell: (entry) => (
        // Colour reinforces the sign and is never the only signal.
        <span
          className={`whitespace-nowrap tabular-nums ${
            entry.delta_inr.startsWith("-") ? "text-ink" : "text-brand-deep dark:text-brand-bright"
          }`}
        >
          {signed(entry.delta_inr)}
        </span>
      ),
    },
    { id: "what", header: "What", cell: (entry) => creditReasonLabel(entry.reason) },
    {
      id: "ref",
      header: "Reference",
      hideBelow: "md",
      cell: (entry) => <span className="break-all font-mono text-meta">{entry.ref ?? "—"}</span>,
    },
    {
      id: "after",
      header: "Balance after",
      align: "right",
      hideBelow: "sm",
      cell: (entry) => (
        <span className="whitespace-nowrap tabular-nums">{formatINR(entry.balance_after_inr)}</span>
      ),
    },
    {
      // Why an entry is, or is not, offered for correction — and the only place an
      // operator can see a line was ALREADY corrected without adding up deltas.
      id: "left",
      header: "Left to take back",
      align: "right",
      hideBelow: "sm",
      cell: (entry) => (
        <span className="whitespace-nowrap tabular-nums text-ink-muted">
          {isFullyReversed(entry) ? "fully corrected" : formatINR(entry.reversible_inr)}
        </span>
      ),
    },
    {
      id: "menu",
      header: "Actions",
      align: "right",
      cell: (entry) =>
        correctable.has(entry.id) ? (
          <RowMenu
            label={`${creditReasonLabel(entry.reason)} ${formatIST(entry.occurred_at)}`}
            items={[
              {
                id: "correct",
                label: "Correct this entry",
                onSelect: () => onAct({ kind: "correct", entryId: entry.id }),
              },
            ]}
          />
        ) : null,
    },
  ];
  return (
    <>
      <DataTable
        rows={rows}
        columns={columns}
        getRowId={(entry) => entry.id}
        label="Credit ledger, newest first"
      />
      <p className="pt-2 text-meta text-ink-muted">
        The newest {LEDGER_LIMIT}. Nothing here can be edited or removed — and the
        repeated-reference check the server makes reads the WHOLE ledger, not only what
        is shown here, so a reference missing from this list is not proof the payment is
        new.
      </p>
    </>
  );
}

function PaymentsView({ wallet, onAct }: { wallet: Credits; onAct: (act: Act) => void }) {
  if (wallet.payments.length === 0) {
    return <EmptyState message="No payment has been recorded on this wallet yet." />;
  }
  const columns: DataColumn<Payment>[] = [
    {
      id: "ref",
      header: "Reference",
      cell: (payment) => <span className="break-all font-mono text-meta">{payment.payment_ref}</span>,
    },
    {
      id: "first",
      header: "First recorded",
      hideBelow: "sm",
      cell: (payment) => <span className="whitespace-nowrap">{formatIST(payment.first_at)}</span>,
    },
    {
      id: "credited",
      header: "Credited",
      align: "right",
      cell: (payment) => (
        <span className="whitespace-nowrap tabular-nums">{formatINR(payment.credited_inr)}</span>
      ),
    },
    {
      id: "entries",
      header: "Ledger entries",
      align: "right",
      hideBelow: "sm",
      cell: (payment) => (
        <span className="tabular-nums text-ink-muted">
          {payment.entries === 1 ? "1" : `${payment.entries} — restated`}
        </span>
      ),
    },
    {
      id: "menu",
      header: "Actions",
      align: "right",
      cell: (payment) => (
        <RowMenu
          label={payment.payment_ref}
          items={[
            {
              id: "restate",
              label: "Restate this payment",
              onSelect: () => onAct({ kind: "restate", paymentRef: payment.payment_ref }),
            },
            {
              id: "refund",
              label: "Refund this payment",
              onSelect: () => onAct({ kind: "refund", paymentRef: payment.payment_ref }),
            },
          ]}
        />
      ),
    },
  ];
  return (
    <>
      <ViewCaption title="Payments — one line per bank transfer">
        <InfoTip label="Why payments and ledger rows differ">
          A payment restated after being entered for too little occupies more than one row
          on the ledger and still exactly one line here — that is what keeps the reference
          usable as the thing reconciliation keys on.
        </InfoTip>
      </ViewCaption>
      <DataTable
        rows={wallet.payments}
        columns={columns}
        getRowId={(payment) => payment.payment_ref}
        label="Bank transfers behind the ledger"
      />
      <p className="pt-2 text-meta text-ink-muted">
        Compare <span className="font-semibold">Credited</span> against the statement, one
        line to one line.
      </p>
    </>
  );
}

function LotsView({ wallet, onAct }: { wallet: Credits; onAct: (act: Act) => void }) {
  const lots = wallet.lots;
  const canReprice = wallet.override_packs.length > 0;
  const columns: DataColumn<CreditLot>[] = [
    {
      id: "left",
      header: "Credit left",
      cell: (lot) => (
        <span className="whitespace-nowrap font-medium tabular-nums text-ink">
          {formatINR(lot.credits_remaining)} left of {formatINR(lot.credits_total)}
        </span>
      ),
    },
    {
      id: "rates",
      header: "Frozen rates",
      cell: (lot) => <span className="text-meta text-ink-muted">{lotRates(lot)}</span>,
    },
    {
      id: "origin",
      header: "Opened",
      hideBelow: "md",
      cell: (lot) => (
        <span className="text-meta text-ink-muted">
          <LotOrigin lot={lot} />
          <span className="mt-0.5 block break-all font-mono text-meta">{lot.lot_id}</span>
        </span>
      ),
    },
    {
      id: "menu",
      header: "Actions",
      align: "right",
      cell: (lot) =>
        canReprice ? (
          <RowMenu
            label={`lot ${lot.lot_id}`}
            items={[
              {
                id: "reprice",
                label: "Sell at another pack's rates",
                onSelect: () => onAct({ kind: "reprice", lotId: lot.lot_id }),
              },
            ]}
          />
        ) : null,
    },
  ];
  return (
    <>
      <p className="pb-3 text-meta text-ink-muted">
        Calls are charged to the OLDEST lot first, at that lot&apos;s rate for the voice the
        agent speaks with. Restating a payment moves a lot&apos;s totals and{" "}
        <span className="font-semibold">never its rates</span> — only re-pricing a lot can
        change them.
      </p>
      {lots.length === 0 ? (
        <div>
          <EmptyState message="No open lots" />
          <p className="text-center text-meta text-ink-muted">
            Either nothing has been credited yet, or every lot has been spent. A negative
            balance is overdraft: the next payment repays it before a new lot opens.
          </p>
        </div>
      ) : (
        <>
          <DataTable
            rows={[...lots]}
            columns={columns}
            getRowId={(lot) => lot.lot_id}
            label="Credit lots, oldest spent first"
          />
          {!canReprice && (
            <div className="pt-2">
              <NoPackLadder />
            </div>
          )}
        </>
      )}
    </>
  );
}
