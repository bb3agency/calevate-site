import { Search } from "lucide-react";

import {
  CallCard,
  SAMPLE_LEADS,
  SampleLeadHeader,
  SampleLeadRow,
  LeadCapturedCard,
} from "./callCards";
import { Chip, Window } from "./kit";
import { MockStage } from "./stage";

/**
 * The hero's product shot: a call arrives, and a lead lands in the list.
 *
 * Three panels SIDE BY SIDE — the live call, the leads screen, the captured lead — in the
 * order the story happens. They never overlap at any width: overlapping cards hid the
 * table's own columns, and a product shot that covers its product is decoration. Each
 * width keeps only what fits:
 * - from `xl`: all three, the side cards set a little lower than the table;
 * - `lg`: the call and the table (the table's new top row carries the captured lead);
 * - `sm`-`md`: the table alone;
 * - phone: the two cards, stacked — a table at 328px is unreadable.
 *
 * The leads screen is drawn from `app/c/[slug]/leads` (status chips "All" + the stages,
 * the search placeholder, the List/Board toggle) with the education template's captured
 * fields as columns.
 *
 * ## Motion
 *
 * A one-shot CSS sequence (`mk-sim-step` + the `mk-d*` delays in `globals.css`): the
 * table settles, the call arrives, then the captured lead and its new row appear. It is an
 * EXPLANATION, the one purpose that earns a staged sequence on a marketing page, and it
 * runs once. Every step's end frame is its resting state, so without the bundle, or for a
 * reduced-motion reader, the finished picture is painted on the first frame. The only loop
 * is the call's voice level, paused by `MockStage` once the hero scrolls away.
 */
export function HeroProduct() {
  return (
    <MockStage
      label="Illustration: a caller rings a coaching centre and speaks Telugu with the AI agent; the call becomes a captured lead — name, course and class — at the top of the centre's lead list."
      className="relative"
    >
      {/* Phone: the two cards, in the order they happen. */}
      <div className="mx-auto grid max-w-sm gap-3 sm:hidden">
        <CallCard className="mk-sim-step mk-d1" />
        <LeadCapturedCard className="mk-sim-step mk-d3" />
      </div>

      <div className="hidden items-start gap-5 sm:grid lg:grid-cols-[0.9fr_1.6fr] xl:grid-cols-[0.85fr_1.6fr_0.85fr] xl:gap-6">
        <CallCard className="mk-sim-step mk-d2 hidden lg:mt-10 lg:block" />
        <Window
          title="Leads"
          className="mk-sim-step mk-d1"
          actions={
            <span className="hidden items-center gap-1 rounded-md bg-surface p-0.5 ring-1 ring-line md:flex">
              <span className="rounded bg-app px-2 py-0.5 text-[11px] font-semibold text-ink">List</span>
              <span className="px-2 py-0.5 text-[11px] font-medium text-ink-muted">Board</span>
            </span>
          }
        >
          <span className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
            <span className="flex min-w-0 items-center gap-2 rounded-md bg-surface px-2.5 py-1 text-[12px] text-ink-faint ring-1 ring-line">
              <Search className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">Name or last digits</span>
            </span>
            <span className="flex items-center gap-1.5">
              <Chip tone="brand">All</Chip>
              <Chip>new</Chip>
              <Chip>hot</Chip>
              <Chip className="hidden md:inline-flex">interested</Chip>
            </span>
            <span className="ml-auto text-[11px] text-ink-muted">126 leads</span>
          </span>
          <SampleLeadHeader />
          <span className="block divide-y divide-line">
            {SAMPLE_LEADS.map((lead, i) => (
              <SampleLeadRow
                key={lead.name}
                lead={lead}
                highlight={i === 0}
                className={i === 0 ? "mk-sim-field mk-d5" : ""}
              />
            ))}
          </span>
        </Window>
        <LeadCapturedCard className="mk-sim-step mk-d4 hidden xl:mt-16 xl:block" />
      </div>
    </MockStage>
  );
}
