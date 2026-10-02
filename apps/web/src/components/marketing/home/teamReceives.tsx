import { Reveal } from "@/components/marketing/motion";

import { Band, Chapter, HOME } from "./band";
import { CampaignBoardMock } from "./mockups/featureMockups";
import { LeadsWorkspace } from "./mockups/leadsWorkspace";
import { MockStage } from "./mockups/stage";

/**
 * CHAPTER 5 — THE DARK ONE. What your team receives, and what that does to their day.
 *
 * ## Why this chapter is the one that inverts
 *
 * It holds the largest product screen on the page — the leads list and one opened lead —
 * and a dark ground makes the white product panels read as lit rather than as another card
 * on another grey. `--brand-deep`, not a neutral, because the tint has to be ours; it is
 * the same value in both palettes (see `band.tsx` for the ratios).
 *
 * The second band ("your sales team") is what the first one is FOR: the list is the
 * artefact, the shortlist is what it means. Ranked `anchor` then `quiet`, beside the
 * campaign screen that works the list.
 *
 * ## What is NOT here, and the guard that keeps it out
 *
 * No conversion statistic, no multiple, no "studies show". Every figure this play is
 * normally sold with traces back to a source this repository could not read, so hard rule 11
 * forbids repeating it and `docs/POSITIONING-QUALIFICATION-LAYER.md` names each refused one.
 * `publicLanding.test.tsx` scopes a second, narrower ban to the `#sales` section for exactly
 * the shapes a conversion claim takes.
 *
 * Every card is a shipped surface:
 *  - the first call to every lead: `apps/api/ingest/service.py` (webhook-in → lead →
 *    compliance gate → outbound) and `apps/api/campaigns/service.py`; the form→dial gap is
 *    timed by `apps/api/core/alerting.py:632::record_speed_to_lead`;
 *  - sorted and written down: the extraction schema drives the columns
 *    (`apps/api/crm/columns.py`), the statuses are the fixed enum in
 *    `apps/api/crm/schemas.py:29`, and the hot-lead alert fires off the extracted fields
 *    (`apps/workers/pipeline.py:179`);
 *  - the funnel the owner reads it back on: `apps/api/crm/performance.py:42,46`.
 */

/** A panel on the inverted ground. White at 6% is a lift, not a second surface colour. */
const DARK_PANEL = "rounded-2xl border border-white/15 bg-white/[0.06]";

const QUALIFICATION: readonly { title: string; body: string }[] = [
  {
    title: "Everyone on the list gets the first call",
    body:
      "All of them, in the order they came in. A web enquiry becomes a call without " +
      "waiting for someone to notice it, and the gap between the form and the dial is " +
      "timed on every one.",
  },
  {
    title: "They come back sorted, not just recorded",
    body:
      "Each one lands as a row, marked contacted, interested or hot. A hot lead alerts " +
      "you while they are still thinking about it.",
  },
  {
    title: "Your people open the day on a shortlist",
    body:
      "Your team talks to people who already said yes. Nobody spends the morning " +
      "finding out who didn’t.",
  },
];

export function TeamReceives() {
  return (
    <Chapter tone="dark">
      <Band
        id="leads"
        eyebrow="What your team receives"
        weight="anchor"
        tone="dark"
        title="Stop replaying calls to find out who is serious"
        lede="This is what your employee opens tomorrow morning instead of a list of numbers nobody can explain."
      >
        <LeadsWorkspace />
      </Band>

      <Band
        id="sales"
        eyebrow="Your sales team"
        weight="quiet"
        tone="dark"
        className={HOME.bandGap}
        title="Your salespeople should be closing, not finding out who is interested"
        lede="Calevate is not your salesperson. It is the layer that makes your salesperson more productive: it takes the first call to every enquiry and every name on your list, works out who is worth a conversation, and hands your people the shortlist."
      >
        {/* The three steps as one panel of rows — a sequence, read as one consequence —
            beside the campaign screen that produces them. */}
        <div className={`${HOME.contentGap} grid gap-6 lg:grid-cols-[1fr_1.05fr] lg:items-center lg:gap-12`}>
          <Reveal as="ul" className={`${DARK_PANEL} divide-y divide-white/15`}>
            {QUALIFICATION.map(({ title, body }, index) => (
              <li key={title} className="flex gap-4 p-5 sm:gap-5 sm:p-7">
                <span aria-hidden className="w-6 shrink-0 pt-1 font-mono text-sm font-semibold text-white/80">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3 className={`${HOME.itemTitle} font-semibold text-balance text-white`}>
                    {title}
                  </h3>
                  <p className={`mt-2 text-pretty text-white/80 ${HOME.bodySm}`}>{body}</p>
                </div>
              </li>
            ))}
          </Reveal>
          <MockStage
            label="Illustration of a running campaign: the contacts on the list, how many calls were answered, how many were not called because they are on the do-not-call list, and a pause control."
          >
            <CampaignBoardMock />
          </MockStage>
        </div>
        <p className={`mt-10 max-w-2xl text-white/75 ${HOME.bodySm}`}>
          This is not your team replaced. It is the part of their day that was never
          selling. The goal is not to automate your business — it is to automate the parts
          of the phone workflow your team should not be spending their day on.
        </p>
      </Band>
    </Chapter>
  );
}
