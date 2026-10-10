"use client";

import { Disclosure, FilterChip } from "@/components/ui";
import type { LeadFacets, SavedView, SavedViewBody } from "@/lib/api/leads";

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
                capitalize={false}
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
