"use client";

import { SearchField } from "@/components/arc/search-field";
import { HowItWorks } from "@/components/console/howItWorks";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { FIELD_HINT, formatCount } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useActAccess, useMe } from "@/lib/api/hooks";
import { useLeadFacets, useLeadsUnderLens, useSavedViews, type LeadStatus } from "@/lib/api/leads";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { MoreFilters, capturedFieldsOf } from "../leads/MoreFilters";
import { STATUSES } from "../leads/StatusSelect";
import type { LeadsLensState } from "../leads/useLeadsLens";

/**
 * The leads a lens matches, counted by the Leads table's own route (`POST /v1/leads/search`)
 * with one row, so the number here is the number the Leads screen shows for the same
 * filters. `matching` is undefined while a changed lens is still being counted: the
 * previous figure must not be sent as the confirmed count.
 */
export function usePickedLeads(session: Session, f: LeadsLensState, enabled = true) {
  const list = useLeadsUnderLens(session, f.lens, { limit: 1 }, enabled);
  const matching = list.data && !list.isPlaceholderData ? list.data.total : undefined;
  return { list, matching };
}

/**
 * PEOPLE FROM YOUR LEADS (D-893 F2): the Leads screen's own filters over the one lead lens
 * (`crm/lens.py`), so search, stage, outcome, follow-up, captured details and saved views
 * choose the same leads here as there. Only the lens and the confirmed count leave the
 * browser (`POST …/contacts/from-leads`); the server reads the numbers itself and refuses
 * a set that moved since it was counted.
 */
export function LeadPicker({ f }: { f: LeadsLensState }) {
  const session = useClientSession();
  const { list, matching } = usePickedLeads(session, f);
  const facets = useLeadFacets(session, f.lens);
  const views = useSavedViews(session);
  const me = useMe(session);
  const mayApplyView = useActAccess(session, "leads:write", "leads.saved_view", "save a view");
  const myUserId = me.data?.user_id ?? undefined;
  const stageCounts: Record<string, number> = list.data?.status_counts_matching_search ?? {};

  return (
    <div className="space-y-4">
      <div className="max-w-sm">
        <SearchField
          label="Search leads"
          hideLabel
          value={f.search}
          onValueChange={f.setSearch}
          maxLength={60}
          placeholder="Name or last digits"
        />
      </div>
      <SegmentedControl
        label="Filter by status"
        value={f.status ?? ""}
        onValueChange={(next) => f.setStatus(next === "" ? undefined : next)}
        options={[
          { value: "", label: "All" },
          ...STATUSES.map((s: LeadStatus) => ({
            value: s,
            label: s.charAt(0).toUpperCase() + s.slice(1),
            count: list.data ? formatCount(lookup(stageCounts, s)) : undefined,
          })),
        ]}
        className="min-w-0"
      />
      <MoreFilters
        inUse={f.moreInUse}
        myUserId={myUserId}
        assignedToMe={f.assignedTo !== undefined}
        onAssignedToMe={(on) => f.setAssignedTo(on ? myUserId : undefined)}
        impersonating={me.data?.impersonating}
        facets={facets}
        facetValues={f.facetValues}
        onFacetValues={f.setFacetValues}
        calls={f.callFilters(capturedFieldsOf(list.data))}
        views={views}
        activeViewId={f.activeViewId}
        canSaveView={mayApplyView.allowed}
        saveViewReason={mayApplyView.reason}
        onApplyView={(view) => f.applyView(view, myUserId)}
        viewFilters={f.viewFilters}
        columns={f.chosenColumns ?? null}
      />
      <p role="status" className={FIELD_HINT}>
        {matching !== undefined ? (
          `${formatCount(matching)} ${matching === 1 ? "lead matches" : "leads match"}. Anyone on your do-not-call list is skipped when the campaign starts.`
        ) : list.error ? (
          "We could not count the matching leads."
        ) : (
          <span className="text-shimmer">Counting matching leads…</span>
        )}
      </p>
      <HowItWorks
        className="mt-1"
        items={[
          "These are the filters from your Leads page, and your saved views work here too.",
          "We read each number from the lead itself; numbers already on the campaign or outside India are left out.",
          "If the leads change before you add them, nothing is added and you are asked to check again.",
          "A large set is added in the background; you can follow it on the card that appears.",
        ]}
      />
    </div>
  );
}
