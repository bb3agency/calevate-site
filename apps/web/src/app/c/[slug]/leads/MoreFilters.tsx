"use client";

import { DateRangePicker, type DateRange } from "@/components/arc/calendar";
import { Disclosure, FIELD, FilterChip, istDateStamp } from "@/components/ui";
import type { LeadFacets, SavedView, SavedViewBody } from "@/lib/api/leads";
import { FOLLOW_UP, OUTCOMES } from "@/lib/callFilters";

import { FacetPanel } from "./FacetPanel";
import { SavedViewBar } from "./SavedViewBar";

/**
 * EVERYTHING USED NOW AND THEN, behind one fold (UX-DOCTRINE §3: low consequence, touched
 * rarely): the owner filter, the filters over captured answers, and saved views. Its
 * title says how many of them are narrowing the rows, and it opens by itself while one
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
  currentView,
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
  currentView: Omit<SavedViewBody, "name">;
  /** When the lead came in and what its calls say (D-893); the same lens Pip acts on. */
  calls: LeadCallFilters;
}) {
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
        <SavedViewBar
          views={views.data}
          error={views.error}
          activeViewId={activeViewId}
          canWrite={canSaveView}
          writeReason={saveViewReason}
          onApply={onApplyView}
          currentBody={currentView}
        />
      </div>
    </Disclosure>
  );
}

export interface LeadCallFilters {
  created: DateRange | null;
  onCreated: (next: DateRange | null) => void;
  lastOutcome: string | undefined;
  onLastOutcome: (next: string | undefined) => void;
  followUp: "done" | "not_done" | undefined;
  onFollowUp: (next: "done" | "not_done" | undefined) => void;
  callbackOpen: boolean | undefined;
  onCallbackOpen: (next: boolean | undefined) => void;
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
  lastOutcome,
  onLastOutcome,
  followUp,
  onFollowUp,
  callbackOpen,
  onCallbackOpen,
}: LeadCallFilters) {
  return (
    <div role="group" aria-label="Filter by when and by calls" className="flex flex-wrap items-end gap-3">
      <DateRangePicker
        label="Came in"
        value={created}
        onChange={onCreated}
        max={istDateStamp()}
        placeholder="Any time"
        clearLabel="Show leads from any time"
        className="min-w-0"
      />
      <label className="block min-w-0">
        <span className="text-meta font-medium text-ink">Last call</span>
        <select
          value={lastOutcome ?? ""}
          onChange={(e) => onLastOutcome(e.target.value || undefined)}
          className={`${FIELD} w-auto max-w-full`}
        >
          <option value="">Any</option>
          {OUTCOMES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="block min-w-0">
        <span className="text-meta font-medium text-ink">Follow-up</span>
        <select
          value={followUp ?? ""}
          onChange={(e) => onFollowUp(FOLLOW_UP.find((f) => f.value === e.target.value)?.value)}
          className={`${FIELD} w-auto max-w-full`}
        >
          <option value="">Any</option>
          {FOLLOW_UP.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </label>
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
    </div>
  );
}
