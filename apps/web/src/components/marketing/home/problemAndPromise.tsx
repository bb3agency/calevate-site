import type { ReactNode } from "react";

import { Reveal } from "@/components/marketing/motion";

import { Band, Chapter, HOME } from "./band";
import { AnsweredMini, FollowUpMini, QualifiedMini, RowsMini } from "./mockups/featureMockups";
import { MockStage } from "./mockups/stage";

/**
 * CHAPTER 1 — the problem, then the promise, on one ground: the second is the answer to
 * the first, so they share a breath rather than a rule between them. The promise is one of
 * the page's three `anchor` bands, because it is the sentence the buyer is here to test.
 *
 * The problem is stated as a SCENE, not a statistic: the figures this genre opens with
 * (how many calls an SMB misses, what a slow follow-up costs) trace to sources this
 * repository could not read, and hard rule 11 forbids repeating them.
 *
 * Each outcome is a BENTO cell with the product drawn in it, because "show, don't
 * describe" is the brief and each outcome has a screen that proves it:
 *  - answering — 24/7 by default (`apps/api/agents/business_hours.py`);
 *  - following up — `apps/api/ingest/service.py` turns a web enquiry into a dial, and
 *    `apps/api/core/alerting.py::record_speed_to_lead` times the gap;
 *  - qualifying — the fixed lead statuses (`apps/api/crm/schemas.py`) and the hot-lead
 *    alert (`apps/workers/pipeline.py::HOT_LEAD_FIELD_TRIGGERS`);
 *  - structuring — the per-agent extraction schema is the CRM's column registry
 *    (`apps/api/crm/columns.py`), shared by the table and the CSV export.
 */

const PROBLEMS: readonly { title: string; body: string }[] = [
  {
    title: "The calls nobody answered",
    body: "Your staff is with a customer when an enquiry rings. The caller rings the next business instead.",
  },
  {
    title: "The enquiry that went cold",
    body: "A form arrives at 11am. Somebody notices it at 2pm. By then they have spoken to somebody else.",
  },
  {
    title: "The hours spent sorting",
    body: "Your salespeople work the whole list to find the few who were interested. That is not selling.",
  },
];

const OUTCOMES: readonly {
  title: string;
  body: string;
  figure: ReactNode;
  span: string;
}[] = [
  {
    title: "Every enquiry gets answered",
    body: "While your staff is busy, after you close, and on a festival day — in the language the caller rang in.",
    figure: <AnsweredMini />,
    span: "lg:col-span-3",
  },
  {
    title: "Follow-up stops depending on memory",
    body: "Every new enquiry gets a first call without waiting for a person to notice it, and the gap is timed on every one.",
    figure: <FollowUpMini />,
    span: "lg:col-span-2",
  },
  {
    title: "Your team talks to qualified people first",
    body: "Instead of “Hello, what are you looking for?”, your team opens with “Priya wants a root canal and asked for Tuesday evening.”",
    figure: <QualifiedMini />,
    span: "lg:col-span-2",
  },
  {
    title: "Calls become information you can act on",
    body: "Not scattered recordings, diary notes and WhatsApp messages — rows you can sort, filter and hand to somebody.",
    figure: <RowsMini />,
    span: "lg:col-span-3",
  },
];

export function ProblemAndPromise() {
  return (
    <Chapter tone="app">
      <Band
        id="problem"
        eyebrow="The problem"
        weight="standard"
        title="The calls you missed today are not on any report"
      >
        {/* One reveal for the row, not one per item: three things arriving one after the
            other on scroll is a queue, not an entrance. */}
        <Reveal as="ul" className={`${HOME.contentGap} grid gap-px overflow-hidden rounded-2xl border border-line bg-line md:grid-cols-3`}>
          {PROBLEMS.map(({ title, body }) => (
            <li key={title} className="bg-surface p-5 sm:p-8">
              <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>{title}</h3>
              <p className={`mt-2 text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
            </li>
          ))}
        </Reveal>
      </Band>

      <Band
        id="outcomes"
        eyebrow="What changes"
        weight="anchor"
        split
        className={HOME.bandGap}
        title="What is different in your business by next week"
        lede="Calevate handles the first layer of phone work so your team can spend the day on the conversations that matter."
      >
        <div className={`${HOME.contentGap} grid ${HOME.itemGap} lg:grid-cols-5`}>
          {OUTCOMES.map(({ title, body, figure, span }) => (
            <section
              key={title}
              className={`flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-card ${HOME.panelLift} ${span}`}
            >
              <MockStage className="border-b border-line bg-app/70 p-4 sm:p-7">{figure}</MockStage>
              <div className="p-5 sm:p-7">
                <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>{title}</h3>
                <p className={`mt-2 max-w-xl text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
              </div>
            </section>
          ))}
        </div>
      </Band>
    </Chapter>
  );
}
