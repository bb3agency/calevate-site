import { AlertTriangle, Layers, Receipt, Timer, Wallet } from "lucide-react";

import { Panel, Tag, Window } from "@/components/marketing/home/mockups/kit";

/**
 * The client billing console (`app/c/[slug]/billing/**`), re-drawn for `/pricing`.
 *
 * Labels are the console's own: the tab names (`billing/tabs.ts`), "Calling credit" and
 * "How long this lasts" (`WalletHero.tsx`), "Your credit and what it costs a minute" and
 * "Spent first" (`LotsPanel.tsx`), "Your spending limit" and its three rows
 * (`UsageTab.tsx::SpendingLimit`), "Your credit history" and its columns
 * (`WalletLedgerPanel.tsx`), and the ledger reasons (`lib/api/wallet.ts`).
 *
 * NO RUPEE FIGURE IS DRAWN, and that is a rule of this page rather than a style. Every ₹
 * figure on `/pricing` must be one the rate card sent (`marketingPages.test.tsx`, "invents
 * no figure"), so a sample balance would be an invented price however it was captioned.
 * Amounts are masked the way the sample phone numbers are; minutes, days and dates are
 * the illustrative data. The voice name is the one the card sent (`tierLabel`), never
 * typed here, and only the voice an agent can be put on today is drawn.
 */

/** A rupee amount the illustration does not state. Same idea as `MaskedPhone`. */
export function MaskedAmount({ className = "" }: { className?: string }) {
  return (
    <span className={`tabular-nums tracking-wider text-ink-faint ${className}`}>₹ ••,•••</span>
  );
}

const TABS = ["Overview", "Credits", "Transactions", "Usage"] as const;

function BillingTabs({ active }: { active: (typeof TABS)[number] }) {
  return (
    <span className="flex gap-1 overflow-hidden border-b border-line px-3 pt-2 text-[12px] font-medium">
      {TABS.map((tab) => (
        <span
          key={tab}
          className={`shrink-0 border-b-2 px-2.5 pb-2 ${
            tab === active ? "border-brand-strong text-ink" : "border-transparent text-ink-muted"
          } ${tab === "Transactions" ? "hidden sm:block" : ""}`}
        >
          {tab}
        </span>
      ))}
    </span>
  );
}

/** Overview tab: the balance, the runway, and the lot queue it is drawn from. */
export function CreditOverviewMock({ voiceLabel }: { voiceLabel: string | null }) {
  const lots = [
    { bought: "4 Aug", spent: "w-4/5", first: true },
    { bought: "2 Sep", spent: "w-0", first: false },
  ] as const;
  return (
    <Window title="Billing" className="mk-rise mk-s1">
      <BillingTabs active="Overview" />
      <span className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5">
        <Panel className="mk-rise mk-s2 p-4">
          <span className="flex items-center gap-2 text-[12px] font-medium text-ink-muted">
            <Wallet aria-hidden className="h-3.5 w-3.5 text-brand" />
            Calling credit
          </span>
          <MaskedAmount className="mt-2 block text-2xl font-bold" />
        </Panel>
        <span className="mk-rise mk-s3 block rounded-xl border border-line bg-brand-soft dark:bg-brand-strong/20 p-4 shadow-card">
          <span className="flex items-center gap-2 text-[12px] font-medium text-brand-strong dark:text-brand-bright">
            <Timer aria-hidden className="h-3.5 w-3.5" />
            How long this lasts
          </span>
          <span className="mt-2 block text-[15px] leading-snug font-semibold text-ink">
            About 23 days of calling left at your recent pace
          </span>
          {voiceLabel !== null && (
            <span className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-muted">
              <Layers aria-hidden className="h-3 w-3 shrink-0" />
              <span>
                about <span className="font-semibold tabular-nums text-ink">1,140 minutes</span> on{" "}
                {voiceLabel}
              </span>
            </span>
          )}
        </span>
      </span>
      <span className="mk-rise mk-s4 block border-t border-line px-4 pt-3 pb-4 sm:px-5">
        <span className="block text-[13px] font-semibold text-ink">
          Your credit and what it costs a minute
        </span>
        <span className="mt-1 block text-[11px] text-ink-muted">
          Each purchase keeps the per-minute rates it was bought at.
        </span>
        <span className="mt-3 flex items-center gap-3 border-b border-line pb-1.5 text-[10px] font-semibold tracking-wider text-ink-faint uppercase">
          <span className="flex-1">Credit left</span>
          <span className="w-20 shrink-0 text-right">Bought</span>
        </span>
        {lots.map((lot) => (
          <span key={lot.bought} className="flex items-center gap-3 border-b border-line/60 py-2.5 text-[12px]">
            <span className="flex min-w-0 flex-1 flex-col gap-1.5">
              <span className="flex items-center gap-2">
                <MaskedAmount className="font-medium" />
                {lot.first && <Tag tone="brand">Spent first</Tag>}
              </span>
              <span className="block h-1.5 w-full overflow-hidden rounded-full bg-brand/15">
                <span className={`block h-full rounded-full bg-ink/20 ${lot.spent}`} />
              </span>
            </span>
            <span className="w-20 shrink-0 text-right text-ink-muted">{lot.bought}</span>
          </span>
        ))}
      </span>
    </Window>
  );
}

/** Usage tab: the client's own limit beside the one in their arrangement. */
export function SpendingLimitMock() {
  const rows = [
    { label: "In force this month", value: "3,000 minutes", strong: true },
    { label: "Limit on your plan", value: "5,000 minutes", strong: false },
  ] as const;
  return (
    <Panel className="mk-rise mk-s2 p-4 sm:p-5">
      <span className="block text-[13px] font-semibold text-ink">Your spending limit</span>
      <span className="mt-3 flex flex-col gap-2 text-[12px]">
        {rows.map((row) => (
          <span key={row.label} className="flex items-baseline justify-between gap-3">
            <span className="text-ink-muted">{row.label}</span>
            <span className={`tabular-nums ${row.strong ? "font-semibold text-ink" : "text-ink"}`}>
              {row.value}
            </span>
          </span>
        ))}
        <span className="flex items-baseline justify-between gap-3">
          <span className="text-ink-muted">Used so far</span>
          <span className="flex items-baseline gap-1 tabular-nums text-ink">
            1,284 min · <MaskedAmount />
          </span>
        </span>
      </span>
      <span className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4">
        <span className="flex min-w-0 flex-1 flex-col gap-1 text-[11px] font-medium text-ink-muted">
          <span>Minutes</span>
          <span className="rounded-md bg-surface px-2.5 py-1.5 text-[12px] tabular-nums text-ink ring-1 ring-brand/50">
            3000
          </span>
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1 text-[11px] font-medium text-ink-muted">
          <span>Spend (₹)</span>
          <span className="rounded-md bg-surface px-2.5 py-1.5 text-[12px] text-ink-faint ring-1 ring-line">
            no limit
          </span>
        </span>
        <span className="rounded-md bg-brand-strong px-3 py-1.5 text-[12px] font-semibold text-white">
          Save limit
        </span>
      </span>
    </Panel>
  );
}

/** Overview tab, the morning the balance crosses the warning line. */
export function LowCreditNoticeMock() {
  return (
    <span className="mk-rise mk-s3 block rounded-xl border border-amber-200 bg-amber-50 p-4 text-[12px] text-amber-950 shadow-card dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200">
      <span className="flex items-start gap-2 font-semibold">
        <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Your calling credit is running low.
      </span>
      <span className="mt-1.5 block pl-5.5 text-amber-900 dark:text-amber-200">We email the account owner at this point too.</span>
    </span>
  );
}

/** Transactions tab: every movement of credit is a line of its own. */
export function CreditHistoryMock() {
  const entries = [
    { when: "28 Sep", what: "Calls", sign: "−" },
    { when: "27 Sep", what: "Calls", sign: "−" },
    { when: "2 Sep", what: "Credit added", sign: "+" },
    { when: "1 Sep", what: "Calls", sign: "−" },
  ] as const;
  return (
    <Panel className="mk-rise mk-s2 p-4 sm:p-5">
      <span className="block text-[13px] font-semibold text-ink">Your credit history</span>
      <span className="mt-3 flex items-center gap-2 sm:gap-3 border-b border-line pb-1.5 text-[10px] font-semibold tracking-wider text-ink-faint uppercase">
        <span className="w-14 shrink-0">When</span>
        <span className="min-w-0 flex-1">What</span>
        <span className="w-20 shrink-0 text-right">Amount</span>
        <span className="hidden w-20 shrink-0 text-right sm:block">Balance after</span>
        <span className="w-4 shrink-0" />
      </span>
      {entries.map((entry, i) => (
        <span
          key={`${entry.when}-${i}`}
          className="flex items-center gap-2 border-b border-line/60 py-2.5 text-[12px] last:border-b-0 sm:gap-3"
        >
          <span className="w-14 shrink-0 text-ink-muted">{entry.when}</span>
          <span className="min-w-0 flex-1 truncate text-ink">{entry.what}</span>
          <span className="flex w-20 shrink-0 items-baseline justify-end gap-0.5 text-ink">
            {entry.sign}
            <MaskedAmount />
          </span>
          <span className="hidden w-20 shrink-0 justify-end sm:flex">
            <MaskedAmount />
          </span>
          <span className="flex w-4 shrink-0 justify-end text-ink-faint">
            {entry.what === "Credit added" && <Receipt aria-hidden className="h-3.5 w-3.5" />}
          </span>
        </span>
      ))}
    </Panel>
  );
}
