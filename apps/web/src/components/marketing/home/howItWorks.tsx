import type { ReactNode } from "react";

import { Band, Chapter, HOME } from "./band";
import { MockStage } from "./mockups/stage";
import { CallMock, FieldListMock, LeadRecordMock } from "./mockups/stepMockups";

/**
 * CHAPTER 2 — how it works: three steps, each with the screen it happens on.
 *
 * Three columns from `lg`, a column of three below it. The numerals are an ORDER, not a
 * measurement, so enlarging them claims nothing. Each step's screen is decorative — the
 * heading and sentence carry the meaning — so the screens are hidden from assistive
 * technology and the step reads as heading, then sentence.
 *
 * Step 02 follows D-669: a new agent VOLUNTEERS neither notice and opens with the greeting;
 * each is a per-agent toggle (D-163). The unswitchable guarantee is about the ANSWER and
 * lives in the trust chapter.
 */

const STEPS: readonly { step: string; title: string; body: string; figure: ReactNode }[] = [
  {
    step: "01",
    title: "You say what matters",
    body: "Tell the agent about your business and list what it has to find out from each caller. That list becomes your columns.",
    figure: <FieldListMock />,
  },
  {
    step: "02",
    title: "It takes the call",
    body: "Someone rings, or the agent works through a list you gave it. It opens with your greeting, says it is an AI whenever a caller asks, and answers from what you approved.",
    figure: <CallMock />,
  },
  {
    step: "03",
    title: "You get a lead, not a recording to wade through",
    body: "The enquiry lands filled in and sorted, with the audio attached and the key moments timestamped if you want to hear it yourself.",
    figure: <LeadRecordMock />,
  },
];

export function HowItWorks() {
  return (
    <Chapter tone="raised">
      <Band
        id="how"
        eyebrow="How it works"
        weight="standard"
        title="Three things happen, and you only set up the first one"
      >
        <ol className={`${HOME.contentGap} grid ${HOME.itemGap} lg:grid-cols-3`}>
          {STEPS.map(({ step, title, body, figure }) => (
            <li
              key={step}
              className="flex flex-col overflow-hidden rounded-2xl border border-line bg-app shadow-card lg:row-span-2 lg:grid lg:grid-cols-1 lg:grid-rows-subgrid lg:gap-0"
            >
              {/* Subgrid at lg: the three figures share one row height and the three captions
                  another, so every step's number and title start on the same line however tall
                  its mockup is. */}
              <MockStage className="flex items-center justify-center bg-[radial-gradient(circle_at_50%_0%,var(--brand-soft),transparent_70%)] p-4 sm:p-8 lg:min-h-80">
                <div className="w-full max-w-xs">{figure}</div>
              </MockStage>
              <div className="border-t border-line bg-surface p-5 sm:p-7">
                <span className="font-mono text-sm font-semibold text-brand-strong dark:text-brand-bright">
                  {step}
                </span>
                <h3 className={`mt-2 ${HOME.itemTitle} font-semibold text-balance text-ink`}>{title}</h3>
                <p className={`mt-2 text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </Band>
    </Chapter>
  );
}
