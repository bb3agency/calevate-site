import type { ReactNode } from "react";

/** A block heading inside a card: sentence case, no icon tile (the shared one has both). */
export function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="mb-1.5 text-sm font-semibold text-ink">{children}</h3>;
}

/**
 * What is on file, as label/value pairs. Rows whose value is empty are left out rather than
 * printed as "—": these records grow field by field, and a column of dashes reads as a
 * form nobody filled in.
 */
export function FactList({ rows }: { rows: { label: string; value: string | null }[] }) {
  const shown = rows.filter((row) => row.value !== null && row.value !== "");
  return (
    <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
      {shown.map((row) => (
        <div key={row.label} className="min-w-0 text-xs">
          <dt className="text-ink-muted">{row.label}</dt>
          <dd className="mt-0.5 break-all font-medium text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
