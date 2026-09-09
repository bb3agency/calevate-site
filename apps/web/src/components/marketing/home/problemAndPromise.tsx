import {
  Filter,
  PhoneIncoming,
  PhoneMissed,
  PhoneOutgoing,
  Table2,
  Timer,
} from "lucide-react";

import { Reveal } from "@/components/marketing/motion";

import { Band, Chapter, HOME } from "./band";

/**
 * CHAPTER 1 — the problem, then the promise. TWO BANDS THAT USED TO BE TWO CHAPTERS.
 *
 * They were bands 01 and 02, each with its own hairline, its own 80px of padding either
 * side and its own identically-sized heading, which said to the reader that "the calls you
 * missed" and "what is different by next week" are two topics. They are one: the second is
 * the answer to the first, and a reader who has just agreed they are losing calls should
 * meet the resolution inside the same breath rather than after a rule and a colour change.
 *
 * The RANKING is the whole point of putting them together. The problem is `standard`; the
 * promise is one of the page's three `anchor` bands, because it is the sentence the buyer
 * is here to test. Under the old page they were the same size and the reader had no way to
 * tell which one was the offer.
 *
 * ## The problems are not cards any more, and that is UX-DOCTRINE §1
 *
 * "Kill the everything-is-a-`Card` default": a card is a container for a bounded job with
 * its own controls and its own outcome. These three are PROSE — one observation each, no
 * control, no outcome — and boxing them made three panels compete with the four that
 * follow, which really are the offer. They are rows now, on a hairline grid.
 *
 * ## Nothing here is a claim about our product, and nothing here is a statistic
 *
 * The figures this genre opens with (how many calls an SMB misses, what a slow follow-up
 * costs) trace to sources this repository could not read; hard rule 11 forbids repeating
 * them, so the problem is stated as a scene rather than as a number.
 *
 * The four outcomes each name a shipped behaviour, unchanged from the page they came from:
 *  - answering: 24/7 by default (FLOWS §3, `apps/api/agents/business_hours.py`);
 *  - following up: `apps/api/ingest/service.py` turns a web enquiry into a dial through the
 *    compliance gate, `apps/api/campaigns/service.py` works a pasted list, and
 *    `apps/api/core/alerting.py:632::record_speed_to_lead` times the gap;
 *  - qualifying: the six lead statuses are a fixed enum (`apps/api/crm/schemas.py:29`) and
 *    the hot-lead alert fires off the extracted fields
 *    (`apps/workers/pipeline.py:179::HOT_LEAD_FIELD_TRIGGERS`);
 *  - structuring: the per-agent extraction schema is the CRM's column registry
 *    (`apps/api/crm/columns.py`), shared by the table and the CSV export.
 */

const PROBLEMS: readonly { icon: typeof PhoneMissed; title: string; body: string }[] = [
  {
    icon: PhoneMissed,
    title: "The calls nobody answered",
    body:
      "Your staff is with another customer when a new enquiry rings. The caller does not " +
      "leave a message — they ring the next business on the list.",
  },
  {
    icon: Timer,
    title: "The enquiry that went cold",
    body:
      "A form arrives at 11am. Somebody notices it at 2pm. By then the person has already " +
      "spoken to somebody else.",
  },
  {
    icon: PhoneOutgoing,
    title: "The hours spent finding out who is serious",
    body:
      "Your salespeople work down the whole list to discover which few were interested. " +
      "That is not selling; it is sorting.",
  },
];

const OUTCOMES: readonly { icon: typeof PhoneIncoming; title: string; body: string }[] = [
  {
    icon: PhoneIncoming,
    title: "Every enquiry gets answered",
    body:
      "Your phone is picked up while your staff is busy, after you close, and on a " +
      "festival day — in the language the caller rang you in.",
  },
  {
    icon: PhoneOutgoing,
    title: "Follow-up stops depending on somebody remembering",
    body:
      "Every new enquiry gets a first call without waiting for a person to notice it, and " +
      "the gap between the form and the dial is timed on every one.",
  },
  {
    icon: Filter,
    title: "Your team talks to qualified people first",
    body:
      "Instead of opening with “Hello, what are you looking for?”, your team opens with " +
      "“Priya wants a root canal and asked for Tuesday evening.”",
  },
  {
    icon: Table2,
    title: "Calls become information you can act on",
    body:
      "Not scattered recordings, diary notes and WhatsApp messages — rows you can sort, " +
      "filter and hand to somebody.",
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
        {/* THREE ROWS, NOT THREE COLUMNS — and this is the second time this grid has been
            broken. The 9 Sep 2026 pass took it out of three `Card`s (§1: prose is not a
            panel) and left it as three columns divided by a hairline, which kept the
            defect that matters here: three observations arriving at once, each in a 380px
            column at 14px, so the reader parses a layout before they read a sentence. One
            column, one observation at a time, at the page's own body size. */}
        <ul className={`${HOME.contentGap} divide-y divide-line border-y border-line`}>
          {PROBLEMS.map(({ icon: Icon, title, body }, index) => (
            <Reveal
              as="li"
              key={title}
              delay={index * 0.08}
              className="flex flex-col gap-4 py-8 sm:flex-row sm:gap-8 sm:py-10"
            >
              <Icon
                aria-hidden
                className="h-7 w-7 shrink-0 text-brand-strong sm:mt-1 dark:text-brand-bright"
              />
              <div>
                <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>
                  {title}
                </h3>
                <p className={`mt-3 max-w-2xl text-pretty text-ink-muted ${HOME.body}`}>{body}</p>
              </div>
            </Reveal>
          ))}
        </ul>
      </Band>

      <Band
        id="outcomes"
        eyebrow="What changes"
        weight="anchor"
        className={HOME.bandGap}
        title="What is different in your business by next week"
        lede="Calevate handles the first layer of phone work so your team can spend the day on the conversations that matter."
      >
        {/* TWO-UP, and it stays two-up: these four ARE panels — one outcome each, four
            parallel answers to the three observations above — and a four-row column would
            spend a screenful and a half saying so. What changed is the scale: the card
            padding, the title and the body all move onto the page's own scale, so two
            cards fill a screenful instead of four competing inside one. */}
        <div className={`${HOME.contentGap} grid ${HOME.itemGap} sm:grid-cols-2`}>
          {OUTCOMES.map(({ icon: Icon, title, body }, index) => (
            <Reveal
              as="section"
              key={title}
              delay={(index % 2) * 0.06}
              className={`${HOME.panel} ${HOME.panelLift}`}
            >
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft text-brand-strong">
                <Icon aria-hidden className="h-7 w-7" />
              </span>
              <h3 className={`mt-6 ${HOME.itemTitle} font-semibold text-balance text-ink`}>
                {title}
              </h3>
              <p className={`mt-3 text-pretty text-ink-muted ${HOME.bodySm}`}>{body}</p>
            </Reveal>
          ))}
        </div>
      </Band>
    </Chapter>
  );
}
