// Layout adapted from Invoicely (https://github.com/legions-developer/invoicely), commit
// 820d3c51604faa10d44126e019c1fad51b54d96f, apps/web/src/components/pdf/default.tsx and
// apps/web/src/components/pdf/vercel.tsx. MIT licence, Copyright (c) 2025 Invoicely.
// Full notice: ./LICENSE.
//
// What was taken is the DESIGN: the masthead with the document number set large in a
// monospace face, the label/value metadata rows, the side-by-side party cards, the
// filled header bar over the line items, and the right-hand totals block with the total
// set largest. Their components draw a PDF through @react-pdf/renderer; these are plain
// HTML, and the PDF is the browser's own print-to-PDF via `lib/printDocument.ts`, which
// both callers already use. Taking react-pdf would add a second renderer for the same
// sheet (two drawings of one bill drift, and the first thing they drift on is a figure)
// plus its font and layout dependency tree, for no gain: an HTML table prints with
// selectable text, repeats its header row across pages, and is the same markup the
// accessibility suite already scans.
//
// Their colours were not taken. The filled bar uses slate-900 under white text rather than
// the brand green, which is 3.38:1 under white and fails WCAG 1.4.3 at this size, and no
// grey lighter than slate-600 sits on a tinted card for the same reason.

import type { ReactNode } from "react";

import clsx from "clsx";

/**
 * The paper. White with slate ink rather than theme tokens, because browsers drop
 * background colours when printing and a themed sheet prints blank in dark mode; the
 * reasoning is `invoiceDocument.tsx`'s and applies to every billing document.
 */
export function DocumentSheet({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "rounded-card bg-white text-slate-900 print:rounded-none print:p-0 print:shadow-none",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * The document's name and its number. The name is the `<h1>` on its own, with nothing
 * else inside it, because the heading text is a legal claim (BILL OF SUPPLY, Receipt) and
 * tests find it by its exact words.
 */
export function Masthead({
  title,
  numberLabel,
  number,
}: {
  title: string;
  numberLabel: string;
  number: string;
}) {
  return (
    <header className="border-b border-slate-200 pb-4">
      <h1 className="text-sm font-bold uppercase tracking-[0.2em]">{title}</h1>
      <p className="mt-3 text-xs text-slate-600">{numberLabel}</p>
      <p className="break-all font-mono text-2xl font-semibold tracking-tight">{number}</p>
    </header>
  );
}

/** Label/value pairs under the masthead: dates, the billing month, what was paid for. */
export function MetaRows({ rows }: { rows: ReadonlyArray<readonly [string, ReactNode]> }) {
  return (
    <dl className="mt-4 space-y-1 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="flex gap-2">
          <dt className="font-semibold sm:min-w-[7.5rem]">{label}</dt>
          <dd className="text-slate-600">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** One party to the document, or the place of supply, on a tinted card. */
export function PartyCard({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="rounded bg-slate-100 p-3 text-sm break-inside-avoid">
      <h2 className="text-xs font-semibold uppercase tracking-wide">{heading}</h2>
      <div className="mt-1.5 space-y-0.5">{children}</div>
    </section>
  );
}

/** A party's secondary line: an address, an email, a GSTIN sentence. */
export function PartyDetail({ children, preLine = false }: { children: ReactNode; preLine?: boolean }) {
  return (
    <p className={clsx("text-xs text-slate-700", preLine && "whitespace-pre-line")}>{children}</p>
  );
}

/**
 * The totals block, right-aligned under the line items. Every value is already formatted
 * by the caller from the server's decimal string; nothing here adds anything up.
 */
export function TotalsBlock({
  rows,
  totalLabel,
  total,
}: {
  rows: ReadonlyArray<readonly [string, string]>;
  totalLabel: string;
  total: string;
}) {
  return (
    <dl className="w-full space-y-1 text-sm break-inside-avoid sm:max-w-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-4">
          <dt className="text-slate-600">{label}</dt>
          <dd className="font-mono tabular-nums">{value}</dd>
        </div>
      ))}
      <div
        className={clsx(
          "flex items-baseline justify-between gap-4",
          rows.length > 0 && "mt-2 border-t border-slate-200 pt-2",
        )}
      >
        <dt className="text-xs font-semibold uppercase tracking-wide">{totalLabel}</dt>
        <dd className="font-mono text-xl font-bold tracking-tight tabular-nums">{total}</dd>
      </div>
    </dl>
  );
}
