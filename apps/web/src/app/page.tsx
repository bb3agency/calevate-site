import Link from "next/link";

import {
  ArrowRight,
  ArrowUpRight,
  CalendarCheck,
  Check,
  Clock3,
  Database,
  Filter,
  Globe,
  Handshake,
  Infinity as InfinityIcon,
  Languages,
  ListChecks,
  Lock,
  PhoneCall,
  PhoneIncoming,
  PhoneMissed,
  PhoneOutgoing,
  Rows3,
  ShieldCheck,
  Table2,
  Timer,
  TrendingDown,
  Webhook,
} from "lucide-react";

import { BeforeAfter } from "@/components/marketing/beforeAfter";
import { HeroCallSim } from "@/components/marketing/heroCallSim";
import { IndustryTabs } from "@/components/marketing/industryTabs";
import { LeadInbox } from "@/components/marketing/leadInbox";
import { Faq } from "@/components/marketing/faq";
import { HeroStagger, Reveal } from "@/components/marketing/motion";
import {
  CARD,
  CTA_LABEL,
  CTA_PRIMARY,
  CTA_SECONDARY,
  Eyebrow,
  GRID,
  MarketingPage,
  SECTION,
  SHELL,
} from "@/components/marketing/pageShell";
import { RoiCalculator } from "@/components/marketing/roiCalculator";
import {
  COMPLIANCE_INVARIANTS,
  DATA_PROMISES,
  TESTED_SCENARIOS,
  WHERE_IT_RUNS,
} from "@/lib/marketing/compliance";
import { SIGNUP_CONTACT_EMAIL, SIGNUP_OPEN } from "@/lib/api/signup";
import { CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";

/**
 * Root of `app.calevate.tech` — one of exactly two screens a stranger can reach.
 *
 * ## Every line here is a promise, so every line is one the product already keeps
 *
 * This rule predates every redesign and survives this one unchanged: name a behaviour that
 * is enforced in code today, or leave it out. The page was reorganised around the buyer's
 * problem rather than around our mechanism; it did not gain a single new claim. What is
 * still deliberately ABSENT, because the absences are the load-bearing part and a rewrite
 * is exactly when they get quietly reinstated:
 *
 * - **No prices, with ONE deliberate exception.** D-11's managed pricing is negotiated
 *   per client, so no plan price appears. The exception is the ROI calculator: it shows
 *   the published self-serve rate (`self_serve_inr_per_min`, ₹5/min) as the INPUT to a
 *   comparison the buyer drives with their own numbers — a tool, not a tag.
 *   `publicLanding.test.tsx` scopes its price/percent bans off that one section and keeps
 *   them everywhere else.
 * - **No customer counts, logos, testimonials or case studies.** There is no client #1 in
 *   production (ROADMAP M2). The founder's decision of 5 Sep 2026 is that the proof
 *   section is OMITTED this round rather than filled with placeholders — an empty proof
 *   band reads worse than none, and an invented one is a fabrication.
 * - **No uptime, latency, accuracy or quality figures.** The testing band is a LIST of the
 *   scenarios an agent is run against and carries no score of any kind: nothing in
 *   `apps/api/quality` publishes a per-scenario number this page could stand behind, and
 *   D-36 records Telugu extraction quality as UNMEASURED until task #87 scores it.
 * - **No turnaround promise, and no integration logos.** Nothing measures one; a wall of
 *   CRM logos would imply certified integrations that do not exist.
 * - **No data-residency, storage-location or certification claim.** The trust band names
 *   which leg is Indian and which is not (Azure OpenAI in East US 2 since D-449) and says
 *   the region is confirmed by a person, not proved by a build. Those sentences are
 *   REUSED VERBATIM rather than rewritten: they have been through several correction
 *   rounds, and `publicLanding.test.tsx` pins them in both directions — the page must say
 *   the Indian half is Indian AND that the language model is not, and must not claim a
 *   build proves residency. Certifications (SOC 2, ISO 27001, HIPAA) are absent because we
 *   hold none.
 *
 * ## THE ORDER IS THE NARRATIVE, AND THAT IS WHAT CHANGED
 *
 * The page used to explain HOW the product works before it said why a business owner
 * should care. A clinic owner does not think "I need signed webhooks and timestamped
 * transcripts"; they think "I am missing calls", "leads are not followed up", "my staff
 * wastes hours ringing people who were never serious". So the spine is now
 * PROBLEM → PROMISE → WHAT YOU GET → HOW → EXAMPLES → WHAT YOUR TEAM SEES → COST →
 * TRUST → QUESTIONS → CTA, and every block follows one shape: a headline that is a
 * customer benefit, ONE sentence on why it matters, a visual, and the mechanism behind a
 * disclosure for the reader who wants it.
 *
 *   01 the problem · 02 what changes · 03 how it works · 04 before/after ·
 *   05 what it does · 06 what your team receives · 07 your line of work ·
 *   08 Telugu-first · 09 your sales team · 10 what it costs · 11 why Calevate ·
 *   12 what we do with your customers' data · 13 questions
 *
 * The page got SHORTER without losing a fact, and the way it got shorter is the part to
 * preserve: complexity moved behind interaction. Six use cases are a headline and one
 * sentence with the mechanism inside a `<details>`; four verticals are tabs rather than
 * four stacked cards; the calculator's methodology is one disclosure; the residency
 * paragraph — which may not be shortened, because shortening it would change what it
 * says — sits inside a disclosure in full.
 *
 * ## Motion
 *
 * `SmoothScroll` installs Lenis and the shared GSAP ticker (D-161). All of it is an
 * enhancement: content renders visible and is animated FROM a displaced state, so a failed
 * bundle or a reader who asked for reduced motion gets the same page, immediately. The
 * hero figure is CSS-only for the same reason and one more (`heroCallSim.tsx`).
 * `data-marketing-root` is what lets `globals.css` hand the document its scrollbar back
 * and paint the marketing-only visual tokens without either rule reaching the fixed app
 * shells under /c and /admin.
 */

/*
 * THE SHELL, THE SPACING TOKENS, THE CALL-TO-ACTION CLASSES AND THE EYEBROW ALL MOVED TO
 * `components/marketing/pageShell.tsx`.
 *
 * They were local constants here when this was the only marketing page. There are eight
 * now, and eight copies of `py-16 sm:py-20 lg:py-24` is exactly the drift CLAUDE.md's "one
 * way per problem" rule is about — the copy that falls behind is never the one you are
 * editing. Nothing about the rendered page changed with the move.
 */

/**
 * 01 — THE PROBLEM, in the owner's words rather than ours.
 *
 * A new band, and the one the founder asked for most directly: the page never made the
 * pain explicit, so every benefit after it landed on a reader who had not yet agreed there
 * was anything wrong. Nothing here is a claim about our product, so nothing here needs a
 * shipped surface behind it — but nothing here is a statistic either, because the figures
 * this genre uses (how many calls an SMB misses, what a slow follow-up costs) trace to
 * sources this repository could not read, and hard rule 11 forbids repeating them.
 */
const PROBLEMS: { icon: typeof PhoneMissed; title: string; body: string }[] = [
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

/**
 * 02 — WHAT CHANGES FOR YOUR BUSINESS. Four outcomes, each a shipped behaviour.
 *
 * In order, with what makes each one true:
 *  - answering: an agent runs 24/7 by default (FLOWS §3, `apps/api/agents/business_hours.py`,
 *    whose reader also drives the console's after-hours tile);
 *  - following up: `apps/api/ingest/service.py` turns a web enquiry into a dial through
 *    the compliance gate, `apps/api/campaigns/service.py` works a pasted list, and
 *    `apps/api/core/alerting.py:632::record_speed_to_lead` times the gap;
 *  - qualifying: the six lead statuses are a fixed enum (`apps/api/crm/schemas.py:29`) and
 *    the hot-lead alert fires off the extracted fields
 *    (`apps/workers/pipeline.py:179::HOT_LEAD_FIELD_TRIGGERS`);
 *  - structuring: the per-agent extraction schema is the CRM's column registry
 *    (`apps/api/crm/columns.py`), shared by the table and the CSV export.
 */
const OUTCOMES: { icon: typeof PhoneIncoming; title: string; body: string }[] = [
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

/** 03 — the three steps. The AI-by-default nuance in step 02 is D-163. */
const STEPS: { icon: typeof PhoneCall; step: string; title: string; body: string }[] = [
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
    // "by default" is not hedging — it is D-163. Whether the agent VOLUNTEERS the AI line
    // at the start is a per-agent toggle that ships ON (`ai_disclosure_enabled` DEFAULT
    // true), so this describes what a new agent does rather than a guarantee. The
    // guarantee is in the trust band and is about the ANSWER, not the opening.
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

/**
 * 05 — WHAT IT DOES. Six jobs, benefit first, mechanism behind a disclosure.
 *
 * The rule the founder set and the reason the page got shorter without losing anything:
 * every card leads with what it does FOR YOU, and the "how" is one `<details>` away for
 * the reader who wants it. Each `detail` is the sentence the old page led with.
 *
 * The shipped surface behind each, in order:
 *  1. inbound answering — `apps/api/agents/models.py:43` (`AgentDirection`), 24/7 default
 *     per `apps/api/agents/business_hours.py`;
 *  2. outbound follow-up — `apps/api/campaigns/service.py` + the retry ladder in
 *     `apps/workers/campaign_dispatch.py:1147`; contacts are PASTED (there is no file
 *     input anywhere in this console, `grep 'type="file"' apps/web/src` returns nothing);
 *  3. qualification — `apps/api/crm/schemas.py:29`, `apps/workers/pipeline.py:179`;
 *  4. appointments and callbacks — the `calendar` action kind
 *     (`apps/api/actions/models.py:53`, `apps/api/actions/calendar.py`, gated by
 *     `calendar_configured()` — hence "once your Google account is connected"), and the
 *     in-call callback tool (`apps/voice-runtime/tool_routes.py:268` →
 *     `apps/api/callbacks/service.py`), which needs nothing connected;
 *  5. delivery — the signed outbound webhook (`X-Calevate-Signature` over
 *     `{timestamp}.{body}`, `apps/api/integrations/service.py:176`), the Sheets leg
 *     (`apps/workers/sheets_sync.py`, per-deployment Google credentials) and the CSV
 *     export (`apps/api/crm/routes.py:1017`);
 *  6. knowledge — T0 and nothing else (`docs/TRD.md:948`): the facts a person approves are
 *     compiled into the agent's own prompt at publish time (`apps/api/agents/t0.py`,
 *     `apps/api/kb/service.py:437::approve_source`). There is no document upload — `POST /v1/kb/sources`
 *     takes TEXT and refuses `url`/`file` (`apps/api/kb/routes.py:44`) — so the card may
 *     not offer one, and says the better true thing instead.
 */
const CAPABILITIES: {
  icon: typeof PhoneIncoming;
  title: string;
  benefit: string;
  detail: string;
}[] = [
  {
    icon: PhoneIncoming,
    title: "Answering",
    benefit: "Nobody rings out, whatever time it is",
    detail:
      "It picks up, answers what callers ask from what you approved, and writes down what " +
      "they wanted. An agent runs at every hour unless you tell it otherwise, and your " +
      "dashboard counts how many enquiries arrived after you closed.",
  },
  {
    icon: PhoneOutgoing,
    title: "Follow-up",
    benefit: "Every enquiry gets a first attempt",
    detail:
      "Paste in a list, or let a web enquiry become a call on its own. It works through " +
      "them in order, retries the no-answers on a ladder, and stops the moment you pause it.",
  },
  {
    icon: Filter,
    title: "Qualification",
    benefit: "Your team talks to qualified prospects first",
    detail:
      "Each caller comes back marked contacted, interested or hot — a fixed set of stages, " +
      "not a note somebody has to read and interpret. A hot lead alerts you while the " +
      "person is still thinking about it.",
  },
  {
    icon: CalendarCheck,
    title: "Appointments",
    benefit: "Callers leave the call with a time",
    detail:
      "The agent can book a callback during the call, and can put an appointment straight " +
      "into your calendar once your Google account is connected.",
  },
  {
    icon: Webhook,
    title: "Your own tools",
    benefit: "Your leads don’t get trapped inside Calevate",
    detail:
      "Send them to your CRM or a Google Sheet and keep the workflow your team already " +
      "has, or download the lot as a spreadsheet. Every delivery is logged and failures " +
      "are retried.",
  },
  {
    icon: Database,
    title: "Your answers",
    benefit: "It answers from what you approved, and nothing else",
    detail:
      "Your prices, timings and the questions you get asked every day are built into the " +
      "agent before it takes a call, so the answer comes back straight away. Nothing " +
      "reaches a caller until a person approves it.",
  },
];

/**
 * 09 — WHERE YOUR TEAM'S TIME GOES. The positioning the cost band then puts numbers to.
 *
 * Every card is a shipped surface, per this file's rule:
 *  - the first call to every lead: `apps/api/ingest/service.py` (webhook-in → lead →
 *    compliance gate → outbound) and `apps/api/campaigns/service.py` (list campaigns); the
 *    form→dial gap is timed by `apps/api/core/alerting.py:632::record_speed_to_lead`;
 *  - sorted and written down: the extraction schema drives the columns
 *    (`apps/api/crm/columns.py`), the statuses are the fixed enum in
 *    `apps/api/crm/schemas.py:29`, and the hot-lead alert fires off the extracted fields
 *    (`apps/workers/pipeline.py:179`);
 *  - the funnel the owner reads it back on: `apps/api/crm/performance.py:42,46`
 *    (Calls → Connected → Qualified, qualified = the lead moved past `new`).
 *
 * NO CONVERSION STATISTIC APPEARS HERE. The figures this play is usually sold with trace
 * back to sources this repository could not read and therefore may not repeat — hard rule
 * 11, and `docs/POSITIONING-QUALIFICATION-LAYER.md` names each one and why it was refused.
 */
const QUALIFICATION: { icon: typeof Filter; title: string; body: string }[] = [
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

/**
 * 11 — WHY CALEVATE, beyond what a headcount comparison can see.
 *
 * These five were buried INSIDE the ROI calculator, under "What no headcount maths
 * captures", where a reader only met them after doing arithmetic. They are the answer to
 * "why not just hire somebody", which is a question earlier than cost, so they are a band
 * of their own now and the calculator no longer carries them.
 *
 * Each is a behaviour: 24/7 answering (`apps/api/agents/business_hours.py`), concurrency
 * (the engine dials per call, not per desk), no hiring cycle, the same questions asked
 * every time (the extraction schema, `apps/api/crm/columns.py`), and the dispatch-path
 * invariants (calling hours and DNC, `apps/api/compliance/service.py:208,621`).
 */
const BEYOND: { icon: typeof Clock3; title: string; body: string }[] = [
  {
    icon: Clock3,
    title: "Your phone doesn’t clock out",
    body:
      "Evenings, Sundays and festival days are answered at the same rate as a Tuesday " +
      "morning. There is no shift to staff for them.",
  },
  {
    icon: InfinityIcon,
    title: "A busy hour is not a queue",
    body:
      "Fifty callers at 11am are fifty answered calls, not fifty people waiting behind " +
      "three desks.",
  },
  {
    icon: TrendingDown,
    title: "Nothing to train, and nothing resigns",
    body:
      "No six-week ramp, no re-hiring in four months. It is doing the job the day you " +
      "switch it on, and the same job a year later.",
  },
  {
    icon: ListChecks,
    title: "The same questions, every single call",
    body:
      "The things you said you needed to know get asked whether it is the third call of " +
      "the day or the ninetieth.",
  },
  {
    icon: ShieldCheck,
    title: "The rules on every dial",
    body:
      "Calling hours, do-not-call scrubbing and the AI-disclosure answer are enforced on " +
      "every call rather than left to a person to remember.",
  },
];

/** 08 — the same question, in the three languages the product offers. */
const SAME_QUESTION: { lang: string; label: string; text: string }[] = [
  { lang: "te", label: "తెలుగు", text: "రేపు డాక్టర్ గారు ఉంటారా?" },
  { lang: "hi", label: "हिन्दी", text: "क्या कल डॉक्टर उपलब्ध हैं?" },
  { lang: "en", label: "English", text: "Is the doctor available tomorrow?" },
];

export default function Home() {
  const devSlug = process.env.NEXT_PUBLIC_DEV_ORG_SLUG;

  return (
    <MarketingPage>
      {/* --- Hero ------------------------------------------------------------- */}
      <section className="relative overflow-hidden">
        {/* Decorative background: a masked dotted grid and two soft brand blobs.
            All aria-hidden, all pointer-events-none, all frozen under reduced motion. */}
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
          <div className="mk-grid-dots absolute inset-0" />
          <div className="mk-blob mk-blob--a mk-float absolute -top-24 -left-24 h-80 w-80" />
          <div className="mk-blob mk-blob--b mk-float--slow absolute -top-16 right-[-6rem] h-96 w-96" />
        </div>

        {/*
         * `pt-8` ON A PHONE, `pt-14` FROM `sm` — AND THAT IS THE FIX THE FOUNDER ASKED
         * FOR FIRST. The hero opened with `pt-10 pb-10 sm:pt-20 lg:pt-24` under a
         * sticky header that already contributes ~56px of its own, so the first thing
         * on the page sat roughly 136px down a 640px-tall phone screen — a fifth of the
         * viewport spent on nothing, above the one sentence the whole page depends on
         * being read. The desktop step is smaller than it was for the same reason and
         * not a different one.
         */}
        <div className={`${SHELL} relative pt-8 pb-12 sm:pt-14 sm:pb-16 lg:pt-16`}>
          <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12">
            <HeroStagger>
              <p
                data-hero-item
                className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/80 px-3.5 py-1.5 text-xs font-medium text-ink-muted shadow-sm backdrop-blur"
              >
                <Languages aria-hidden className="h-3.5 w-3.5 text-brand-strong dark:text-brand-bright" />
                Telugu-first · Hindi · English
              </p>
              <h1
                data-hero-item
                /*
                 * 40px ON A PHONE, NOT 48px. At `text-5xl` inside a 320px content box
                 * this headline set to four lines and pushed the call to action off a
                 * 640px screen — the one thing a hero may not do.
                 */
                className="mt-5 max-w-4xl text-[2.5rem] leading-[1.05] font-semibold tracking-tight text-balance text-ink sm:mt-6 sm:text-6xl sm:leading-[1.02] lg:text-[3.75rem]"
              >
                Never miss a lead because{" "}
                <span className="relative inline-block">
                  <span className="relative z-10">nobody answered</span>
                  <span
                    aria-hidden
                    className="absolute inset-x-[-0.12em] bottom-[0.06em] z-0 h-[0.42em] -rotate-1 rounded-sm bg-brand-soft dark:bg-brand-strong/45"
                  />
                </span>
                .
              </h1>
              <p data-hero-item className="mt-5 max-w-2xl text-lg text-pretty text-ink-muted sm:text-xl">
                Calevate answers your calls, follows up on every enquiry, works out who
                is worth your team’s time, and turns each conversation into a lead they
                can act on.
              </p>
              {/*
               * WHO IT IS FOR, ABOVE THE BUTTON. This sentence used to be the LAST
               * thing in the hero, so on a phone the one reader this page is written
               * for had to scroll past the call to action to find out it was addressed
               * to them. `publicLanding.test.tsx` pins the ORDER, not the words.
               */}
              <p data-hero-item className="mt-3 max-w-2xl text-sm text-pretty text-ink-faint">
                Built Telugu-first for clinics, property offices, insurance advisors and
                coaching centres across Andhra Pradesh and Telangana.
              </p>
              <div data-hero-item className="mt-7 flex flex-wrap items-center gap-3">
                <Link href="/signup" className={CTA_PRIMARY}>
                  {CTA_LABEL}
                  <ArrowRight
                    aria-hidden
                    className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                  />
                </Link>
                <Link href="#how" className={CTA_SECONDARY}>
                  See how it works
                </Link>
              </div>
              {/*
               * Four behaviours, each mapped to a shipped feature — no count, no logo
               * wall, and no number of any kind. This is the only thing this page has
               * in the slot a landing page normally fills with borrowed proof.
               */}
              <ul
                data-hero-item
                className="mt-7 flex flex-col gap-y-2.5 sm:flex-row sm:flex-wrap sm:gap-x-6 sm:gap-y-3"
              >
                {[
                  "Answers day and night",
                  "Follows up on every enquiry",
                  "Qualifies before your team calls",
                  "Books appointments",
                ].map((claim) => (
                  <li key={claim} className="flex items-center gap-2 text-sm font-medium text-ink-muted">
                    <span
                      aria-hidden
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                    >
                      <Check className="h-3 w-3" />
                    </span>
                    {claim}
                  </li>
                ))}
              </ul>
            </HeroStagger>

            <div className="relative">
              {/* A glow tucked behind the figure so it reads as lifted off the page. */}
              <div
                aria-hidden
                className="mk-blob mk-blob--a pointer-events-none absolute inset-x-6 -top-6 -z-10 h-40"
              />
              <HeroCallSim />
            </div>
          </div>
        </div>
      </section>

      {/* --- 01 The problem ---------------------------------------------------- */}
      <section id="problem" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="01">The problem</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              The calls you missed today are not on any report
            </h2>
          </Reveal>
          <div className={`${GRID} sm:grid-cols-3`}>
            {PROBLEMS.map(({ icon: Icon, title, body }, index) => (
              <Reveal as="section" key={title} delay={index * 0.08} className={CARD}>
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
                <h3 className="mt-5 text-[17px] font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-sm text-pretty text-ink-muted">{body}</p>
              </Reveal>
            ))}
          </div>
          <Reveal delay={0.24}>
            <p className="mt-8 max-w-2xl text-base text-pretty text-ink">
              Calevate handles the first layer of phone work so your team can spend the
              day on the conversations that matter.
            </p>
          </Reveal>
        </div>
      </section>

      {/* --- 02 What changes --------------------------------------------------- */}
      <section id="outcomes" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="02">What changes</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              What is different in your business by next week
            </h2>
          </Reveal>
          <div className={`${GRID} sm:grid-cols-2`}>
            {OUTCOMES.map(({ icon: Icon, title, body }, index) => (
              <Reveal
                as="section"
                key={title}
                delay={(index % 2) * 0.06}
                className={`${CARD} transition-colors hover:border-brand/40`}
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
                <h3 className="mt-5 text-xl font-semibold text-balance text-ink">{title}</h3>
                <p className="mt-2 text-base text-pretty text-ink-muted">{body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* --- 03 How it works --------------------------------------------------- */}
      <section id="how" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="03">How it works</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              Three things happen, and you only set up the first one
            </h2>
          </Reveal>
          <ol className={`${GRID} sm:grid-cols-3`}>
            {STEPS.map(({ icon: Icon, step, title, body }, index) => (
              <Reveal as="li" key={step} delay={index * 0.08} className={`relative ${CARD}`}>
                <div className="flex items-center justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                    <Icon aria-hidden className="h-5 w-5" />
                  </span>
                  <span className="font-mono text-sm font-semibold text-ink-faint">{step}</span>
                </div>
                <h3 className="mt-5 text-lg font-semibold text-ink">{title}</h3>
                <p className="mt-2 text-sm text-ink-muted">{body}</p>
              </Reveal>
            ))}
          </ol>
          {/* The same three steps as the chain a lead actually travels. An ordered
              list, so the sequence is carried by the markup and not only by the
              chevrons — which are decorative for that reason. */}
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
        </div>
      </section>

      {/* --- 04 Before / after ------------------------------------------------- */}
      <section id="workflow" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="04">Before and after</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              Same leads. Completely different workflow.
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              Nothing about your enquiries changes. What changes is how many hands they
              pass through before anybody sells anything.
            </p>
          </Reveal>
          <BeforeAfter />
        </div>
      </section>

      {/* --- 05 What it does --------------------------------------------------- */}
      <section id="capabilities" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="05">What it does</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              One AI receptionist. Several jobs.
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              Each of these is one thing off your team’s plate. Open a card if you want
              to know exactly how it works.
            </p>
          </Reveal>
          <div className={`${GRID} sm:grid-cols-2 lg:grid-cols-3`}>
            {CAPABILITIES.map(({ icon: Icon, title, benefit, detail }, index) => (
              <Reveal
                as="section"
                key={title}
                delay={(index % 3) * 0.06}
                className={`group ${CARD} transition-colors hover:border-brand/40`}
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
                <p className="mt-5 text-xs font-semibold tracking-[0.14em] text-ink-faint uppercase">
                  {title}
                </p>
                <h3 className="mt-1.5 text-[17px] font-semibold text-balance text-ink">
                  {benefit}
                </h3>
                {/*
                 * The mechanism, one keystroke away. `<details>` rather than a built
                 * accordion for the reason the FAQ records: it is the platform's own
                 * disclosure widget, keyboard-operable and announced with no script at
                 * all — and this page's rule is that it is finished without its bundle.
                 */}
                <details className="mt-3">
                  <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong [&::-webkit-details-marker]:hidden dark:text-brand-bright">
                    Learn more
                    <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                  </summary>
                  <p className="mt-2 text-sm text-pretty text-ink-muted">{detail}</p>
                </details>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* --- 06 What your team receives --------------------------------------- */}
      <section id="leads" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="06">What your team receives</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              Stop replaying calls to find out who is serious
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              This is what your employee opens tomorrow morning instead of a list of
              numbers nobody can explain.
            </p>
          </Reveal>
          <LeadInbox />
        </div>
      </section>

      {/* --- 07 Your line of work --------------------------------------------- */}
      <section id="industries" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="07">Your line of work</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              It asks the questions your trade actually asks
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              A clinic needs to know what hurts and how soon. A property office needs a
              budget and an area. These are the field lists a new agent starts from —
              and then you change them, because the columns are yours rather than ours.
            </p>
          </Reveal>
          <IndustryTabs />
          <Reveal delay={0.12}>
            <p className="mt-8 max-w-2xl text-sm text-ink-faint">
              Nothing is locked to a line of work. If yours is not one of these, you
              write the list of things the agent has to find out, and that is the whole
              setup — the same as it is for the four above.
            </p>
          </Reveal>
        </div>
      </section>

      {/* --- 08 Telugu-first --------------------------------------------------- */}
      <section id="languages" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
            <Reveal>
              <Eyebrow index="08">Telugu-first</Eyebrow>
              <h2 className="mt-4 text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                Your customers shouldn’t have to change language to reach you
              </h2>
              <p className="mt-4 max-w-xl text-base text-pretty text-ink-muted">
                Your callers do not switch to English for your convenience, and a
                receptionist who makes them is one they hang up on. A new agent is a
                Telugu agent until somebody changes it — that is the default in the
                database, not a suggestion in a guide — and the opening line, the
                script and the answers all move with the language it speaks.
              </p>
              <p className="mt-6 max-w-xl text-sm text-ink-faint">
                Three languages are offered, and only three, because those are the ones
                we are willing to put a client’s callers in front of. We publish no
                score for how well it understands any of them: a number we cannot show
                you the working for is worth nothing.
              </p>
            </Reveal>
            <Reveal delay={0.08} as="section" className={CARD}>
              <h3 className="text-sm font-semibold text-ink">
                The same question, asked three ways
              </h3>
              <p className="mt-1.5 text-sm text-ink-muted">
                Your agent answers all three on the same number.
              </p>
              <ul className="mt-5 space-y-3">
                {SAME_QUESTION.map(({ lang, label, text }) => (
                  <li
                    key={lang}
                    className="rounded-xl border border-line bg-app/60 px-4 py-3"
                  >
                    <p className="text-[11px] font-semibold tracking-wide text-ink-faint uppercase">
                      {label}
                    </p>
                    <p lang={lang} className="mt-1 text-lg text-ink">
                      {text}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="mt-5 border-t border-line pt-4 text-sm text-ink-muted">
                Each of them comes back to you as the same row: who rang, what they
                wanted, and when they can come in.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* --- 09 Your sales team ------------------------------------------------ */}
      <section id="sales" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="09">Your sales team</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              Your salespeople should be closing, not finding out who is interested
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              Calevate is not your salesperson. It is the layer that makes your
              salesperson more productive: it takes the first call to every enquiry and
              every name on your list, works out who is worth a conversation, and hands
              your people the shortlist.
            </p>
          </Reveal>
          <div className={`${GRID} lg:grid-cols-3`}>
            {QUALIFICATION.map(({ icon: Icon, title, body }, index) => (
              <Reveal as="section" key={title} delay={index * 0.08} className={CARD}>
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
                <h3 className="mt-5 text-[17px] font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-sm text-pretty text-ink-muted">{body}</p>
              </Reveal>
            ))}
          </div>
          <Reveal delay={0.2}>
            <p className="mt-8 max-w-2xl text-sm text-ink-faint">
              This is not your team replaced. It is the part of their day that was never
              selling. The goal is not to automate your business — it is to automate the
              parts of the phone workflow your team should not be spending their day on.
            </p>
          </Reveal>
        </div>
      </section>

      {/* --- 10 What it costs -------------------------------------------------- */}
      {/*
       * The one place a price appears (see `roiCalculator.tsx` for why the page's
       * no-prices rule makes an exception for a tool the buyer drives). It sits HERE,
       * below the problem, the outcomes, the workflow and the product, because a
       * calculator asks a visitor to do arithmetic about a problem they have not yet
       * agreed they have — which is why it used to lose people at band 06.
       */}
      <section id="cost" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="10">What it costs</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              Do the maths against hiring, with your own numbers
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              Three numbers you already know. Everything else is pre-filled and sitting
              behind “Adjust assumptions”, where you can change any of it.
            </p>
          </Reveal>
          <RoiCalculator />

          {/*
           * THE SAME DOOR, OFFERED AGAIN AT THE ONE POINT ON THE PAGE WHERE THE READER
           * HAS JUST DONE WORK. Not a competing call to action — GOV.UK's rule is
           * against multiple DIFFERENT default buttons; every primary button on this
           * page is one action, one destination and one label.
           *
           * The three lines under it are risk reversal, and each is a shipped fact: a
           * person approves every word before an agent can answer with it
           * (`apps/api/kb/service.py:437::approve_source`, `apps/api/agents/service.py:1193`), a
           * campaign is a draft until somebody launches it
           * (`apps/api/campaigns/service.py:1199`), and pause stops the next dispatch
           * tick (`POST /v1/campaigns/{id}/pause`, `apps/api/campaigns/routes.py:731`).
           */}
          <Reveal as="section" delay={0.1} className={`mt-10 ${CARD} sm:mt-12`}>
            <h3 className="text-xl font-semibold tracking-tight text-balance text-ink sm:text-2xl">
              Worth a conversation?
            </h3>
            <p className="mt-3 max-w-2xl text-base text-pretty text-ink-muted">
              Those figures came out of what you typed, not out of a claim we made. If
              the shape of it works for your business, the next step is a short
              conversation — we build the agent with you, and you hear exactly what it
              will say before it ever picks up.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Link href="/signup" className={CTA_PRIMARY}>
                {CTA_LABEL}
                <ArrowRight
                  aria-hidden
                  className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                />
              </Link>
            </div>
            <ul className="mt-6 grid gap-2.5 border-t border-line pt-5 sm:grid-cols-3">
              {[
                "You approve every word before it goes live",
                "Nothing dials anybody until you launch it",
                "Pause it from your dashboard whenever you want",
              ].map((promise) => (
                <li key={promise} className="flex items-start gap-2 text-sm text-ink-muted">
                  <span
                    aria-hidden
                    className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                  >
                    <Check className="h-3 w-3" />
                  </span>
                  {promise}
                </li>
              ))}
            </ul>
          </Reveal>
        </div>
      </section>

      {/* --- 11 Why Calevate --------------------------------------------------- */}
      <section id="why" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="11">Why Calevate</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              The part a headcount comparison cannot see
            </h2>
          </Reveal>
          <div className={`${GRID} sm:grid-cols-2 lg:grid-cols-3`}>
            {BEYOND.map(({ icon: Icon, title, body }, index) => (
              <Reveal as="section" key={title} delay={(index % 3) * 0.06} className={CARD}>
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon aria-hidden className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-[17px] font-semibold text-balance text-ink">{title}</h3>
                <p className="mt-1.5 text-sm text-pretty text-ink-muted">{body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* --- 12 Trust ---------------------------------------------------------- */}
      {/*
       * COMPRESSED IN LAYOUT, NOT IN WORDING. The compliance invariants, the data
       * statements and the residency paragraph are reused verbatim — they are legally
       * load-bearing and have been corrected several times — but they no longer occupy
       * three full bands of the primary sales story. Two of them now sit inside
       * disclosures, which is the "move complexity behind interaction" rule applied to
       * the one content on this page that may not be shortened by rewriting.
       */}
      <section id="trust" className="scroll-mt-20 border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="12">Trust</Eyebrow>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              An automated call is regulated here, and we built for that
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              The agent speaks on your registration, so these are not settings with
              sensible defaults — they are limits the product enforces on every dial.
            </p>
          </Reveal>

          <div className={`${GRID} lg:grid-cols-3`}>
            <Reveal as="section" className={CARD}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <ShieldCheck aria-hidden className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-[17px] font-semibold text-ink">
                The rules live in the code
              </h3>
              <p className="mt-1.5 text-sm text-pretty text-ink-muted">
                Four things are enforced on the dispatch path rather than written in a
                policy page.
              </p>
              <details className="mt-3">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong [&::-webkit-details-marker]:hidden dark:text-brand-bright">
                  See all four
                  <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                </summary>
                <dl className="mt-3 space-y-3">
                  {COMPLIANCE_INVARIANTS.map(({ icon: Icon, title, body }) => (
                    <div key={title}>
                      <dt className="flex items-center gap-2 text-sm font-semibold text-ink">
                        <Icon aria-hidden className="h-4 w-4 shrink-0 text-brand-strong dark:text-brand-bright" />
                        {title}
                      </dt>
                      <dd className="mt-1 text-sm text-pretty text-ink-muted">{body}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </Reveal>

            <Reveal as="section" delay={0.08} className={CARD}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <Globe aria-hidden className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-[17px] font-semibold text-ink">
                Know where your customer data goes
              </h3>
              <p className="mt-1.5 text-sm text-pretty text-ink-muted">
                Which part of a call runs where, including the parts that are not
                Indian. In full, in our words, before you sign anything.
              </p>
              <details className="mt-3">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong [&::-webkit-details-marker]:hidden dark:text-brand-bright">
                  Where each part runs
                  <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                </summary>
                {/*
                 * VERBATIM, AND FROM ONE DEFINITION. `lib/marketing/compliance.ts`
                 * holds this text and the history behind it — narrowed four times,
                 * withdrawn as an India claim by D-449, and narrowed again on
                 * 27 Aug 2026 on the Indian half. `/security` renders the same
                 * constant, so the two surfaces cannot drift apart, and
                 * `publicLanding.test.tsx` pins it here in both directions.
                 */}
                <p className="mt-3 text-sm text-pretty text-ink-muted">{WHERE_IT_RUNS}</p>
                <p className="mt-3 text-sm">
                  <Link
                    href="/legal/subprocessors"
                    className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                  >
                    Read the sub-processor page
                  </Link>
                </p>
              </details>
            </Reveal>

            <Reveal as="section" delay={0.16} className={CARD}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                <Lock aria-hidden className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-[17px] font-semibold text-ink">
                Your customers’ data stays yours
              </h3>
              <dl className="mt-3 space-y-3">
                {DATA_PROMISES.map(({ term, detail }) => (
                  <div key={term}>
                    <dt className="text-sm font-semibold text-ink">{term}</dt>
                    <dd className="mt-1 text-sm text-pretty text-ink-muted">{detail}</dd>
                  </div>
                ))}
              </dl>
            </Reveal>
          </div>

          {/* The testing band, compressed to what it is: a list of what gets tested.
              No score of any kind — see `TESTED_SCENARIOS` for why. */}
          <Reveal as="section" delay={0.24} className={`mt-4 ${CARD}`}>
            <h3 className="text-[17px] font-semibold text-ink">
              Your agent is run against awkward calls before it takes a real one
            </h3>
            <p className="mt-1.5 max-w-2xl text-sm text-pretty text-ink-muted">
              An agent that sounds good on the demo call and loses a detail on the
              fortieth one is the ordinary failure of this whole category. These are the
              calls it is put through. We publish no score for them, because a number we
              cannot show you the working for is worth nothing.
            </p>
            <ul className="mt-4 flex flex-wrap gap-2">
              {TESTED_SCENARIOS.map((scenario) => (
                <li
                  key={scenario}
                  className="flex items-center gap-2 rounded-full border border-line bg-app/60 px-3 py-1.5 text-xs font-medium text-ink-muted"
                >
                  <Check aria-hidden className="h-3.5 w-3.5 text-brand-strong dark:text-brand-bright" />
                  {scenario}
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal delay={0.3}>
            <p className="mt-6 text-sm text-ink-muted">
              The whole of it is written down:{" "}
              <Link
                href="/legal"
                className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
              >
                our legal and compliance pages
              </Link>
              .
            </p>
          </Reveal>
        </div>
      </section>

      {/* --- 13 Questions ------------------------------------------------------ */}
      <section id="faq" className="scroll-mt-20 border-t border-line bg-surface/40">
        <div className={`${SHELL} ${SECTION}`}>
          <Reveal>
            <Eyebrow index="13">Questions</Eyebrow>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              Questions people ask us first
            </h2>
          </Reveal>
          {/* Not wrapped in a Reveal: the answers change the page height when they
              open, and animating the container that contains the thing doing the
              resizing is how a reveal ends up half-played. */}
          <Faq />
        </div>
      </section>

      {/* --- Doors + closing invitation --------------------------------------- */}
      <section className="border-t border-line">
        <div className={`${SHELL} ${SECTION}`}>
          {/*
           * A last panel that closes on the reader's future state rather than on one
           * more superlative. Both reassurance lines were checked against the code
           * before being written: approval before anything is answerable
           * (`apps/api/kb/service.py:437::approve_source` review states, `agents/service.py:1193::publish_agent`
           * publish), and the campaign launch gate (`campaigns/service.py:1199` —
           * a campaign is a draft until a person launches it).
           */}
          <Reveal
            as="section"
            className="relative overflow-hidden rounded-2xl border border-line bg-surface p-6 sm:p-10 lg:p-12"
          >
            <div
              aria-hidden
              className="mk-blob mk-blob--b pointer-events-none absolute -top-16 right-0 h-56 w-56"
            />
            <h2 className="max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
              Your next customer could already be trying to reach you
            </h2>
            <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
              Tell us what your callers ring about and what you need written down about
              each one. We build the agent with you, in your language, on your own price
              list and timings. You approve the agent before it goes live, and nothing
              calls a customer until you launch it.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/signup" className={CTA_PRIMARY}>
                {CTA_LABEL}
                <ArrowRight
                  aria-hidden
                  className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                />
              </Link>
              {/* Only when there is an address to give — an invented one bounces. */}
              {SIGNUP_CONTACT_EMAIL && (
                <a href={`mailto:${SIGNUP_CONTACT_EMAIL}`} className={CTA_SECONDARY}>
                  Write to us
                  <ArrowUpRight aria-hidden className="h-4 w-4" />
                </a>
              )}
            </div>
          </Reveal>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Reveal as="section" className={CARD}>
              <h2 className="text-[17px] font-semibold text-ink">Already a client</h2>
              <p className="mt-1.5 text-sm text-pretty text-ink-muted">
                Your workspace is at{" "}
                <code className="rounded bg-black/5 px-1 font-mono text-[13px] text-ink dark:bg-white/10">
                  /c/your-slug
                </code>{" "}
                — the URL your account manager gave you.
              </p>
              <Link
                href={CLIENT_SIGN_IN_PATH}
                className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-surface dark:text-brand-bright"
              >
                Sign in
                <ArrowRight aria-hidden className="h-3.5 w-3.5" />
              </Link>
              {/* Local development only: unset in every deployed build, so this renders
                  nothing rather than offering a stranger a link into somebody's tenant. */}
              {devSlug && (
                <Link
                  href={`/c/${devSlug}`}
                  className="mt-4 ml-4 inline-flex items-center gap-2 rounded-full bg-brand-strong px-4 py-2 text-sm font-semibold text-white hover:bg-brand-deep"
                >
                  Open {devSlug}
                  <ArrowRight aria-hidden className="h-4 w-4" />
                </Link>
              )}
            </Reveal>

            {/*
             * The self-serve door (D-34), told the truth about on the page a stranger
             * reads FIRST. `self_serve_signup_enabled` defaults OFF (R-11's kill
             * switch), so on most deployments the answer is "we open accounts with
             * you" — and rendering "Sign up free" over that is a claim the product
             * cannot keep, dressed as a button.
             */}
            <Reveal as="section" delay={0.06} className={CARD}>
              <h2 className="text-[17px] font-semibold text-ink">
                {SIGNUP_OPEN ? "New here" : "Not a client yet"}
              </h2>
              <p className="mt-1.5 text-sm text-pretty text-ink-muted">
                {SIGNUP_OPEN
                  ? "Set up your first agent. Nothing calls anyone until you say so."
                  : "Calevate does not open accounts online. Every workspace is set up by hand with you."}
              </p>
              <Link
                href="/signup"
                className="mt-4 inline-flex items-center gap-2 rounded-full border border-line px-4 py-2 text-sm font-semibold text-ink transition-colors hover:border-brand/50 hover:bg-brand-soft/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
              >
                How to get one
                <ArrowRight aria-hidden className="h-4 w-4" />
              </Link>
              {/* Only when there is an address to give. An invented one bounces. */}
              {!SIGNUP_OPEN && SIGNUP_CONTACT_EMAIL && (
                <p className="mt-3 text-sm text-ink-muted">
                  Or write to{" "}
                  <a
                    className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                    href={`mailto:${SIGNUP_CONTACT_EMAIL}`}
                  >
                    {SIGNUP_CONTACT_EMAIL}
                  </a>
                  .
                </p>
              )}
            </Reveal>
          </div>
        </div>
      </section>
    </MarketingPage>
  );
}
