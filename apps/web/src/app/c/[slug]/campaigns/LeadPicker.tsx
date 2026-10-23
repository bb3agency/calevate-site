"use client";

import { DatePicker } from "@/components/arc/calendar";
import { ChipGroup } from "@/components/arc/chip-group";
import { addDays, todayIST } from "@/components/arc/ist-dates";
import { FIELD_HINT, FIELD_LABEL, formatCount, istDateStamp, istDateToInstant } from "@/components/ui";
import { useLeadPool, type LeadFilter } from "@/lib/api/campaigns";
import { useClientSession } from "@/lib/api/session";
import type { Lead } from "@/lib/api/leads";
import { sourceLabel } from "@/lib/leadLabels";

import { STATUSES } from "../leads/StatusSelect";

const SOURCES: Lead["source"][] = ["inbound_call", "outbound_call", "webhook", "campaign", "manual"];

/** The IST day an instant falls on, or null. */
function dayOf(instant: string | null | undefined): string | null {
  return instant ? istDateStamp(new Date(instant)) : null;
}

/**
 * PEOPLE FROM YOUR LEADS (D-773): choose CRM leads by stage, where they came from and when.
 *
 * Only the filter leaves the browser; the server reads the leads' numbers itself
 * (`POST …/contacts/from-leads`), and says first how many leads the filter matches
 * (`GET /v1/campaigns/lead-pool`). Leads carry no tags, so there is no tag filter. Dates
 * are IST days; `created_until` is the start of the day AFTER the one picked, so the
 * picked day is included.
 */
export function LeadPicker({
  value,
  onChange,
}: {
  value: LeadFilter;
  onChange: (value: LeadFilter) => void;
}) {
  const session = useClientSession();
  const pool = useLeadPool(session, value, true);
  const since = dayOf(value.created_since);
  const untilExclusive = dayOf(value.created_until);
  const until = untilExclusive ? addDays(untilExclusive, -1) : null;
  const today = todayIST();
  return (
    <div className="space-y-4">
      <div>
        <p aria-hidden className={FIELD_LABEL}>
          Stage
        </p>
        <ChipGroup
          mode="multiple"
          label="Stage"
          className="mt-1.5"
          value={value.statuses ?? []}
          onChange={(next) => onChange({ ...value, statuses: STATUSES.filter((s) => next.includes(s)) })}
          chips={STATUSES.map((status) => ({ value: status, label: status.charAt(0).toUpperCase() + status.slice(1) }))}
          allLabel="Any stage"
        />
      </div>
      <div>
        <p aria-hidden className={FIELD_LABEL}>
          Came from
        </p>
        <ChipGroup
          mode="multiple"
          label="Came from"
          className="mt-1.5"
          value={value.sources ?? []}
          onChange={(next) => onChange({ ...value, sources: SOURCES.filter((s) => next.includes(s)) })}
          chips={SOURCES.map((source) => ({ value: source, label: sourceLabel(source) }))}
          allLabel="Anywhere"
        />
      </div>
      <div className="grid max-w-md grid-cols-1 gap-3 sm:grid-cols-2">
        <DatePicker
          label="Added on or after"
          value={since}
          onChange={(day) => onChange({ ...value, created_since: day ? istDateToInstant(day) : null })}
          max={until ?? today}
          clearable
          placeholder="Any day"
        />
        <DatePicker
          label="Added on or before"
          value={until}
          onChange={(day) =>
            onChange({ ...value, created_until: day ? istDateToInstant(addDays(day, 1)) : null })
          }
          min={since ?? undefined}
          max={today}
          clearable
          placeholder="Any day"
        />
      </div>
      <p role="status" className={FIELD_HINT}>
        {pool.data
          ? pool.data.matching > pool.data.limit
            ? `${formatCount(pool.data.matching)} leads match. One campaign takes up to ${formatCount(pool.data.limit)} at a time, so narrow it down.`
            : `${formatCount(pool.data.matching)} ${pool.data.matching === 1 ? "lead matches" : "leads match"}. Anyone on your do-not-call list is skipped when the campaign starts.`
          : pool.error
            ? "We could not count the matching leads."
            : <span className="text-shimmer">Counting matching leads…</span>}
      </p>
    </div>
  );
}

/** True when the picker's count says the filter can be added. */
export function leadPoolFits(matching: number | undefined, limit: number | undefined): boolean {
  return matching !== undefined && limit !== undefined && matching > 0 && matching <= limit;
}
