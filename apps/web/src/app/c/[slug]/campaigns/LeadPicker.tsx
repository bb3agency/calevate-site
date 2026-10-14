"use client";

import { FIELD, FIELD_HINT, FIELD_LABEL, FilterChip, formatCount, istDateToInstant } from "@/components/ui";
import { useLeadPool, type LeadFilter } from "@/lib/api/campaigns";
import { useClientSession } from "@/lib/api/session";
import type { Lead } from "@/lib/api/leads";
import { sourceLabel } from "@/lib/leadLabels";

import { STATUSES } from "../leads/StatusSelect";

const SOURCES: Lead["source"][] = ["inbound_call", "outbound_call", "webhook", "campaign", "manual"];

/** The day a `created_since`/`created_until` instant starts, as `<input type="date">` holds it. */
function dayOf(instant: string | null | undefined): string {
  if (!instant) return "";
  return new Date(new Date(instant).getTime() + 5.5 * 3_600_000).toISOString().slice(0, 10);
}

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

/**
 * PEOPLE FROM YOUR LEADS (D-773): choose CRM leads by stage, where they came from and when.
 *
 * Only the filter leaves the browser; the server reads the leads' numbers itself
 * (`POST …/contacts/from-leads`), and says first how many leads the filter matches
 * (`GET /v1/campaigns/lead-pool`). Leads carry no tags, so there is no tag filter. Dates
 * are IST days, the `until` day included.
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
  const statuses = value.statuses ?? [];
  const sources = value.sources ?? [];
  const until = dayOf(value.created_until);
  return (
    <div className="space-y-4">
      <fieldset>
        <legend className={FIELD_LABEL}>Stage</legend>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {STATUSES.map((status) => (
            <FilterChip
              key={status}
              label={status.charAt(0).toUpperCase() + status.slice(1)}
              active={statuses.includes(status)}
              onClick={() => onChange({ ...value, statuses: toggle(statuses, status) })}
            />
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className={FIELD_LABEL}>Came from</legend>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {SOURCES.map((source) => (
            <FilterChip
              key={source}
              label={sourceLabel(source)}
              active={sources.includes(source)}
              onClick={() => onChange({ ...value, sources: toggle(sources, source) })}
            />
          ))}
        </div>
      </fieldset>
      <div className="grid max-w-md grid-cols-2 gap-3">
        <label className="block">
          <span className={FIELD_LABEL}>Added on or after</span>
          <input
            type="date"
            value={dayOf(value.created_since)}
            onChange={(e) => onChange({ ...value, created_since: istDateToInstant(e.target.value) })}
            className={FIELD}
          />
        </label>
        <label className="block">
          <span className={FIELD_LABEL}>Added on or before</span>
          <input
            type="date"
            value={until ? dayOf(new Date(new Date(value.created_until!).getTime() - 86_400_000).toISOString()) : ""}
            onChange={(e) => {
              const start = istDateToInstant(e.target.value);
              onChange({
                ...value,
                created_until: start ? new Date(new Date(start).getTime() + 86_400_000).toISOString() : null,
              });
            }}
            className={FIELD}
          />
        </label>
      </div>
      <p role="status" className={FIELD_HINT}>
        {pool.data
          ? pool.data.matching > pool.data.limit
            ? `${formatCount(pool.data.matching)} leads match. One campaign takes up to ${formatCount(pool.data.limit)} at a time, so narrow it down.`
            : `${formatCount(pool.data.matching)} ${pool.data.matching === 1 ? "lead matches" : "leads match"}. Anyone on your do-not-call list is skipped when the campaign starts.`
          : pool.error
            ? "We could not count the matching leads."
            : "Counting matching leads…"}
      </p>
    </div>
  );
}

/** True when the picker's count says the filter can be added. */
export function leadPoolFits(matching: number | undefined, limit: number | undefined): boolean {
  return matching !== undefined && limit !== undefined && matching > 0 && matching <= limit;
}
