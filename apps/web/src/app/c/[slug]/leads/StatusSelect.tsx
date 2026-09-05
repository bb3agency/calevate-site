"use client";

import type { LeadStatus } from "@/lib/api/leads";

/**
 * ONE spelling of the pipeline stages, shared by the table, the board and the lead's own
 * page. Fixed enum (D-21): clients cannot add statuses, because analytics and the
 * hot-lead rules key off exactly these values.
 *
 * Lifted out of `leads/page.tsx` when the detail screen gained a stage control
 * (ux-audit client-daily-work LD1) — a third local copy of this list is where the drift
 * starts.
 */
export const STATUSES: LeadStatus[] = ["new", "contacted", "interested", "hot", "won", "lost"];

/**
 * The stage control. The caller supplies the accessible name (each row's names its own
 * lead) and the classes, because the table cell, the board card and the detail header
 * dress it differently while the options must never differ.
 */
export function StatusSelect({
  value,
  label,
  disabled,
  onChange,
  className,
}: {
  value: LeadStatus;
  label: string;
  disabled: boolean;
  onChange: (next: LeadStatus) => void;
  className: string;
}) {
  return (
    <select
      value={value}
      aria-label={label}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as LeadStatus)}
      className={className}
    >
      {STATUSES.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}
