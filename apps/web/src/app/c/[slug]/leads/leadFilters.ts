import { type LeadLens } from "@/lib/api/leads";

/**
 * WHICH FILTERS ARE IN FORCE — derived from the LENS, once, for every sentence on this
 * screen that is allowed to say something about the client's account.
 *
 * ## The defect this file exists to make unrepeatable
 *
 * The empty state, the header count and the stage tally each carried their own boolean
 * chain — `status || searchTerm`, and `searchTerm` alone — while the screen sends the
 * server FIVE filters. An owner who ticked "Assigned to me", or picked one facet value,
 * got a correct zero-row response and the sentence "No leads yet — Every answered call
 * becomes a lead within two minutes." printed over an account holding twelve hundred
 * leads. That is UX-DOCTRINE §52's defect in its purest form: a statement about the
 * business manufactured from something that is not evidence about the business. There
 * was no "Clear the filters" button either, because the action was gated on the same
 * two-thirds of the truth.
 *
 * ## Why the lens, and why a Record
 *
 * The `LeadLens` IS the request the server filtered by (`lib/api/leads.ts::lensBody`) —
 * one object, built once in `LeadsScreen`, shared by the rows, the facet counts and the
 * CSV. Deriving "is anything narrowing this" from that object rather than from a chain of
 * the screen's local state means the empty state cannot disagree with the query that
 * produced it: there is nothing to keep in step.
 *
 * The map below is a `Record<LeadFilterKey, …>`, and that is the half that survives a
 * SIXTH filter. `LeadFilterKey` is every key of the lens except `columns` — computed from
 * the interface, not typed out — so adding a field to `LeadLens` makes this Record
 * missing a property, and `tsc` refuses the build until somebody says whether the new key
 * narrows the rows. A boolean chain has no such day of reckoning; it just quietly keeps
 * answering the old question, which is exactly what it did here. The screen's
 * `clearFilter` map is the same shape for the same reason, so "clear the filters" cannot
 * forget one either.
 *
 * `columns` is excluded because it is the only key that changes what a row SHOWS rather
 * than which rows there are: hiding a column has never made an account empty.
 */
export type LeadFilterKey = Exclude<keyof LeadLens, "columns">;

/**
 * Is this one narrowing the rows? A filter counts as in force only when the server would
 * actually act on it — an empty string, an empty facet list and `undefined` are all "not
 * set", and `lensBody` drops them all before the request goes out.
 */
const IN_FORCE: Record<LeadFilterKey, (lens: LeadLens) => boolean> = {
  status: (lens) => Boolean(lens.status),
  search: (lens) => Boolean(lens.search),
  ask: (lens) => Boolean(lens.ask),
  assigned_to: (lens) => Boolean(lens.assigned_to),
  agent_id: (lens) => Boolean(lens.agent_id),
  // A key mapped to an empty array is a facet the client OPENED and chose nothing in.
  fields: (lens) => Object.values(lens.fields ?? {}).some((values) => values.length > 0),
};

/** Every key that narrows the rows, in one place — the screen's clear-all iterates it. */
export const LEAD_FILTER_KEYS = Object.keys(IN_FORCE) as LeadFilterKey[];

/** The filters the server is applying right now. */
export function filtersInForce(lens: LeadLens): LeadFilterKey[] {
  return LEAD_FILTER_KEYS.filter((key) => IN_FORCE[key](lens));
}

/**
 * Is ANYTHING narrowing the rows? The question the empty state, and only the empty state,
 * needs: "you have none" may be said only when this is false.
 */
export function anyFilterInForce(lens: LeadLens): boolean {
  return filtersInForce(lens).length > 0;
}

/**
 * Is anything OTHER than the stage chip narrowing the rows?
 *
 * The stage tally is the server's `status_counts_matching_search`, which is computed over
 * the whole scope MINUS the status filter (`crm/service.py`: "The counts follow the SEARCH
 * (and the agent scope) and ignore the STATUS filter"). So the sentence above those
 * badges may say "In this account" only when no OTHER filter is in force — under an owner
 * chip or a facet value those numbers are about a subset, and calling that subset "this
 * account" is the same §52 defect one line further down the screen.
 */
export function narrowedBeyondStatus(lens: LeadLens): boolean {
  return filtersInForce(lens).some((key) => key !== "status");
}
