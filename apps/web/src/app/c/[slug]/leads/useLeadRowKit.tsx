"use client";

import { useState } from "react";

import { MonoValue, formatCount, formatIST } from "@/components/ui";
import { type CallLeadResult } from "@/lib/api/client";
import { useCallLead, useWriteAccess } from "@/lib/api/hooks";
import {
  useLeadRowEdit,
  useMembers,
  type Lead,
  type LeadColumn,
  type LeadStatus,
} from "@/lib/api/leads";

import { AssigneeSelect } from "./AssigneeSelect";
import { CallControl } from "./CallControl";
import { EMPTY_SELECTION, type BulkSelection } from "./BulkActionBar";
import { InlineName } from "./InlineName";
import { RowFailure } from "./RowFailure";
import { StatusSelect } from "./StatusSelect";
import { INLINE_EDIT, cellValue } from "./leadsTable";
import type { LeadRowKit } from "./leadRowKit";

/**
 * HOW ONE LEAD IS DRAWN — the cells, the two inline editors, the dispatch control and the
 * per-row failure slot.
 *
 * Extracted from `LeadsScreen.tsx` (UX-DOCTRINE §6). One subject, and the table and the
 * board share every line of it: they draw the SAME row, so a second copy of any of this
 * would be the drift `leadRowKit.ts` exists to prevent.
 *
 * `callResults` lives HERE rather than on the mutation, and that is the point of putting
 * it beside the control: `callLead.data` is one slot, so calling a second lead would move
 * the first row's verdict onto the second — and a compliance refusal moving rows is worse
 * than none.
 */
export function useLeadRowKit({
  session,
  href,
  items,
  columns,
  rows,
  mayEditLead,
  members,
  readOnly,
  canCall,
  callLead,
  selectedAgentId,
  selection,
  setSelection,
  filtered,
  askTerm,
  onClearFilters,
  stageCount,
}: {
  session: { orgSlug: string };
  href: (path: string) => string;
  items: Lead[];
  columns: LeadColumn[];
  rows: ReturnType<typeof useLeadRowEdit>;
  mayEditLead: ReturnType<typeof useWriteAccess>;
  members: ReturnType<typeof useMembers>;
  readOnly: boolean;
  canCall: boolean;
  callLead: ReturnType<typeof useCallLead>;
  selectedAgentId: string;
  selection: BulkSelection;
  setSelection: (update: (prev: BulkSelection) => BulkSelection) => void;
  /** Is ANY filter narrowing the rows — one answer off the lens; see `leadRowKit.ts`. */
  filtered: boolean;
  askTerm: string;
  onClearFilters: () => void;
  /** The SERVER's count for a stage, or `undefined` when it did not say. */
  stageCount: (stage: LeadStatus) => number | undefined;
}): LeadRowKit {
  /**
   * The dispatch answer, per lead — see the header.
   */
  const [callResults, setCallResults] = useState<Record<string, CallLeadResult>>({});

  const dispatch = (leadId: string) =>
    callLead.mutate(
      { leadId, agentId: selectedAgentId },
      // A 200 carrying `status: "blocked"` is the compliance gate answering, not an
      // error — it is recorded against the row like the queued case (same shape the
      // call-detail follow-up card handles).
      {
        onSuccess: (result) => setCallResults((prev) => ({ ...prev, [leadId]: result })),
      },
    );

  const callCell = (lead: Lead) =>
    canCall ? (
      <CallControl
        result={callResults[lead.id]}
        pending={callLead.isPending && callLead.variables?.leadId === lead.id}
        onCall={() => dispatch(lead.id)}
      />
    ) : null;

  const ownerCell = (lead: Lead, className: string) => (
    <AssigneeSelect
      lead={lead}
      members={members.data}
      // The picker is only offered when the team list actually ARRIVED. An empty
      // `<select>` over a failed `/v1/members` would read as "you have no colleagues",
      // which is a statement about the business made from a request that never landed.
      unavailableReason={
        members.error
          ? "We could not read your team just now, so the owner cannot be changed. Reload the page to try again."
          : mayEditLead.reason
      }
      // Per-ROW pending, not the mutation's global flag: one saving row must not freeze
      // every other row's controls.
      disabled={!mayEditLead.allowed || rows.pendingFor(lead.id)}
      onChange={(userId) => rows.edit(lead.id, { assigned_to: userId })}
      className={className}
    />
  );

  /**
   * THE FAILURE, IN THE ROW IT BELONGS TO — once per row, in its FIRST cell.
   *
   * An inline edit that fails and reverts is a lie the user cannot see: the control snaps
   * back to the stored value because the row re-renders from a cache the server never
   * changed, and without this the only evidence is a value that did not stick. A single
   * page-level notice cannot do that job on a hundred-row table — it says an edit failed
   * without saying which row.
   *
   * The first cell rather than the edited one, and that is not laziness: the column
   * chooser can drop the name, the status or the owner, so a message anchored to any one
   * of them would disappear exactly when that column was hidden — and a row can only have
   * one failure at a time (one mutation, one error slot), so one place per row is the
   * honest number of places.
   */
  const rowFailure = (lead: Lead) => <RowFailure error={rows.errorFor(lead.id)} />;

  /**
   * ONE CELL, chosen by the server's column key.
   *
   * The switch is the price of a chooseable table and it is worth paying here rather
   * than in a generic renderer: `status` and `owner` are interactive controls rather
   * than text, `name` is the link to the lead, and `phone` is plain text on purpose —
   * a `tel:` link would put the number in an `href`, which is the one place it still
   * must not go. Anything the switch does not name is an extraction field.
   */
  const renderCell = (column: LeadColumn, lead: Lead) => {
    switch (column.kind === "fixed" ? column.key : "") {
      case "name":
        // The link AND the inline text edit (SURFACES §2: "exit via Enter/click-out; no
        // modal"). `InlineName` carries the interaction and the row-level failure; the
        // gate is the same `leads:write` the two selects use.
        return (
          <InlineName
            lead={lead}
            href={href(`/c/${session.orgSlug}/leads/${lead.id}`)}
            canEdit={mayEditLead.allowed}
            editReason={mayEditLead.reason}
            saving={rows.pendingFor(lead.id)}
            onCommit={(name) => rows.edit(lead.id, { name })}
          />
        );
      case "phone":
        // IN FULL (D-436). Text, not a `tel:` href — see `renderCell` above. Mono and
        // tabular for the same reason the detail screen and the DNC console are: a
        // number a person compares against their own records is read character by
        // character.
        return <MonoValue className="tabular-nums">{lead.phone_e164}</MonoValue>;
      case "status":
        return (
          <StatusSelect
            value={lead.status}
            label={`Status for ${lead.name ?? lead.phone_e164}`}
            disabled={rows.pendingFor(lead.id) || readOnly}
            onChange={(next) => rows.edit(lead.id, { status: next })}
            className={`${INLINE_EDIT} capitalize hover:border-line`}
          />
        );
      case "owner":
        return ownerCell(
          lead,
          `${INLINE_EDIT} hover:border-line`,
        );
      case "source":
        return lead.source;
      case "calls":
        return formatCount(lead.call_count);
      case "created_at":
        return formatIST(lead.created_at);
      case "updated_at":
        return formatIST(lead.updated_at);
      default:
        return cellValue(lead, column.key);
    }
  };

  const maySelect = mayEditLead.allowed;
  // Not memoised: `items` is `leads.data?.items ?? []`, a fresh array every render, so a
  // `useMemo` keyed on it would recompute every render anyway while implying it did not.
  const pageIds = items.map((lead) => lead.id);
  const ticked = new Set(selection.wholeQuery ? pageIds : selection.ids);
  const allOfPageTicked = pageIds.length > 0 && pageIds.every((id) => ticked.has(id));

  const toggleRow = (leadId: string) =>
    setSelection((prev) => {
      // Ticking a row out of a whole-query selection narrows it back to THIS PAGE, and
      // says so through the bar's sentence. Silently keeping the query scope while a row
      // looks unticked would be the scope ambiguity in its most confusing form.
      const base = prev.wholeQuery ? pageIds : prev.ids;
      const next = base.includes(leadId)
        ? base.filter((id) => id !== leadId)
        : [...base, leadId];
      return { ids: next, wholeQuery: false };
    });


  /**
   * ONE OBJECT FOR A ROW, because the table and the board draw the same row. Built here
   * because every gate on it (`maySelect`, `readOnly`, `canCall`) is an answer from
   * `/v1/me` that this component already holds — see `leadRowKit.ts`.
   */
  const kit: LeadRowKit = {
    columns,
    items,
    canCall,
    maySelect,
    readOnly,
    ticked,
    allOfPageTicked,
    toggleRow,
    toggleAllOnPage: () =>
      setSelection(() =>
        allOfPageTicked ? EMPTY_SELECTION : { ids: pageIds, wholeQuery: false },
      ),
    renderCell,
    rowFailure,
    callCell,
    ownerCell,
    statusCell: (lead, className) => (
      <StatusSelect
        value={lead.status}
        label={`Status for ${lead.name ?? lead.phone_e164}`}
        disabled={rows.pendingFor(lead.id) || readOnly}
        onChange={(next) => rows.edit(lead.id, { status: next })}
        className={className}
      />
    ),
    hrefFor: (lead) => href(`/c/${session.orgSlug}/leads/${lead.id}`),
    stageCount,
    filtered,
    askTerm,
    onClearFilters,
  };
  return kit;
}
