import { PhoneCall, Timer } from "lucide-react";

import {
  CLINIC,
  CLINIC_LEADS,
  ClinicLeadHeader,
  ClinicLeadRow,
} from "@/components/marketing/home/mockups/callCards";
import { Chip, Panel, Window } from "@/components/marketing/home/mockups/kit";
import { MockStage } from "@/components/marketing/home/mockups/stage";

/**
 * "What you would see in the console" for `/roi`: the month's minutes on one screen, and
 * the leads those minutes produced on the next.
 *
 * The calculator answers in rupees from numbers the buyer typed; this pair shows where the
 * two sides of that sum live once the product is running. Labels are the console's own:
 * the Usage tab's tiles and hints and its "This month" card (`app/c/[slug]/billing/
 * UsageTab.tsx`), and the clinic's lead list, reused from the homepage rather than redrawn
 * (`home/mockups/callCards.tsx`).
 *
 * No rupee amount is drawn: the only figures on this page that price anything are the
 * calculator's, worked out from the published card. The voice name is the card's own
 * (`tierLabel`), passed in, and is omitted when the card could not be loaded.
 *
 * Phones get the Usage window alone: the lead rows need ~250px of fixed columns before the
 * reason column gets a pixel, which is the homepage hero's reason for the same cut.
 */
export function RoiConsoleMock({ voiceLabel }: { voiceLabel: string | null }) {
  return (
    <MockStage
      label={`Illustration: a month in the console for ${CLINIC} — the Usage tab showing minutes used and billed calls, beside the lead list those calls produced, each lead marked new, hot, interested, contacted, won or lost.`}
      // `minmax(0, …)`: a bare `fr` track floors at its min-content, and the lead rows
      // carry ~250px of fixed columns that would otherwise starve the Usage window.
      className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)]"
    >
      <Window title="Billing · Usage" className="mk-rise mk-s1 min-w-0">
        <span className="grid grid-cols-1 gap-3 p-4 min-[360px]:grid-cols-2 sm:p-5">
          <Panel className="mk-rise mk-s2 p-3.5">
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-ink-muted">
              <Timer aria-hidden className="h-3.5 w-3.5 text-brand" />
              Minutes used
            </span>
            <span className="mt-1.5 block text-xl font-bold tabular-nums text-ink">1,284.50</span>
            <span className="mt-0.5 block text-[11px] text-ink-muted">Pay as you go</span>
          </Panel>
          <Panel className="mk-rise mk-s3 p-3.5">
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-ink-muted">
              <PhoneCall aria-hidden className="h-3.5 w-3.5 text-brand" />
              Calls
            </span>
            <span className="mt-1.5 block text-xl font-bold tabular-nums text-ink">612</span>
            <span className="mt-0.5 block text-[11px] text-ink-muted">Billed calls this month</span>
          </Panel>
        </span>
        <span className="mk-rise mk-s4 block border-t border-line px-4 py-4 sm:px-5">
          <span className="block text-[13px] font-semibold text-ink">This month</span>
          <span className="mt-3 flex flex-col gap-2 text-[12px]">
            {voiceLabel !== null && (
              <span className="flex items-baseline justify-between gap-3">
                <span className="text-ink-muted">{voiceLabel} voice (1,284.50 min)</span>
                <span className="tabular-nums tracking-wider text-ink-faint">₹ ••,•••</span>
              </span>
            )}
            <span className="flex items-baseline justify-between gap-3 border-t border-line pt-2">
              <span className="font-semibold text-ink">Total so far</span>
              <span className="tabular-nums tracking-wider text-ink-faint">₹ ••,•••</span>
            </span>
          </span>
        </span>
      </Window>

      <Window
        title="Leads"
        className="mk-rise mk-s2 hidden min-w-0 sm:block"
        actions={<span className="text-[11px] text-ink-muted">{CLINIC}</span>}
      >
        <span className="flex flex-wrap items-center gap-1.5 border-b border-line px-4 py-3">
          <Chip tone="brand">All</Chip>
          <Chip>hot</Chip>
          <Chip>interested</Chip>
          <Chip>won</Chip>
        </span>
        <ClinicLeadHeader />
        <span className="block divide-y divide-line">
          {CLINIC_LEADS.map((lead, i) => (
            <ClinicLeadRow
              key={lead.name}
              lead={lead}
              className={`mk-rise mk-s${Math.min(6, i + 1)}`}
            />
          ))}
        </span>
      </Window>
    </MockStage>
  );
}
