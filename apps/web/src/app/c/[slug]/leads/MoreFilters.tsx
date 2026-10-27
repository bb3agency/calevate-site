"use client";

import { useId, useState } from "react";
import { X } from "lucide-react";

import { DateRangePicker, type DateRange } from "@/components/arc/calendar";
import { SavedViewBar } from "@/components/console/savedViewBar";
import { TEXT_ACTION } from "@/components/console/section";
import { Disclosure, FIELD, FIELD_INLINE, FIELD_LABEL, FilterChip, istDateStamp } from "@/components/ui";
import {
  useDeleteView,
  useSaveView,
  type CapturedFilter,
  type LeadFacets,
  type SavedView,
  type SavedViewBody,
  type SavedViewFilters,
} from "@/lib/api/leads";
import { useClientRealm } from "@/lib/api/session";
import { DIRECTIONS, FOLLOW_UP, OUTCOMES } from "@/lib/callFilters";
import { describeViewDays, endsToday } from "@/lib/viewDays";
import { daysBetween } from "@/components/arc/ist-dates";

import { FacetPanel } from "./FacetPanel";

/**
 * EVERYTHING USED NOW AND THEN, behind one fold (UX-DOCTRINE §3: low consequence, touched
 * rarely): the owner filter, the filters over calls and captured answers, and saved views.
 * Its title says how many of them are narrowing the rows, and it opens by itself while one
 * is, so a filter in force is never out of sight. The stage chips stay outside it: they
 * are the filter a client uses most.
 */
export function MoreFilters({
  inUse,
  myUserId,
  assignedToMe,
  onAssignedToMe,
  impersonating,
  facets,
  facetValues,
  onFacetValues,
  views,
  activeViewId,
  canSaveView,
  saveViewReason,
  onApplyView,
  viewFilters,
  columns,
  calls,
}: {
  inUse: number;
  /** The signed-in person's id; no id, no "Assigned to me". */
  myUserId: string | undefined;
  assignedToMe: boolean;
  onAssignedToMe: (on: boolean) => void;
  /** The server's answer; undefined until `/v1/me` has answered, and then no line shows. */
  impersonating: boolean | undefined;
  facets: { data: LeadFacets | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  facetValues: Record<string, string[]>;
  onFacetValues: (next: Record<string, string[]>) => void;
  views: { data: SavedView[] | undefined; error: unknown };
  activeViewId: string | undefined;
  canSaveView: boolean;
  saveViewReason: string | null;
  onApplyView: (view: SavedView | undefined) => void;
  /** The screen's filters as a view stores them (`useLeadsLens.viewFilters`). */
  viewFilters: (rolling: boolean) => SavedViewFilters;
  /** The chosen columns, or null for "whatever this agent has". */
  columns: string[] | null;
  /** When the lead came in and what its calls say (D-893); the same lens Pip acts on. */
  calls: LeadCallFilters;
}) {
  const { session } = useClientRealm();
  const today = istDateStamp();
  const moving = [calls.created, calls.lastCall].filter(
    (range): range is DateRange => range !== null && endsToday(range, today),
  );
  return (
    <Disclosure
      variant="inline"
      headingLevel={2}
      title={inUse > 0 ? `More filters · ${inUse} in use` : "More filters"}
      defaultOpen={inUse > 0}
      className="border-t border-line"
    >
      <div className="space-y-5 pb-4">
        {myUserId && (
          <div className="space-y-1">
            <div role="group" aria-label="Filter by owner">
              <FilterChip
                label="Assigned to me"
                active={assignedToMe}
                onClick={() => onAssignedToMe(!assignedToMe)}
              />
            </div>
            {/* An operator is a real person with a real id, so the chip works; it simply
                cannot match, because leads are owned by the client's own team. */}
            {impersonating && (
              <p className="text-meta text-ink-muted">
                You are viewing this account as Calevate operations, so no lead here is assigned to you.
              </p>
            )}
          </div>
        )}
        <CallFilters {...calls} />
        <FacetPanel
          bare
          facets={facets.data}
          loading={facets.isLoading}
          error={facets.error}
          selected={facetValues}
          onChange={onFacetValues}
          onRetry={() => facets.refetch()}
        />
        <SavedViewBar<SavedView, SavedViewBody>
          views={views.data}
          error={views.error}
          activeViewId={activeViewId}
          canWrite={canSaveView}
          writeReason={saveViewReason}
          onApply={onApplyView}
          bodyFor={(name, rolling) => ({ name, filters: viewFilters(rolling), columns })}
          session={session}
          useSave={useSaveView}
          useRemove={useDeleteView}
          allLabel="All leads (no view)"
          describe={(view) => describeLeadView(view.filters)}
          notice={staleNotice}
          rollingNote={
            moving.length
              ? `saved as the last ${moving.map((range) => daysBetween(range.start, range.end)).join(" and ")} days, so it stays up to date`
              : null
          }
        />
      </div>
    </Disclosure>
  );
}

/** What a view lost when the capture list moved under it. Already removed from what it
 *  applies; said out loud because a dropped filter WIDENS the set. */
function staleNotice(view: SavedView): string | null {
  const lost = [...view.stale_filter_keys, ...view.stale_column_keys];
  if (!lost.length) return null;
  return `“${view.name}” also referred to ${lost.join(", ")}, which your agent's capture list no longer has. Those parts are not being applied. Update the view to save it without them.`;
}

/** "came in the last 7 days, last call missed, not handled yet" — the call half of a view. */
export function describeLeadView(filters: SavedViewFilters): string | null {
  const parts: string[] = [];
  const created = describeViewDays(filters.created);
  if (created) parts.push(`leads that came in ${created}`);
  const lastCall = describeViewDays(filters.last_call);
  if (lastCall) parts.push(`last called ${lastCall}`);
  const outcome = OUTCOMES.find((o) => o.value === filters.last_outcome);
  if (outcome) parts.push(`last call: ${outcome.label.toLowerCase()}`);
  const direction = DIRECTIONS.find((d) => d.value === filters.direction);
  if (direction) parts.push(`${direction.label.toLowerCase()} calls`);
  const followUp = FOLLOW_UP.find((f) => f.value === filters.follow_up);
  if (followUp) parts.push(followUp.label.toLowerCase());
  if (filters.callback_open === true) parts.push("a call-back waiting");
  if (filters.callback_open === false) parts.push("no call-back waiting");
  if (filters.test_calls === false) parts.push("no test calls");
  for (const c of filters.captured ?? []) parts.push(`${c.key.replaceAll("_", " ")} ${c.op} “${c.value}”`);
  return parts.length ? parts.join(", ") : null;
}

export interface LeadCallFilters {
  created: DateRange | null;
  onCreated: (next: DateRange | null) => void;
  lastCall: DateRange | null;
  onLastCall: (next: DateRange | null) => void;
  lastOutcome: string | undefined;
  onLastOutcome: (next: string | undefined) => void;
  direction: "inbound" | "outbound" | undefined;
  onDirection: (next: "inbound" | "outbound" | undefined) => void;
  testCalls: boolean;
  onTestCalls: (next: boolean) => void;
  followUp: "done" | "not_done" | undefined;
  onFollowUp: (next: "done" | "not_done" | undefined) => void;
  callbackOpen: boolean | undefined;
  onCallbackOpen: (next: boolean | undefined) => void;
  captured: CapturedFilter[];
  onCaptured: (next: CapturedFilter[]) => void;
  /** The details this agent captures, for "Detail contains". */
  capturedFields: { key: string; label: string }[];
}

/**
 * WHEN THE LEAD CAME IN AND WHAT ITS CALLS SAY: the questions an owner asks of the list
 * ("everyone from last week whose last call was missed and nobody has rung back"). Each
 * is a server filter on the one lead lens (`crm/lens.py`), so a bulk action or a plan
 * launched from here acts on exactly these rows.
 */
function CallFilters({
  created,
  onCreated,
  lastCall,
  onLastCall,
  lastOutcome,
  onLastOutcome,
  direction,
  onDirection,
  testCalls,
  onTestCalls,
  followUp,
  onFollowUp,
  callbackOpen,
  onCallbackOpen,
  captured,
  onCaptured,
  capturedFields,
}: LeadCallFilters) {
  const today = istDateStamp();
  return (
    <div className="space-y-3">
      <div role="group" aria-label="Filter by when and by calls" className="flex flex-wrap items-end gap-3">
        <DateRangePicker
          label="Came in"
          value={created}
          onChange={onCreated}
          max={today}
          placeholder="Any time"
          clearLabel="Show leads from any time"
          className="min-w-0"
        />
        <DateRangePicker
          label="Last called"
          value={lastCall}
          onChange={onLastCall}
          max={today}
          placeholder="Any time"
          clearLabel="Show leads called at any time"
          className="min-w-0"
        />
        <Choice
          label="Last call"
          value={lastOutcome}
          options={OUTCOMES}
          onChange={(next) => onLastOutcome(next)}
        />
        <Choice
          label="Direction"
          value={direction}
          options={DIRECTIONS}
          onChange={(next) => onDirection(DIRECTIONS.find((d) => d.value === next)?.value)}
        />
        <Choice
          label="Follow-up"
          value={followUp}
          options={FOLLOW_UP}
          onChange={(next) => onFollowUp(FOLLOW_UP.find((f) => f.value === next)?.value)}
        />
        <label className="block min-w-0">
          <span className="text-meta font-medium text-ink">Call-back</span>
          <select
            value={callbackOpen === undefined ? "" : String(callbackOpen)}
            onChange={(e) => onCallbackOpen(e.target.value === "" ? undefined : e.target.value === "true")}
            className={`${FIELD} w-auto max-w-full`}
          >
            <option value="">Any</option>
            <option value="true">Waiting</option>
            <option value="false">None waiting</option>
          </select>
        </label>
        <label className="block min-w-0">
          <span className="text-meta font-medium text-ink">Test calls</span>
          <select
            value={testCalls ? "include" : "leave_out"}
            onChange={(e) => onTestCalls(e.target.value === "include")}
            className={`${FIELD} w-auto max-w-full`}
          >
            <option value="include">Include</option>
            <option value="leave_out">Leave out</option>
          </select>
        </label>
      </div>
      <CapturedFilters captured={captured} onCaptured={onCaptured} fields={capturedFields} />
    </div>
  );
}

function Choice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: readonly { value: string; label: string }[];
  onChange: (next: string | undefined) => void;
}) {
  return (
    <label className="block min-w-0">
      <span className="text-meta font-medium text-ink">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        className={`${FIELD} w-auto max-w-full`}
      >
        <option value="">Any</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The API's cap on captured-detail filters per lens (`LeadLensIn.captured`). */
const MAX_CAPTURED = 5;

/**
 * "WHAT THEY SAID CONTAINS …": a captured detail matched as text, on the server, with the
 * value bound as a parameter. Each one is a chip that removes it; up to five.
 */
function CapturedFilters({
  captured,
  onCaptured,
  fields,
}: {
  captured: CapturedFilter[];
  onCaptured: (next: CapturedFilter[]) => void;
  fields: { key: string; label: string }[];
}) {
  const ids = useId();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const labelOf = (k: string) => fields.find((f) => f.key === k)?.label ?? k.replaceAll("_", " ");
  const chosenKey = key || fields[0]?.key || "";
  const full = captured.length >= MAX_CAPTURED;

  if (!fields.length && !captured.length) return null;
  return (
    <div className="space-y-2">
      {captured.length > 0 && (
        <ul aria-label="Detail filters" className="flex flex-wrap gap-2">
          {captured.map((c, index) => (
            <li key={`${c.key}-${index}`}>
              <button
                type="button"
                onClick={() => onCaptured(captured.filter((_, i) => i !== index))}
                aria-label={`Remove filter: ${labelOf(c.key)} contains ${c.value}`}
                className="press inline-flex max-w-full items-center gap-1.5 rounded-full border border-ink bg-ink/[0.06] px-3 py-1.5 text-xs font-medium text-ink touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              >
                <span className="truncate">
                  {labelOf(c.key)} {c.op === "equals" ? "is" : "contains"} “{c.value}”
                </span>
                <X aria-hidden className="h-3 w-3 shrink-0" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {fields.length > 0 && !full && (
        <form
          noValidate
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const text = value.trim();
            if (!text || !chosenKey) return;
            onCaptured([...captured, { key: chosenKey, op: "contains", value: text.slice(0, 200) }]);
            setValue("");
          }}
        >
          <label htmlFor={`${ids}-key`} className="block min-w-0">
            <span className={FIELD_LABEL}>Detail</span>
            <select
              id={`${ids}-key`}
              value={chosenKey}
              onChange={(e) => setKey(e.target.value)}
              className={`${FIELD_INLINE} mt-1 block max-w-full`}
            >
              {fields.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor={`${ids}-value`} className="block min-w-0">
            <span className={FIELD_LABEL}>Contains</span>
            <input
              id={`${ids}-value`}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              maxLength={200}
              autoComplete="off"
              className={`${FIELD_INLINE} mt-1 block w-40 max-w-full`}
            />
          </label>
          <button type="submit" disabled={!value.trim()} className={TEXT_ACTION}>
            Add filter
          </button>
        </form>
      )}
    </div>
  );
}
