import { type ReactNode } from "react";

import { type Lead, type LeadColumn, type LeadStatus } from "@/lib/api/leads";

/**
 * WHAT A ROW NEEDS, whichever view is drawing it.
 *
 * The table and the board render the SAME leads with the same controls and the same
 * per-row failure slot, so they take the same object rather than fourteen props each.
 * The screen builds it once (`LeadsScreen.tsx`); everything on it is already gated —
 * `maySelect`, `readOnly` and `canCall` are answers from `/v1/me`, not guesses.
 */
export interface LeadRowKit {
  columns: LeadColumn[];
  items: Lead[];
  canCall: boolean;
  maySelect: boolean;
  readOnly: boolean;
  ticked: Set<string>;
  allOfPageTicked: boolean;
  toggleRow: (leadId: string) => void;
  toggleAllOnPage: () => void;
  renderCell: (column: LeadColumn, lead: Lead) => ReactNode;
  /** Once per row, in its first cell — an inline edit that failed and reverted. */
  rowFailure: (lead: Lead) => ReactNode;
  callCell: (lead: Lead) => ReactNode;
  ownerCell: (lead: Lead, className: string) => ReactNode;
  statusCell: (lead: Lead, className: string) => ReactNode;
  hrefFor: (lead: Lead) => string;
  /** The SERVER's count for a stage, or `undefined` when it did not say. */
  stageCount: (stage: LeadStatus) => number | undefined;
  /** The filters in force, so the empty state can belong to them and not to the business. */
  status: string | undefined;
  searchTerm: string;
  askTerm: string;
  onClearFilters: () => void;
}
