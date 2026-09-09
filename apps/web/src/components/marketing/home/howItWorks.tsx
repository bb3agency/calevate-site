import { ArrowRight, ListChecks, PhoneCall, Rows3 } from "lucide-react";

import { BeforeAfter } from "@/components/marketing/beforeAfter";
import { Reveal } from "@/components/marketing/motion";
import { CARD, GRID } from "@/components/marketing/pageShell";

import { Band, Chapter } from "./band";

/**
 * CHAPTER 2 — how it works, and what it replaces. BANDS 03 AND 04, JOINED.
 *
 * "Three things happen" and "Same leads. Completely different workflow." were two numbered
 * chapters with a rule between them. They are one mechanism explained twice — once as the
 * three steps you take, once as the two chains a lead travels — and the second only makes
 * sense to a reader who has just read the first. Joining them costs nothing and removes a
 * boundary that was telling the reader to start again.
 *
 * The before/after keeps its own `<h3>`, so it is still in the heading outline and still
 * findable by a screen-reader user moving by heading. Its two chains dropped from `<h3>` to
 * `<h4>` in the same change, because they are now one level deeper than they were — a
 * heading level is real structure (UX-DOCTRINE §2), not a size.
 *
 * ## The step numerals are the page's one large numeric moment
 *
 * A landing page wants big numbers to anchor a scan, and the honest supply here is exactly
 * one: 01/02/03 are an ORDER, not a measurement, so enlarging them claims nothing. Every
 * other number a page like this would enlarge — a percentage, an uptime, an accuracy, a
 * turnaround, a customer count — is one this repository cannot source, and hard rule 11 is
 * why none appears.
 *
 * "by default" in step 02 is not hedging, it is D-163: whether an agent VOLUNTEERS the AI
 * line at the start is a per-agent toggle that ships ON (`ai_disclosure_enabled` DEFAULT
 * true). The unswitchable guarantee is about the ANSWER and lives in the trust chapter.
 */

const STEPS: readonly {
  icon: typeof PhoneCall;
  step: string;
  title: string;
  body: string;
}[] = [
  {
    icon: ListChecks,
    step: "01",
    title: "You say what matters",
    body:
      "Tell the agent about your business and list what it has to find out from each " +
      "caller. That list becomes your columns.",
  },
  {
    icon: PhoneCall,
    step: "02",
    title: "It takes the call",
    body:
      "Someone rings, or the agent works through a list you gave it. It opens by saying " +
      "it is an AI by default, and answers from what you approved.",
  },
  {
    icon: Rows3,
    step: "03",
    title: "You get a lead, not a recording to wade through",
    body:
      "The enquiry lands filled in and sorted, with the audio attached and the key " +
      "moments timestamped if you want to hear it yourself.",
  },
];

/** The flow under the three steps. Five words, in the order they happen. */
const FLOW: readonly string[] = [
  "Call",
  "Conversation",
  "Qualification",
  "Structured lead",
  "Your team follows up",
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
        <ol className={`${GRID} sm:grid-cols-3`}>
          {STEPS.map(({ icon: Icon, step, title, body }, index) => (
            <Reveal as="li" key={step} delay={index * 0.08} className={`relative ${CARD}`}>
              <div className="flex items-baseline justify-between gap-4">
                {/*
                 * The one enlarged number on the page. An order, not a measurement.
                 *
                 * AT FULL STRENGTH, and that is not a style choice. It was
                 * `text-brand-strong/25` — a watermark — until axe in a real Chromium
                 * reported it at 1.47:1 on white and 1.78:1 on the dark palette. A numeral
                 * is TEXT: it is in the accessible name of the step, a screen reader reads
                 * it, and a person with low vision has to be able to. The 3:1 large-text
                 * allowance is not reached for either (and UX-DOCTRINE §8.4 declines to
                 * offer it in any case), so the colour goes to the full token: 6.58:1 here
                 * and 7.78:1 on `--brand-bright` in the dormant dark palette.
                 */}
                <span className="font-mono text-3xl leading-none font-semibold text-brand-strong dark:text-brand-bright">
                  {step}
                </span>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
              </div>
              <h3 className="mt-5 text-lg font-semibold text-ink">{title}</h3>
              <p className="mt-2 text-sm text-ink-muted">{body}</p>
            </Reveal>
          ))}
        </ol>

        {/* The same three steps as the chain a lead actually travels. An ordered list, so
            the sequence is carried by the markup and not only by the chevrons — which are
            decorative for that reason. */}
        <Reveal delay={0.24}>
          <ol className="mt-8 flex flex-wrap items-center gap-x-2 gap-y-2">
            {FLOW.map((stage, index) => (
              <li key={stage} className="flex items-center gap-2">
                <span className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-xs font-semibold text-ink sm:text-sm">
                  {stage}
                </span>
                {index < FLOW.length - 1 && (
                  <ArrowRight aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
                )}
              </li>
            ))}
          </ol>
        </Reveal>

        <Reveal delay={0.1}>
          <h3 className="mt-14 text-xl font-semibold tracking-tight text-balance text-ink sm:mt-16 sm:text-2xl">
            Same leads. Completely different workflow.
          </h3>
          <p className="mt-3 max-w-2xl text-base text-pretty text-ink-muted">
            Nothing about your enquiries changes. What changes is how many hands they pass
            through before anybody sells anything.
          </p>
        </Reveal>
        <BeforeAfter />
      </Band>
    </Chapter>
  );
}
