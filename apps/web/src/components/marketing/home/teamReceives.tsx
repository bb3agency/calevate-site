import { Filter, Handshake, PhoneOutgoing } from "lucide-react";

import { LeadInbox } from "@/components/marketing/leadInbox";
import { Reveal } from "@/components/marketing/motion";

import { Band, Chapter } from "./band";

/**
 * CHAPTER 5 — THE DARK ONE. What your team receives, and what that does to their day.
 *
 * ## Why this chapter is the one that inverts
 *
 * A landing page needs one place where the scroll stops, and the honest candidate is the
 * only place the PRODUCT is on screen. Everything else on this page is an argument; this is
 * the artefact — the leads screen, drawn with example enquiries — and a dark ground does
 * two things at once for it: it breaks a scroll that was thirteen identical stripes long,
 * and it makes the white product panels read as lit rather than as another card on another
 * grey. That is why the inversion is HERE and not on the trust band or the closing panel,
 * where it would only be decoration.
 *
 * `--brand-deep`, not a neutral: the tint has to be ours, and `--brand-deep` is defined
 * once and is the SAME value in both palettes, so the one band that inverts is the one band
 * that cannot drift between themes. See `band.tsx` for the ratios.
 *
 * ## Two bands, one chapter — and the ranking between them is the argument
 *
 * Band 06 ("what your team receives") and band 09 ("your sales team") were four chapters
 * apart with the whole capability list between them, which is odd, because the second one
 * is what the first one is FOR: the inbox is the artefact, the shortlist argument is what it
 * means. Together, ranked `anchor` then `quiet`, they read as one idea with a consequence.
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

/** A card on the inverted ground. White at 6% is a lift, not a second surface colour. */
const DARK_CARD =
  "rounded-2xl border border-white/15 bg-white/[0.06] p-5 sm:p-6";

const QUALIFICATION: readonly { icon: typeof Filter; title: string; body: string }[] = [
  {
    icon: PhoneOutgoing,
    title: "Everyone on the list gets the first call",
    body:
      "All of them, in the order they came in. A web enquiry becomes a call without " +
      "waiting for someone to notice it, and the gap between the form and the dial is " +
      "timed on every one.",
  },
  {
    icon: Filter,
    title: "They come back sorted, not just recorded",
    body:
      "Each one lands as a row, marked contacted, interested or hot. A hot lead alerts " +
      "you while they are still thinking about it.",
  },
  {
    icon: Handshake,
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
        <LeadInbox tone="dark" />
      </Band>

      <Band
        id="sales"
        eyebrow="Your sales team"
        weight="quiet"
        tone="dark"
        className="mt-16 sm:mt-20"
        title="Your salespeople should be closing, not finding out who is interested"
        lede="Calevate is not your salesperson. It is the layer that makes your salesperson more productive: it takes the first call to every enquiry and every name on your list, works out who is worth a conversation, and hands your people the shortlist."
      >
        <div className="mt-10 grid gap-4 sm:mt-12 lg:grid-cols-3">
          {QUALIFICATION.map(({ icon: Icon, title, body }, index) => (
            <Reveal as="section" key={title} delay={index * 0.08} className={DARK_CARD}>
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-white">
                <Icon aria-hidden className="h-5 w-5" />
              </span>
              <h3 className="mt-5 text-[17px] font-semibold text-white">{title}</h3>
              <p className="mt-1.5 text-sm text-pretty text-white/80">{body}</p>
            </Reveal>
          ))}
        </div>
        <Reveal delay={0.2}>
          <p className="mt-8 max-w-2xl text-sm text-white/70">
            This is not your team replaced. It is the part of their day that was never
            selling. The goal is not to automate your business — it is to automate the parts
            of the phone workflow your team should not be spending their day on.
          </p>
        </Reveal>
      </Band>
    </Chapter>
  );
}
