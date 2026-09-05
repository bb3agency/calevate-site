import type { Metadata } from "next";
import Link from "next/link";

import {
  CalendarCheck,
  Check,
  Database,
  Filter,
  PhoneIncoming,
  PhoneOutgoing,
  Webhook,
  X,
} from "lucide-react";

import {
  CARD,
  ClosingCta,
  Eyebrow,
  INLINE_LINK,
  MarketingPage,
  PageIntro,
  SECTION,
  SHELL,
} from "@/components/marketing/pageShell";

/**
 * `/solutions` — the six jobs an agent does, at the length the homepage deliberately
 * refuses.
 *
 * ## What this page is FOR, and why it is not a longer version of the homepage band
 *
 * The homepage's use-case band is six benefit headlines with the mechanism one keystroke
 * away. That is the right shape there: a first-time visitor is deciding whether this is
 * for them at all. It is the wrong shape for the reader who has decided it might be and
 * now wants to know exactly what they are buying — and that reader used to have nowhere to
 * go. This page is where the detail legitimately lives, so each job says four things the
 * homepage cannot fit: what it does for you, what actually happens, what YOU set up, and
 * what it deliberately does not do.
 *
 * ## The rule is unchanged: name a behaviour that is enforced in code, or leave it out
 *
 * Every `does` bullet below cites the code that makes it true, at the point of use. Two
 * kinds of honesty carry more weight here than anywhere else on the site, because this is
 * the page a buyer reads with a pen:
 *
 * 1. **A CONDITION is stated in the same sentence as the capability.** Google Calendar and
 *    Google Sheets both need a Google account connected — `calendar_configured()` gates
 *    every calendar route (`apps/api/actions/calendar.py:52`) and
 *    `sheets_delivery_available()` decides the Sheets leg per deployment. Those are vendor-
 *    account blockers on us, not code gaps, and a page that omitted the condition would be
 *    selling a control the client will not find.
 * 2. **The `never` list is not a disclaimer, it is the product.** "It does not read a
 *    document mid-call" is a truer description of this product than any paragraph about
 *    what it does, and it is the sentence that stops a buyer arriving at a console looking
 *    for an upload button that does not exist (`apps/api/kb/routes.py:44` refuses `url`
 *    and `file`; there is no file input anywhere in this console).
 */
export const metadata: Metadata = {
  title: "Solutions — Calevate",
  description:
    "The six jobs a Calevate agent does for an Indian SMB: answering, follow-up, " +
    "qualification, appointments, delivery to your own tools, and answering from facts " +
    "you approved — with what each one does not do.",
};

interface Solution {
  readonly id: string;
  readonly icon: typeof PhoneIncoming;
  readonly kicker: string;
  readonly title: string;
  readonly lede: string;
  /** What actually happens, in the owner's words. */
  readonly does: readonly string[];
  /** What the client sets up, so the buyer knows the work on their side. */
  readonly yours: readonly string[];
  /** What it does NOT do. The most useful paragraph on the page. */
  readonly never: readonly string[];
}

const SOLUTIONS: readonly Solution[] = [
  {
    id: "answering",
    icon: PhoneIncoming,
    kicker: "Answering",
    title: "Nobody rings out, whatever time it is",
    lede:
      "The call your staff could not reach is the one that goes to the next business on " +
      "the list. This is the job that stops that happening.",
    does: [
      // `AgentDirection` (apps/api/agents/models.py:43) and FLOWS §3's 24/7 default,
      // read by apps/api/agents/business_hours.py.
      "It picks up while your staff is with somebody else, after you close, on a Sunday and on a festival day. An agent runs at every hour unless you tell it otherwise.",
      // ai_disclosure_enabled DEFAULT true (D-163); the line itself is NOT NULL and
      // non-blank (apps/api/agents/models.py:192,304).
      "It opens by saying it is an AI — that announcement is a switch you own, and the honest ANSWER when a caller asks is not.",
      // apps/api/agents/models.py:215 server_default 'te-IN'.
      "It holds the call in Telugu, Hindi or English. Telugu is where a new agent starts, because that is the database's own default rather than a note in a guide.",
      // apps/api/crm/service.py:27 count_after_hours_calls -> after_hours_captured_7d.
      "Your dashboard counts how many enquiries arrived outside your own opening hours, so the thing you could not see before is now a number you can read.",
    ],
    yours: [
      "Your opening hours, so the after-hours count means something.",
      "The sentence it opens with, and whether it volunteers the AI line at the start.",
      "The list of things it has to find out from a caller.",
    ],
    never: [
      "It does not look anything up mid-call. What it can say is compiled into the agent before the call — see “Your answers” below.",
      // `BOLNA_CAPABILITIES.transfer=False` (`apps/api/engine/bolna.py:2996`) and the same
      // on the other adapter (`cartesia.py:367`): "nothing this tree publishes configures a
      // transfer tool" (`bolna.py:1260`). So this is stronger than a policy — the agent has
      // no way to do it.
      "It does not put a caller through to a person. Call transfer is not something this platform does today, so a caller who needs your staff is written down for you to ring back rather than handed over mid-call.",
    ],
  },
  {
    id: "follow-up",
    icon: PhoneOutgoing,
    kicker: "Follow-up",
    title: "Every enquiry gets a first attempt",
    lede:
      "The enquiry that arrives at 11am and gets noticed at 2pm has usually already " +
      "spoken to somebody else. Follow-up stops depending on a person remembering.",
    does: [
      // apps/api/ingest/service.py:1 — webhook-in -> lead -> compliance gate -> outbound.
      "A web enquiry can become a call without waiting for anybody to notice it: the lead lands, the compliance gate runs, and the dial follows.",
      // apps/api/core/alerting.py:632::record_speed_to_lead.
      "The gap between the form arriving and the dial going out is timed on every one, so “we call back quickly” becomes something you can check.",
      // apps/api/campaigns/service.py; contacts are pasted — there is no file input in
      // this console (`grep 'type="file"' apps/web/src` returns nothing).
      // Two dispatch ticks cannot double-dial a person: the claim commits before the
      // first dial and stamps `last_attempt_at` (`apps/workers/campaign_dispatch.py:39,222,
      // 352`). So this is a property of the design rather than a promise about care.
      "For a list, you paste the numbers in — CSV or one per line — and it works through them in the order they came. Nobody is rung twice by the same run, whatever else goes wrong.",
      // apps/workers/campaign_dispatch.py:1147 retry ladder.
      "A no-answer goes back on a retry ladder rather than being lost, and it exhausts rather than retrying for ever.",
      // apps/api/campaigns/routes.py:731 POST /{campaign_id}/pause.
      "Pause stops it starting calls at the next tick. A repeat you scheduled can be stopped the same way before its next run.",
    ],
    yours: [
      "The list, and when it may run — inside the platform's own 9am–9pm window, never outside it.",
      "The registration paperwork, which the product refuses to dial without.",
    ],
    never: [
      "It does not dial outside 9am–9pm, and that is not a setting you can raise.",
      "It does not dial a number on your do-not-call list, which is scrubbed before every dispatch.",
      "It does not launch itself. A campaign is a draft until a person launches it.",
    ],
  },
  {
    id: "qualification",
    icon: Filter,
    kicker: "Qualification",
    title: "Your team talks to qualified prospects first",
    lede:
      "Most of a telecalling day is spent finding out who was never going to buy, and " +
      "you only learn which ones those were afterwards. This is the half of the job that " +
      "should not have been a person's.",
    does: [
      // apps/api/crm/schemas.py:29 — a fixed Literal, not free text.
      "Every caller comes back marked: new, contacted, interested, hot, won or lost. A fixed set of stages, so two people reading the same list read the same thing.",
      // apps/workers/pipeline.py:179 HOT_LEAD_FIELD_TRIGGERS.
      "A hot lead alerts you off what was actually said, while the person is still thinking about it.",
      // apps/api/crm/columns.py — one registry, shared by the table and the CSV export.
      "The answers land in the columns you chose, so the list is sortable and filterable rather than a pile of recordings.",
      // apps/api/crm/performance.py:42,46.
      "You can read the whole thing back as a funnel — calls, the ones that became a conversation, and the ones that moved past new.",
    ],
    yours: [
      "The questions that decide whether somebody is worth your team's time.",
      "Who on your team sees the list at all, which is a role rather than a password shared around.",
    ],
    never: [
      "It does not score a person out of ten, and it does not rank your leads by a confidence number. Nothing in the product measures one, so nothing publishes one.",
      "It does not decide who to drop. Everybody it spoke to is on your list with what they said.",
    ],
  },
  {
    id: "appointments",
    icon: CalendarCheck,
    kicker: "Appointments",
    title: "Callers leave the call with a time",
    lede:
      "An enquiry that ends in “somebody will call you back” is an enquiry you now have " +
      "to work. One that ends with a slot is a booking.",
    does: [
      // apps/voice-runtime/tool_routes.py:268 -> apps/api/callbacks/service.py. Needs
      // nothing connected.
      "The agent can book a callback during the call — “ring me Tuesday at four” — and the dispatch tick rings them at that time. This needs nothing connected.",
      // apps/api/actions/models.py:53 ACTION_KINDS includes "calendar";
      // apps/api/actions/calendar.py builds the freebusy + insert requests, gated by
      // calendar_configured() at :52.
      "It can check your calendar and put the appointment straight into it, once your Google account is connected.",
      // apps/api/callbacks/service.py — GRACE settles a callback rather than retrying
      // for ever.
      "A callback that cannot be placed settles with a visible reason instead of retrying quietly for the life of the campaign.",
    ],
    yours: [
      "Which calendar, and the Google account it lives in.",
      "What counts as a slot you are willing to give away.",
    ],
    never: [
      // The calendar leg asks for two scopes only — `calendar.freebusy` and
      // `calendar.events` — and the code behind them builds exactly two requests: a
      // free/busy query and an event insert (`apps/api/actions/calendar.py:43,168,180`).
      // The full `calendar` scope was refused deliberately, in that file's own words,
      // because it "would let us delete anything".
      "It does not move or cancel an appointment somebody else made. It asks your calendar what is free and adds an event; that is the whole of what it is allowed to do there.",
      "Nothing about your calendar is available until you connect it — the routes refuse cleanly rather than half-working.",
    ],
  },
  {
    id: "delivery",
    icon: Webhook,
    kicker: "Your own tools",
    title: "Your leads don’t get trapped inside Calevate",
    lede:
      "A tool your team has to remember to open is a tool your team stops opening. Send " +
      "the leads where the work already happens.",
    does: [
      // apps/api/integrations/service.py:176 SIGNATURE_HEADER, :250 sign_payload —
      // HMAC-SHA256 over `{timestamp}.{body}`.
      "Push each lead to your own CRM over a signed webhook, so your system can prove the request came from us and is not a replay of an old one.",
      // apps/workers/sheets_sync.py + apps/workers/google_sheets.py (D-23).
      "Or send them into a Google Sheet, once your Google account is connected.",
      // apps/api/crm/routes.py:1017 media_type="text/csv"; columns resolved by the same
      // registry as the screen (apps/api/crm/columns.py).
      "Or download the lot as a spreadsheet, with the same columns you chose on screen — the table and the file cannot disagree about what a column is.",
      "Every delivery is logged and failures are retried, so “it went to the CRM” is a thing you can check rather than assume.",
    ],
    yours: [
      "The endpoint, and the secret we sign with.",
      "Which columns leave the building — downloading the whole contact list is its own permission and writes an audit entry naming who took it.",
    ],
    never: [
      "There is no certified integration with any named CRM, and this site shows no integration logos, because that would imply one.",
      "Nothing is delivered anywhere you have not configured.",
    ],
  },
  {
    id: "answers",
    icon: Database,
    kicker: "Your answers",
    title: "It answers from what you approved, and nothing else",
    lede:
      "The question every owner asks second is “what if it says the wrong thing”. The " +
      "answer is structural rather than reassuring.",
    does: [
      // T0 and nothing else (docs/TRD.md:948) — the approved facts are compiled into the
      // agent's own prompt at publish time (apps/api/agents/t0.py).
      "Your prices, timings and the questions you get asked every day are built INTO the agent before it takes a call, so the answer comes back straight away with nothing to wait for.",
      // apps/api/kb/service.py:348 'pending_approval', :437 the CAS approve.
      "A fact somebody submits is pending until a person approves it. Nothing reaches a caller until that has happened.",
      // apps/api/agents/service.py:1193 publish_agent; compose_engine_prompt appends the
      // truthful-answer promise above the client's script (hard rule 5).
      "Publishing is the moment a change reaches live calls, and the truthful answers about being an AI and about recording are appended above your script every single time.",
    ],
    yours: [
      "The facts themselves, in your words.",
      "Who is allowed to approve them.",
    ],
    never: [
      "It does not read a PDF, a brochure or a price list. There is no document upload, because there is nothing behind one — the endpoint takes text and refuses a file outright.",
      "It does not search the open internet, and it does not answer from anything you have not approved.",
    ],
  },
];

function SolutionSection({ solution, index }: { solution: Solution; index: number }) {
  const Icon = solution.icon;
  return (
    <section
      id={solution.id}
      className={
        "scroll-mt-20 border-t border-line " + (index % 2 === 1 ? "bg-surface/40" : "")
      }
    >
      <div className={`${SHELL} ${SECTION}`}>
        <div className="flex items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
            <Icon aria-hidden className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <Eyebrow index={String(index + 1).padStart(2, "0")}>{solution.kicker}</Eyebrow>
            <h2 className="mt-3 max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
              {solution.title}
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              {solution.lede}
            </p>
          </div>
        </div>

        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          <div className={`${CARD} lg:col-span-2`}>
            <h3 className="text-sm font-semibold tracking-[0.14em] text-ink-faint uppercase">
              What happens
            </h3>
            <ul className="mt-4 space-y-3">
              {solution.does.map((line) => (
                <li key={line} className="flex items-start gap-2.5 text-[15px] text-pretty text-ink-muted">
                  <span
                    aria-hidden
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                  >
                    <Check className="h-3 w-3" />
                  </span>
                  {line}
                </li>
              ))}
            </ul>
          </div>

          <div className="grid gap-4">
            <div className={CARD}>
              <h3 className="text-sm font-semibold tracking-[0.14em] text-ink-faint uppercase">
                What you set up
              </h3>
              <ul className="mt-3 space-y-2">
                {solution.yours.map((line) => (
                  <li key={line} className="text-sm text-pretty text-ink-muted">
                    {line}
                  </li>
                ))}
              </ul>
            </div>
            <div className={CARD}>
              <h3 className="text-sm font-semibold tracking-[0.14em] text-ink-faint uppercase">
                What it does not do
              </h3>
              <ul className="mt-3 space-y-2.5">
                {solution.never.map((line) => (
                  <li key={line} className="flex items-start gap-2.5 text-sm text-pretty text-ink-muted">
                    <X aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
                    {line}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function SolutionsPage() {
  return (
    <MarketingPage>
      <PageIntro
        eyebrow="Solutions"
        title="One AI receptionist. Six jobs off your team’s plate."
        lede="Each of these is a piece of phone work your staff is doing today. Here is what each one actually does, what you set up, and — the part most pages leave out — what it deliberately does not do."
      >
        <nav aria-label="On this page" className="mt-8">
          <ul className="flex flex-wrap gap-2">
            {SOLUTIONS.map((solution) => (
              <li key={solution.id}>
                <Link
                  href={`#${solution.id}`}
                  className="inline-block rounded-full border border-line bg-surface px-3.5 py-2 text-sm font-medium text-ink-muted transition-colors hover:border-brand/50 hover:text-ink touch:py-2.5"
                >
                  {solution.kicker}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </PageIntro>

      {SOLUTIONS.map((solution, index) => (
        <SolutionSection key={solution.id} solution={solution} index={index} />
      ))}

      <section className="border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            The goal is not to automate your business
          </h2>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            It is to automate the parts of the phone workflow your team should not be
            spending their day on. Everything above is the first layer of a call — the
            picking up, the asking, the writing down, the chasing. The conversation where
            somebody decides is still your salesperson&apos;s, and it goes better because
            they are having it with somebody who already said yes.
          </p>
          <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
            See{" "}
            <Link href="/why-calevate" className={INLINE_LINK}>
              why Calevate
            </Link>{" "}
            for the part a headcount comparison cannot price, or{" "}
            <Link href="/roi" className={INLINE_LINK}>
              run the numbers
            </Link>{" "}
            on your own volumes.
          </p>
        </div>
      </section>

      <ClosingCta line="Your next customer could already be trying to reach you" />
    </MarketingPage>
  );
}
