import { lookup } from "@/lib/lookup";
import { type Lead, type LeadColumn, type LeadLens } from "@/lib/api/leads";

import { narrowedBeyondStatus } from "./leadFilters";

/**
 * THE TABLE'S ARITHMETIC AND ITS METRICS — the React-free half of the leads screen.
 *
 * UX-DOCTRINE §6: "Pull the arithmetic out of the JSX … it is the half a test can drive
 * without a render." One subject: how a cell is measured, styled and read. Extracted from
 * `page.tsx` unchanged.
 */
/** Two ways to look at the same leads: the table for scanning detail columns, the
 *  board for working the pipeline stage by stage (parity with what competitors ship). */
export type ViewMode = "list" | "board";

/** Table cell metrics, once — a table whose columns disagree about padding reads as two
 *  tables. `p-2` on the card body plus `px-3` here is the design's 20px edge inset. */
export const HEAD_CELL = "px-3 py-2.5 font-semibold";
export const BODY_CELL = "px-3 py-2.5";

/**
 * The two controls a client touches most — move a lead's stage, reassign its owner — at
 * a size a thumb can hit.
 *
 * They were `px-1 py-0.5 text-xs`: 12px text in a 16px line box plus 2px each side, so
 * about a 20px-tall target, inside a table that scrolls sideways on a phone. That is
 * under WCAG 2.2 SC 2.5.8 Target Size (Minimum), which is 24×24 at Level AA. Both are
 * WRITES — a mis-tap on the status select changes a lead's stage, and `RowFailure` only
 * speaks after a FAILED write, never after a wrong one — so the cost of a near-miss here
 * is a lead in the wrong column that nobody knows moved.
 *
 * `touch:min-h-11` (44px on a coarse pointer) rather than the 24px the AA minimum would
 * accept, and rather than a flat `min-h-11`. Both halves of that are the repo's own
 * answer rather than a new one: 44px is the size every other tap target here uses, and
 * the `touch:` variant is `globals.css`'s `@media (pointer: coarse)` — a tap target is a
 * fact about the FINGER, not the viewport, so a mouse-driven console keeps its density
 * and a tablet gets the target. A second, flat spelling would have quietly restyled the
 * densest table in the product for every operator on a desktop.
 *
 * The visual compactness the small padding was buying is preserved by the transparent
 * border and background the class already carries — the control still reads as text until
 * it is hovered. `tests/responsive.test.ts` pins it.
 */
export const INLINE_EDIT =
  "touch:min-h-11 rounded-md border border-transparent bg-transparent px-1 py-0.5 text-xs text-ink";

/**
 * Rows per request, named because the bulk bar has to talk about it.
 *
 * "All 100 leads on this page are selected" and "select all 1,240 matching these filters"
 * are two different actions, and the sentence that offers the second one has to say how
 * big the first is. A literal in two places is how those two numbers come to disagree.
 */
export const PAGE_SIZE = 100;

/**
 * What the header count is a count OF — read off the LENS, so it names every filter that
 * narrowed it.
 *
 * It used to take `status` and `search` and say "matching your search" for the second one
 * only, which meant a count narrowed by the owner chip or by a facet value was printed as
 * a bare "12 leads" beside a screen full of them: a statement about the account made from
 * a filtered subset (UX-DOCTRINE §52). The stage stays NAMED because the chip is the one
 * filter whose value is a word a client would recognise in this sentence; everything else
 * is "your filters", because listing five of them here would out-shout the number.
 *
 * `narrowedBeyondStatus` rather than a second boolean chain — one derivation, exhaustive
 * over `LeadLens` by type, shared with the empty state and the stage tally.
 */
export function scopeLabel(lens: LeadLens, total: number): string {
  const stage = lens.status ? `${lens.status} ` : "";
  const noun = total === 1 ? "lead" : "leads";
  return narrowedBeyondStatus(lens) ? `${stage}${noun} matching your filters` : `${stage}${noun}`;
}

/**
 * WHY THE CSV EXPORT IS REFUSED, in one sentence, or `null` when it is not.
 *
 * One derivation for two renderings, which is what UX-DOCTRINE §4 asks for: the reason
 * goes on the control (`title`) *and* on the screen (`RestrictionNote`). It used to exist
 * only as a `title` on a DISABLED button — and a disabled `<button>` is not focusable and
 * fires no hover on touch, so the commonest refusal of the three (a question is in force)
 * reached a client as a button that did nothing, with no sentence anywhere on the screen.
 *
 * Order matters and is the order the button was already disabled in: a question refuses
 * the export even for an owner who holds the permission, so it is named first. `null` for
 * a permission answer that has NOT ARRIVED — "we do not know yet" is not a refusal, and a
 * note that flashed and retracted itself would be worse than the wait (§52).
 */
export function exportRefusal(
  askTerm: string,
  mayExport: boolean,
  exportReason: string | null,
): string | null {
  if (askTerm) {
    return (
      "A question ranks the best matches rather than selecting a complete set, " +
      "so it cannot be exported. Clear it to export by the filters instead."
    );
  }
  if (!mayExport) return exportReason;
  return null;
}

export function cellValue(lead: Lead, key: string): string {
  // `lookup`, not `data[key]`: `data` arrives from JSON.parse and therefore inherits
  // Object.prototype, so an extraction field keyed `constructor` — a client's own field
  // name, which nothing on our side constrains — would print
  // `function Object() { [native code] }` into the cell (src/lib/lookup.ts).
  const data: Record<string, unknown> = lead.data ?? {};
  const value = lookup(data, key);
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/** Per-column table styling. A column's LOOK follows its kind, so a client who moves
 *  Phone to the end still gets tabular numerals and no wrapping there. */
export function cellClass(column: LeadColumn): string {
  switch (column.key) {
    case "name":
      return `${BODY_CELL} font-semibold text-ink`;
    case "phone":
      return `${BODY_CELL} whitespace-nowrap tabular-nums text-ink-muted`;
    case "calls":
      return `${BODY_CELL} tabular-nums text-ink-muted`;
    case "created_at":
    case "updated_at":
      return `${BODY_CELL} whitespace-nowrap text-xs text-ink-faint`;
    default:
      return `${BODY_CELL} text-ink-muted`;
  }
}
