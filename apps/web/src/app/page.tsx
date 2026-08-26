import type { ReactNode } from "react";
import Link from "next/link";

import { MarketingAccountNav } from "@/components/authn/marketingAccountNav";
import {
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  Building2,
  Check,
  Clock,
  Database,
  FileAudio,
  Filter,
  Globe,
  GraduationCap,
  Handshake,
  Languages,
  ListChecks,
  Lock,
  Megaphone,
  PhoneCall,
  PhoneOutgoing,
  PhoneIncoming,
  Rows3,
  ShieldCheck,
  Stethoscope,
  Table2,
  Umbrella,
  Webhook,
} from "lucide-react";

import { BrandHeaderMark, BrandLockup } from "@/components/brand";

import { CallDemo } from "@/components/marketing/callDemo";
import {
  IsoCallStack,
  IsoHandset,
  IsoKnowledge,
  IsoPipeline,
  IsoShield,
} from "@/components/marketing/isometric";
import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { Faq } from "@/components/marketing/faq";
import { HeroStagger, Reveal, SmoothScroll } from "@/components/marketing/motion";
import { RoiCalculator } from "@/components/marketing/roiCalculator";
import { SIGNUP_CONTACT_EMAIL, SIGNUP_OPEN } from "@/lib/api/signup";
import { CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";

/**
 * Root of `app.calevate.tech` — one of exactly two screens a stranger can reach.
 *
 * ## Every line here is a promise, so every line is one the product already keeps
 *
 * This rule predates the redesign and survives it unchanged: name a behaviour that is
 * enforced in code today, or leave it out. The page got bolder and more animated; it did
 * not get a single new claim. What is still deliberately ABSENT, because the absences are
 * the load-bearing part and a rewrite is exactly when they get quietly reinstated:
 *
 * - **No prices, with ONE deliberate exception.** D-11's managed pricing is negotiated
 *   per client, so no plan price appears. The exception is the ROI calculator (section
 *   03): it shows the published self-serve rate (`self_serve_inr_per_min`, ₹5/min) as the
 *   INPUT to a comparison the buyer drives with their own numbers — a tool, not a tag. A
 *   fixed "₹X/month" would still be the quote nobody can honour; a figure the buyer sets
 *   and checks is not. `publicLanding.test.tsx` scopes its price/percent bans off that one
 *   section and keeps them everywhere else.
 * - **No customer counts, logos or testimonials.** There is no client #1 in production
 *   (ROADMAP M2). "Trusted by N businesses" is the single most-copied line on SaaS
 *   landing pages and it would be a fabrication.
 * - **No uptime, latency or accuracy figures.** `calls.latency` was dropped in migration
 *   `f1a7c39d5be2` and the console itself refuses to print a latency tile (SURFACES §2c).
 *   A marketing page may not claim what the dashboard declines to state. This is also why
 *   the call figure is captioned as an illustration: D-36 records Telugu extraction
 *   quality as UNMEASURED until task #87 scores it.
 * - **No turnaround promise.** Nothing in the product or in ops measures one.
 * - **No integration logos.** The outbound webhook and Sheets sync are real (D-23); a wall
 *   of CRM logos would imply certified integrations that do not exist.
 * - **No data-residency, storage-location or certification claim.** The data section names
 *   which leg is Indian and which is not (Azure OpenAI in East US 2 since D-449) and says
 *   the region is confirmed by a person, not proved by a build. A softer verb over the
 *   wider implication, or a firmer one over the narrow claim, are the same
 *   misrepresentation, so `publicLanding.test.tsx` bans both shapes. Certifications
 *   (SOC 2, ISO 27001, HIPAA) are absent because the company holds none.
 *
 * ## The redesign, section by section — each reads from a shipped surface
 *
 * Structure: hero (+ the one animated call→row figure), a proof strip, "how it works"
 * (three steps), capabilities, verticals, languages, the compliance band (the genuinely
 * differentiating part — four invariants enforced on the dispatch path, hard rule 5, not
 * a policy page), the data section (residency, told straight), the quality report, the
 * FAQ, the two doors, and a closing invitation. Verticals' field lists are COPIED from
 * `scripts/seed.py`'s `VERTICAL_TEMPLATES` label-for-label; which two have a scenario
 * suite is stated, not implied (`tests/fixtures/golden_transcripts.json` carries `cl_*`
 * and `re_*` only). Languages names three because three is what the product offers
 * (`te-IN | hi-IN | en-IN`), Telugu leading because `agents.language_primary`
 * server-defaults to it. Quality is D-15's shipped screen and says what the report
 * REFUSES to print. The FAQ carries its own answer-by-answer backing.
 *
 * ## Motion
 *
 * `SmoothScroll` installs Lenis and the shared GSAP ticker (D-161). All of it is an
 * enhancement: content renders visible and is animated FROM a displaced state, so a
 * failed bundle or a reader who asked for reduced motion gets the same page, immediately.
 * The decorative CSS layer (`.mk-*` in globals.css) is frozen for that reader by the
 * marketing-scoped `prefers-reduced-motion` reset. `data-marketing-root` is what lets
 * `globals.css` hand the document its scrollbar back and paint the marketing-only visual
 * tokens without either rule reaching the fixed app shells under /c and /admin.
 */

/** The section container, one place so every band lines up on the same rhythm. */
/**
 * The page's content column.
 *
 * IT STOPPED GROWING AT 1024px, WHICH IS WHY A BIG SCREEN LOOKED BROKEN. Every width
 * class on this page tops out at `lg`, so a 1152px column sat unchanged in a 1920, 2560 or
 * 3440 viewport — 40%, 55% and 66% of the screen as empty margin, with a 224px illustration
 * marooned at the right edge. Measured in real Chromium at six widths rather than guessed:
 * the shell was 1152px and the headline 896px at every single one of them, and there was no
 * horizontal overflow anywhere, so the complaint was never a scrollbar — it was a layout
 * with no breakpoint above `lg`.
 *
 * `xl` (1280) and `2xl` (1536) now do something. The steps are deliberately small — 1152 →
 * 1280 → 1440 — because a content column is not improved by growing without limit: past
 * roughly 75 characters a line gets hard to track back from, which is why the paragraphs
 * below keep their own `max-w-2xl` regardless of what this does. What the extra room buys
 * is a hero that fills its screen and cards that are not postage stamps on a monitor.
 */
const SHELL = "mx-auto w-full max-w-6xl px-6 xl:max-w-7xl 2xl:max-w-[90rem]";

/** A capability, stated as the behaviour a caller or a client would observe. */
const CAPABILITIES: { icon: typeof PhoneIncoming; title: string; body: string }[] = [
  {
    icon: PhoneIncoming,
    title: "It answers the phone",
    body:
      "A receptionist that picks up, answers what people ask about your business, and " +
      "writes down what they wanted — in Telugu, Hindi or English.",
  },
  {
    icon: Megaphone,
    title: "It calls your list back",
    body:
      "Upload a list and the agent works through it. Anyone who doesn't answer is tried " +
      "again later, and you can pause the whole thing at any point.",
  },
  {
    icon: Table2,
    title: "Every enquiry lands as a row",
    body:
      "You decide what the agent has to find out — name, area, budget, which treatment — " +
      "and those become the columns you sort and follow up from.",
  },
  {
    icon: FileAudio,
    title: "You can listen back",
    body:
      "Every call is recorded and kept. The moments that matter are timestamped, so you " +
      "jump to where the slot was agreed instead of replaying the whole call.",
  },
  {
    icon: Webhook,
    title: "It reaches your own tools",
    body:
      "Send each enquiry to your CRM over a signed webhook, or straight into a Google " +
      "Sheet. Every delivery is logged, and failures are retried.",
  },
  {
    icon: Database,
    title: "Your knowledge, under your control",
    body:
      "Upload your price list or FAQs. Nothing an agent says from it goes live until " +
      "somebody approves it, and we check the published copy still matches ours.",
  },
];

/**
 * The qualification layer — the positioning this page leads its cost argument with.
 *
 * WHY THIS SECTION EXISTS. The cost calculator below used to make one comparison only:
 * Calevate taking the SAME calls a telecaller would. That is honest for a receptionist
 * workload and dishonest for a sales one, because a long call is a sales conversation and
 * nobody's alternative to their closer is a cheaper closer. The comparison that is
 * like-for-like is the split every sales organisation already runs — one person qualifies,
 * another closes; the industry names are SDR and account executive, marketing-qualified
 * and sales-qualified lead, top-of-funnel triage. Calevate is the first half of it.
 *
 * EVERY CARD IS A SHIPPED SURFACE, per this file's rule. In order:
 *  - the first call to every lead: `apps/api/ingest/service.py:1` (webhook-in → lead →
 *    compliance gate → outbound) and `apps/api/campaigns/service.py:1` (list campaigns);
 *    the form→dial gap is timed by `apps/api/core/alerting.py:611::record_speed_to_lead`;
 *  - sorted and written down: `packages/shared/.../extraction.py::ExtractionSchemaSpec`
 *    drives the columns (`apps/api/crm/columns.py:16`), the lead statuses are the fixed
 *    enum in `apps/api/crm/schemas.py:29`, and the hot-lead alert fires off the extracted
 *    fields (`apps/workers/pipeline.py:135::HOT_LEAD_FIELD_TRIGGERS`);
 *  - the funnel the owner reads it back on: `apps/api/crm/performance.py:16,46`
 *    (Calls → Connected → Qualified, qualified = the lead moved past `new`).
 *
 * NO CONVERSION STATISTIC APPEARS HERE, and that is deliberate rather than an omission.
 * The figures this play is usually sold with (a percentage lift from calling in the first
 * minute, a multiple on reaching a decision maker within the hour) trace back to sources
 * this repository could not read and therefore may not repeat — hard rule 11, and
 * `docs/POSITIONING-QUALIFICATION-LAYER.md` names each one and why it was refused. The
 * argument is made with arithmetic the buyer drives in the calculator instead.
 */
const QUALIFICATION: { icon: typeof Filter; title: string; body: string }[] = [
  {
    icon: PhoneOutgoing,
    title: "Everyone on the list gets the first call",
    body:
      "Not the ones your team got to before the day ran out — all of them, in the order " +
      "they came in. A web enquiry becomes an outgoing call without waiting for someone " +
      "to notice it, and the gap between the form and the dial is timed on every one.",
  },
  {
    icon: Filter,
    title: "They come back sorted, not just recorded",
    body:
      "Each call lands as a row with the things you said you needed to know filled in, " +
      "and the lead marked — contacted, interested, hot. Someone who says they want to " +
      "book reaches you as an alert while they are still thinking about it.",
  },
  {
    icon: Handshake,
    title: "Your people open the day on a shortlist",
    body:
      "The long conversation happens with someone who has already been spoken to and " +
      "already said they are interested. Nobody spends their morning finding out who is " +
      "not. Your dashboard reads it back as a funnel: calls, the ones that became " +
      "conversations, and the ones that turned into a qualified lead.",
  },
];

/** The compliance invariants. Each is enforced on the dispatch path, not documented. */
const COMPLIANCE: { icon: typeof Clock; title: string; body: string }[] = [
  {
    icon: Clock,
    title: "9am to 9pm, always",
    body:
      "Outbound calling hours are fixed by the platform, not by a setting you can raise. " +
      "A campaign cannot dial outside them.",
  },
  {
    icon: ShieldCheck,
    title: "Do-not-call is checked first",
    body:
      "Suppressed numbers are scrubbed before every dispatch, and anyone who asks to be " +
      "removed during a call is added straight away.",
  },
  {
    icon: BadgeCheck,
    /*
     * NARROWED TO WHAT IS ACTUALLY UNSWITCHABLE (D-163). The old wording ("Every call
     * says it is an AI … There is no configuration that turns it off") was inverted by a
     * later decision: D-163 made the OPENING ANNOUNCEMENT a per-agent toggle, so the page
     * was promising a buyer the exact thing the product hands their staff a switch for.
     * What survives is stronger for being narrower and is enforced rather than documented:
     * `agents.ai_disclosure_line` is NOT NULL and non-blank, the dial gate refuses an
     * agent without one, and `compose_engine_prompt` appends the truthful answer above the
     * client's script on every publish and every drift sweep (hard rule 5). The wording
     * follows `compliance/disclosure.TRUTHFUL_ANSWER_PROMISE`.
     */
    title: "It never denies being an AI",
    body:
      "Every agent has an AI disclosure line and cannot go live without one. Whether " +
      "it volunteers that line at the start of a call is your setting; that it answers " +
      "honestly when a caller asks — “I am an AI assistant” — is not, and no " +
      "script can override it.",
  },
  {
    icon: Database,
    title: "Recordings are kept for at least 90 days",
    body:
      "The TRAI floor is enforced by the database itself, so a shorter retention policy " +
      "cannot be set — not by you and not by us.",
  },
];

/**
 * The extraction-schema starting points the product ships (`scripts/seed.py`).
 *
 * `fields` are the seed's own labels, in the seed's own order. Copied rather than
 * paraphrased on purpose: this grid's whole value to a buyer is that it is the actual
 * first screen of their agent, and a prettier label here would be a small lie that only
 * shows up on the day they log in. `suite` marks the two the golden-transcript fixtures
 * cover today (`cl_*`, `re_*`).
 */
const VERTICALS: {
  icon: typeof Stethoscope;
  name: string;
  fields: string[];
  suite: boolean;
}[] = [
  {
    icon: Stethoscope,
    name: "Clinics",
    fields: ["Symptom / reason", "Preferred doctor", "Urgency", "Preferred slot", "Insurance"],
    suite: true,
  },
  {
    icon: Building2,
    name: "Property offices",
    fields: ["Budget (lakhs)", "Location", "BHK", "Timeline", "Site visit"],
    suite: true,
  },
  {
    icon: Umbrella,
    name: "Insurance",
    fields: ["Policy type", "Sum assured", "Renewal due", "Existing insurer"],
    suite: false,
  },
  {
    icon: GraduationCap,
    name: "Coaching and colleges",
    fields: ["Course", "Class / year", "Fee concern", "Demo booked"],
    suite: false,
  },
];

/** What the quality report does, including the two things it refuses to do. */
const QUALITY: { term: string; detail: string }[] = [
  {
    term: "Your agent is run against a scenario suite",
    detail:
      "A booking that goes to plan, a caller who talks over the agent, a wrong number, " +
      "an angry caller, a silent line, someone asking to be taken off the list — each " +
      "scored on whether the details reached your leads list correctly.",
  },
  {
    term: "The report is a screen you open, not a file you ask us for",
    detail:
      "It sits in your dashboard beside the calls it was scored on, month by month, with " +
      "the previous months still there to compare against.",
  },
  {
    term: "It states its own limits",
    detail:
      "Where too few calls were scored to support a figure, it prints the count and says " +
      "so instead. The fields the agent is known to struggle with are listed by name.",
  },
];

/** The three steps, kept exact — the AI-by-default nuance in step 02 is D-163. */
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
    // guarantee is in the compliance band below and is about the ANSWER, not the opening.
    body:
      "Someone rings, or the agent works through a list you uploaded. It opens by saying " +
      "it is an AI by default, and answers from what you approved.",
  },
  {
    icon: Rows3,
    step: "03",
    title: "You get a row, not a recording to wade through",
    body:
      "The enquiry lands filled in, with the audio attached and the key moments " +
      "timestamped if you want to hear it yourself.",
  },
];

/** The small editorial label above each band: an index, a hairline, a word. */
function Eyebrow({ index, children }: { index: string; children: ReactNode }) {
  return (
    <p className="flex items-center gap-3 text-xs font-semibold tracking-[0.18em] text-brand-strong uppercase dark:text-brand-bright">
      <span className="font-mono text-ink-faint">{index}</span>
      <span aria-hidden className="h-px w-6 bg-brand/50" />
      {children}
    </p>
  );
}

const CTA_PRIMARY =
  "group inline-flex items-center gap-2 rounded-full bg-brand-strong px-6 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-app";

const CTA_SECONDARY =
  "inline-flex items-center gap-2 rounded-full border border-line bg-surface px-6 py-3 text-sm font-semibold text-ink transition-colors hover:border-brand/50 hover:bg-brand-soft/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-app";

export default function Home() {
  const devSlug = process.env.NEXT_PUBLIC_DEV_ORG_SLUG;

  return (
    <SmoothScroll>
      <div data-marketing-root className="bg-app text-ink">
        <header className="sticky top-0 z-30 border-b border-line bg-surface/80 backdrop-blur-md">
          <div className={`${SHELL} flex items-center justify-between gap-3 py-3.5 sm:gap-4`}>
            {/* The wordmark REPLACES the chip and the word, rather than sitting beside
                them: the artwork already contains the name, and rendering both would say
                "Calevate" twice on the one screen a stranger judges us by. It carries a
                real `alt` for the same reason — it is the name here, not decoration. */}
            {/* Square mark on a phone, wordmark from `sm` — one element, one request.
                The three things in this row do not fit at 320px otherwise; see
                `BrandHeaderMark`, which carries the measurement. */}
            <BrandHeaderMark />
            {/* A client island in a server page: the session cookie is `HttpOnly`, so
                whether this visitor is already signed in can only be answered by asking
                the API. It renders the signed-out header until that lands, and never the
                other way round. */}
            <MarketingAccountNav
              signupLabel={SIGNUP_OPEN ? "Create a workspace" : "Get a workspace"}
            />
          </div>
        </header>

        <main>
          {/* --- Hero ------------------------------------------------------------- */}
          <section className="relative overflow-hidden">
            {/* Decorative background: a masked dotted grid and two soft brand blobs.
                All aria-hidden, all pointer-events-none, all frozen under reduced motion. */}
            <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
              <div className="mk-grid-dots absolute inset-0" />
              <div className="mk-blob mk-blob--a mk-float absolute -top-24 -left-24 h-80 w-80" />
              <div className="mk-blob mk-blob--b mk-float--slow absolute -top-16 right-[-6rem] h-96 w-96" />
            </div>

            <div className={`${SHELL} relative pt-16 pb-10 sm:pt-24`}>
              {/* Decorative isometric accent in the headline's right margin. Only from `xl`,
                  where the `max-w-4xl` headline leaves clear space; below that it is absent
                  so it can never crowd the copy or push the hero wider. */}
              <div
                aria-hidden
                className="pointer-events-none absolute top-40 right-0 hidden w-56 xl:block 2xl:w-72"
              >
                <IsoHandset className="h-auto w-full" />
              </div>
              <HeroStagger>
                <p
                  data-hero-item
                  className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/80 px-3.5 py-1.5 text-xs font-medium text-ink-muted shadow-sm backdrop-blur"
                >
                  <Languages aria-hidden className="h-3.5 w-3.5 text-brand-strong dark:text-brand-bright" />
                  Telugu-first — also Hindi and English
                </p>
                <h1
                  data-hero-item
                  className="mt-6 max-w-4xl text-5xl leading-[1.02] font-semibold tracking-tight text-balance text-ink sm:text-6xl lg:text-7xl 2xl:max-w-5xl 2xl:text-[5.25rem]"
                >
                  Never lose a{" "}
                  <span className="relative inline-block">
                    <span className="relative z-10">customer</span>
                    <span
                      aria-hidden
                      className="absolute inset-x-[-0.12em] bottom-[0.06em] z-0 h-[0.42em] -rotate-1 rounded-sm bg-brand-soft dark:bg-brand-strong/45"
                    />
                  </span>{" "}
                  to a call you couldn&apos;t take.
                </h1>
                <p data-hero-item className="mt-6 max-w-2xl text-lg text-pretty text-ink-muted sm:text-xl">
                  Calevate is an AI receptionist that picks up when you can&apos;t. It answers
                  your callers, follows up on the enquiries you already have, and writes down
                  what each person wanted — in Telugu, Hindi or English.
                </p>
                <div data-hero-item className="mt-9 flex flex-wrap items-center gap-3">
                  <Link href="/signup" className={CTA_PRIMARY}>
                    {SIGNUP_OPEN ? "Create a workspace" : "Get a workspace"}
                    <ArrowRight
                      aria-hidden
                      className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                    />
                  </Link>
                  <Link href="#how" className={CTA_SECONDARY}>
                    See how it works
                  </Link>
                </div>
                {/* Honest positioning, not a metric: who this was built for, and three
                    behaviours each mapped to a shipped feature — no count, no logo wall. */}
                <ul data-hero-item className="mt-9 flex flex-wrap gap-x-6 gap-y-3">
                  {[
                    "Picks up when you can't",
                    "Follows up on your list",
                    "Writes down every enquiry",
                  ].map((claim) => (
                    <li key={claim} className="flex items-center gap-2 text-sm font-medium text-ink-muted">
                      <span
                        aria-hidden
                        className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
                      >
                        <Check className="h-3 w-3" />
                      </span>
                      {claim}
                    </li>
                  ))}
                </ul>
                <p data-hero-item className="mt-6 max-w-2xl text-sm text-ink-faint">
                  Built Telugu-first for clinics, property offices and coaching centres across
                  Andhra Pradesh and Telangana.
                </p>
              </HeroStagger>

              <div className="relative mt-16">
                {/* A glow tucked behind the figure so it reads as lifted off the page. */}
                <div
                  aria-hidden
                  className="mk-blob mk-blob--a pointer-events-none absolute inset-x-10 -top-6 -z-10 h-40"
                />
                <CallDemo />
              </div>
            </div>
          </section>

          {/* --- How it works ------------------------------------------------------ */}
          <section id="how" className="scroll-mt-20 border-t border-line bg-surface/40">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <div className="flex items-center justify-between gap-6">
                <Reveal className="min-w-0 flex-1">
                  <Eyebrow index="01">How it works</Eyebrow>
                  <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                    Three things happen, and you only set up the first one
                  </h2>
                </Reveal>
                {/* Call → record, as a lifting card. Decorative; hidden below `sm` so a
                    portrait phone keeps the full width the heading needs. */}
                <IsoCallStack className="hidden w-36 shrink-0 sm:block lg:w-48" />
              </div>
              <ol className="mt-12 grid gap-6 sm:grid-cols-3">
                {STEPS.map(({ icon: Icon, step, title, body }, index) => (
                  <Reveal
                    as="li"
                    key={step}
                    delay={index * 0.08}
                    className="relative rounded-2xl border border-line bg-surface p-6"
                  >
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
            </div>
          </section>

          {/* --- Capabilities ------------------------------------------------------ */}
          <section className="border-t border-line">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <div className="flex items-center justify-between gap-6">
                <Reveal className="min-w-0 flex-1">
                  <Eyebrow index="02">What it does</Eyebrow>
                  <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                    Everything that happens once it&apos;s answering your calls
                  </h2>
                </Reveal>
                {/* Leads moving through the campaign pipeline. Decorative; `sm`+ only. */}
                <IsoPipeline className="hidden w-40 shrink-0 sm:block lg:w-52" />
              </div>
              <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {CAPABILITIES.map(({ icon: Icon, title, body }, index) => (
                  <Reveal
                    as="section"
                    key={title}
                    delay={(index % 3) * 0.06}
                    className="group rounded-2xl border border-line bg-surface p-6 transition-colors hover:border-brand/40"
                  >
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong transition-transform group-hover:scale-105">
                      <Icon aria-hidden className="h-5 w-5" />
                    </span>
                    <h3 className="mt-5 text-[17px] font-semibold text-ink">{title}</h3>
                    <p className="mt-1.5 text-sm text-ink-muted">{body}</p>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* --- Qualification layer ------------------------------------------------ */}
          {/*
           * The reframe the cost section then puts numbers to: not "AI instead of your
           * staff", but "AI does the triage your staff should never have been doing".
           * See `QUALIFICATION` above for the shipped surface behind each card and for
           * why no conversion statistic appears anywhere in it.
           */}
          <section id="qualify" className="scroll-mt-20 border-t border-line">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <Reveal>
                <Eyebrow index="03">Where your team&apos;s time goes</Eyebrow>
                <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                  Your salespeople should be closing, not finding out who is interested
                </h2>
                <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                  Most of a telecalling day is spent on people who were never going to buy —
                  and you only know which ones those were after the call. Sales teams that
                  can afford it split the job in two: one person qualifies, another closes.
                  Calevate is the first half. It takes the first call to every enquiry and
                  every name on your list, works out who is worth a conversation, and hands
                  your people the shortlist.
                </p>
              </Reveal>
              <div className="mt-12 grid gap-4 lg:grid-cols-3">
                {QUALIFICATION.map(({ icon: Icon, title, body }, index) => (
                  <Reveal
                    as="section"
                    key={title}
                    delay={index * 0.08}
                    className="rounded-2xl border border-line bg-surface p-6"
                  >
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                      <Icon aria-hidden className="h-5 w-5" />
                    </span>
                    <h3 className="mt-5 text-[17px] font-semibold text-ink">{title}</h3>
                    <p className="mt-1.5 text-sm text-ink-muted">{body}</p>
                  </Reveal>
                ))}
              </div>
              <Reveal delay={0.2}>
                <p className="mt-8 max-w-2xl text-sm text-ink-faint">
                  This is not your team replaced. It is the part of their day that was never
                  selling. What stays theirs is the conversation where somebody decides —
                  and after that, the only thing holding you back is how fast you can look
                  after the customers you have won. The section below lets you put your own
                  numbers on that.
                </p>
              </Reveal>
            </div>
          </section>

          {/* --- ROI calculator ---------------------------------------------------- */}
          {/*
           * The one place a price appears (see `roiCalculator.tsx` for why the page's
           * no-prices rule makes an exception for a tool the buyer drives). It turns the
           * core sales argument — AI versus hiring telecallers — into something a prospect
           * checks with their own numbers, at our published self-serve rate.
           */}
          <section id="cost" className="scroll-mt-20 border-t border-line">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <Reveal>
                <Eyebrow index="04">What it costs</Eyebrow>
                <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                  Do the maths against hiring, with your own numbers
                </h2>
                <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                  A telecaller costs far more than the salary in the job ad, and a desk sits
                  idle on a quiet day. Put in what your line handles and see the comparison —
                  every assumption on both sides is yours to change. Two comparisons, and
                  which one is honest depends on the call: Calevate answering the calls
                  outright, or Calevate taking the first call so your team only holds the
                  conversations worth holding.
                </p>
              </Reveal>
              <RoiCalculator />
            </div>
          </section>

          {/* --- Verticals --------------------------------------------------------- */}
          <section id="verticals" className="scroll-mt-20 border-t border-line bg-surface/40">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <Reveal>
                <Eyebrow index="05">Made for your line of work</Eyebrow>
                <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                  It starts with the questions your line of work actually asks
                </h2>
                <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                  A clinic needs to know what hurts and how soon. A property office needs a
                  budget and an area. These are the field lists a new agent starts from —
                  and then you change them, because the columns are yours rather than ours.
                </p>
              </Reveal>
              <div className="mt-12 grid gap-4 sm:grid-cols-2">
                {VERTICALS.map(({ icon: Icon, name, fields, suite }, index) => (
                  <Reveal
                    as="section"
                    key={name}
                    delay={(index % 2) * 0.06}
                    className="rounded-2xl border border-line bg-surface p-6"
                  >
                    <div className="flex items-center gap-3">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                        <Icon aria-hidden className="h-5 w-5" />
                      </span>
                      <h3 className="text-lg font-semibold text-ink">{name}</h3>
                    </div>
                    <ul className="mt-5 flex flex-wrap gap-2">
                      {fields.map((field) => (
                        <li
                          key={field}
                          className="rounded-full border border-line bg-app/60 px-3 py-1 text-xs font-medium text-ink-muted"
                        >
                          {field}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-5 flex items-start gap-2 text-xs text-ink-faint">
                      <span
                        aria-hidden
                        className={
                          "mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full " +
                          (suite ? "bg-brand-bright" : "bg-ink-faint")
                        }
                      />
                      {suite
                        ? "Built against first, with its own suite of test calls behind it."
                        : "The field list ships; the test calls for it are still being written."}
                    </p>
                  </Reveal>
                ))}
              </div>
              <Reveal delay={0.12}>
                <p className="mt-8 max-w-2xl text-sm text-ink-faint">
                  Nothing is locked to a line of work. If yours is not one of these, you
                  write the list of things the agent has to find out, and that is the whole
                  setup — the same as it is for the four above.
                </p>
              </Reveal>
            </div>
          </section>

          {/* --- Languages --------------------------------------------------------- */}
          <section className="border-t border-line">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
                <Reveal>
                  <Eyebrow index="06">Telugu-first</Eyebrow>
                  <h2 className="mt-4 text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                    Telugu first, and not as a setting somebody remembered at the end
                  </h2>
                  <p className="mt-4 max-w-xl text-base text-pretty text-ink-muted">
                    Your callers do not switch to English for your convenience, and a
                    receptionist who makes them is one they hang up on. This was built for
                    Andhra Pradesh and Telangana before it was built for anywhere else.
                  </p>
                  {/* Authentic Telugu, warm rather than decorative-only: the language the
                      agent greets a caller in. `lang` so a screen reader announces it right. */}
                  <p
                    lang="te"
                    className="mt-8 text-4xl font-semibold text-brand-strong dark:text-brand-bright"
                  >
                    నమస్కారం
                    <span className="ml-3 align-middle text-base font-normal text-ink-faint">
                      — how a call opens
                    </span>
                  </p>
                </Reveal>
                <Reveal delay={0.08} as="section">
                  <dl className="grid gap-4 sm:grid-cols-1">
                    {[
                      {
                        term: "Telugu is where an agent starts",
                        detail:
                          "A newly created agent is a Telugu agent until somebody changes " +
                          "it. That is the default in the database, not a suggestion in a guide.",
                      },
                      {
                        term: "Hindi and English are the other two",
                        detail:
                          "Three languages are offered, and only three, because those are " +
                          "the ones we are willing to put a client's callers in front of.",
                      },
                      {
                        term: "The whole agent moves with the language",
                        detail:
                          "The opening line that says it is an AI, the script and the " +
                          "material it answers from are all in the language it speaks.",
                      },
                    ].map(({ term, detail }) => (
                      <div
                        key={term}
                        className="rounded-2xl border border-line bg-surface p-5"
                      >
                        <dt className="text-[17px] font-semibold text-ink">{term}</dt>
                        <dd className="mt-1.5 text-sm text-ink-muted">{detail}</dd>
                      </div>
                    ))}
                  </dl>
                  <p className="mt-6 max-w-xl text-sm text-ink-faint">
                    We publish no score for how well it understands any of them, because a
                    number we cannot show you the working for is worth nothing. What we do
                    publish, for your own agent, is the report further down.
                  </p>
                </Reveal>
              </div>
            </div>
          </section>

          {/* --- Compliance -------------------------------------------------------- */}
          {/*
           * The differentiator, rendered as a deliberately dark brand band so it reads as
           * a spotlight rather than another card grid. It commits to one look in both
           * themes (brand-deep ground, white text) — a considered single-look section, not
           * a token gap: white on `--brand-deep` (#0c5932) clears WCAG AA comfortably, and
           * the four cards below are the four dispatch-path invariants (hard rule 5).
           */}
          <section className="border-t border-line bg-brand-deep text-white">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <div className="flex items-center justify-between gap-8">
                <Reveal className="min-w-0 flex-1">
                  <p className="flex items-center gap-3 text-xs font-semibold tracking-[0.18em] text-brand-bright uppercase">
                    <span className="font-mono text-white/70">07</span>
                    <span aria-hidden className="h-px w-6 bg-white/40" />
                    Built for the Indian rules
                  </p>
                  <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-white sm:text-4xl">
                    The rules live in the code, not in a policy page
                  </h2>
                  <p className="mt-4 max-w-2xl text-base text-pretty text-white/80">
                    An automated call is regulated here, and the agent speaks on your
                    registration. These are not settings with sensible defaults — they are
                    limits the product enforces on every dial.
                  </p>
                </Reveal>
                {/* Compliance-as-a-cube. Its linework is `currentColor`, which is white on
                    this band; decorative, `sm`+ only. */}
                <IsoShield className="hidden w-36 shrink-0 sm:block lg:w-48" />
              </div>
              <div className="mt-12 grid gap-4 sm:grid-cols-2">
                {COMPLIANCE.map(({ icon: Icon, title, body }, index) => (
                  <Reveal
                    as="section"
                    key={title}
                    delay={(index % 2) * 0.06}
                    className="rounded-2xl border border-white/15 bg-white/5 p-6 backdrop-blur-sm"
                  >
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-brand-bright">
                      <Icon aria-hidden className="h-5 w-5" />
                    </span>
                    <h3 className="mt-5 text-[17px] font-semibold text-white">{title}</h3>
                    <p className="mt-1.5 text-sm text-white/80">{body}</p>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* --- Data ------------------------------------------------------------- */}
          <section className="border-t border-line">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <div className="flex items-center justify-between gap-6">
                <Reveal className="min-w-0 flex-1">
                  <Eyebrow index="08">Your customers&apos; data</Eyebrow>
                  <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                    Where it runs, and who can see what
                  </h2>
                </Reveal>
                {/* The layered T0–T4 knowledge base. Decorative; `sm`+ only. */}
                <IsoKnowledge className="hidden w-36 shrink-0 sm:block lg:w-48" />
              </div>
              <div className="mt-12 grid gap-4 lg:grid-cols-3">
                {[
                  {
                    icon: Globe,
                    /*
                     * The residency card, narrowed FOUR times and now WITHDRAWN as an India
                     * claim (D-449, 22 Aug 2026): the declared model region is Azure OpenAI
                     * `eastus2`, still Regional and not Global, speech and first extraction
                     * untouched and still Sarvam. The card names the American half in the
                     * same breath as the Indian half, says the region is confirmed by a
                     * person rather than proved by a build, and points at the sub-processor
                     * page. `publicLanding.test.tsx` pins the exact sentences in BOTH
                     * directions — it must say the Indian half is Indian AND that the model
                     * is not, and it must not claim a build proves residency.
                     *
                     * DO NOT SPELL THE AZURE HOSTNAME IN THIS FILE. `check_model_residency`
                     * line-scans (no TS AST) and a comment naming the watched host reads as
                     * an endpoint built by hand — its docstring accepts that false positive
                     * deliberately. Describing it says the same to a reader and nothing to
                     * the scanner.
                     */
                    term: "Which part runs where, including the part that is not Indian",
                    detail:
                      "Speech and the first reading of your transcript are Indian " +
                      "services, on every call. The language model is not: it runs on a " +
                      "Microsoft Azure OpenAI account in the United States, in the East " +
                      "US 2 region. Until 22 August 2026 that account was in South " +
                      "India and this card said so, and we would rather withdraw the " +
                      "sentence than soften it. What our code still does is pin the " +
                      "model to that one region — no part of our code can send it " +
                      "anywhere else without editing one frozen constant — and the " +
                      "account's own region is confirmed by a person against " +
                      "Microsoft's console and filed: checked, not proved by a build. " +
                      "The platform that carries the call runs it on US infrastructure " +
                      "today, and the sub-processor page says which part is where " +
                      "before you sign.",
                  },
                  {
                    icon: Lock,
                    term: "One business cannot see another",
                    detail:
                      "Separation is enforced by the database on every query, not by " +
                      "application code remembering to filter.",
                  },
                  {
                    icon: ShieldCheck,
                    term: "Phone numbers are hidden by default",
                    detail:
                      "Transcripts come back redacted. Seeing the raw text takes the " +
                      "right role and writes an audit entry.",
                  },
                ].map(({ icon: Icon, term, detail }, index) => (
                  <Reveal
                    as="section"
                    key={term}
                    delay={index * 0.08}
                    className="rounded-2xl border border-line bg-surface p-6"
                  >
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                      <Icon aria-hidden className="h-5 w-5" />
                    </span>
                    <h3 className="mt-5 text-[17px] font-semibold text-ink">{term}</h3>
                    <p className="mt-1.5 text-sm text-ink-muted">{detail}</p>
                  </Reveal>
                ))}
              </div>
              <Reveal delay={0.2}>
                <p className="mt-8 max-w-2xl text-sm text-ink-faint">
                  If one of your customers asks you to delete what we hold on them, there
                  is a button for it and it produces a certificate saying what was
                  destroyed and when.
                </p>
              </Reveal>
            </div>
          </section>

          {/* --- Quality ----------------------------------------------------------- */}
          <section id="quality" className="scroll-mt-20 border-t border-line bg-surface/40">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <Reveal>
                <Eyebrow index="09">Held to a report</Eyebrow>
                <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                  We test your agent, and you read the same report we do
                </h2>
                <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                  An agent that sounds good on the demo call and loses a detail on the
                  fortieth one is the ordinary failure of this whole category. So the
                  testing is not a promise we make on this page — it is a screen in your
                  dashboard, and it is allowed to say bad news.
                </p>
              </Reveal>
              <div className="mt-12 grid gap-4 sm:grid-cols-3">
                {QUALITY.map(({ term, detail }, index) => (
                  <Reveal
                    as="section"
                    key={term}
                    delay={index * 0.08}
                    className="rounded-2xl border border-line bg-surface p-6"
                  >
                    <span className="font-mono text-sm font-semibold text-brand-strong dark:text-brand-bright">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <h3 className="mt-3 text-[17px] font-semibold text-ink">{term}</h3>
                    <p className="mt-1.5 text-sm text-ink-muted">{detail}</p>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* --- Questions --------------------------------------------------------- */}
          <section id="faq" className="scroll-mt-20 border-t border-line">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <Reveal>
                <Eyebrow index="10">Questions</Eyebrow>
                <h2 className="mt-4 text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                  Questions people ask us first
                </h2>
              </Reveal>
              {/* Not wrapped in a Reveal: the answers change the page height when they
                  open, and animating the container that contains the thing doing the
                  resizing is how a reveal ends up half-played. The list is the trigger's
                  own concern — `Faq` refreshes ScrollTrigger on toggle. */}
              <Faq />
            </div>
          </section>

          {/* --- Doors + closing invitation --------------------------------------- */}
          <section className="border-t border-line bg-surface/40">
            <div className={`${SHELL} py-20 sm:py-24`}>
              <div className="grid gap-4 sm:grid-cols-2">
                <Reveal
                  as="section"
                  className="rounded-2xl border border-line bg-surface p-6"
                >
                  <h2 className="text-[17px] font-semibold text-ink">Already a client</h2>
                  <p className="mt-1.5 text-sm text-ink-muted">
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
                <Reveal
                  as="section"
                  delay={0.06}
                  className="rounded-2xl border border-line bg-surface p-6"
                >
                  <h2 className="text-[17px] font-semibold text-ink">
                    {SIGNUP_OPEN ? "New here" : "Not a client yet"}
                  </h2>
                  <p className="mt-1.5 text-sm text-ink-muted">
                    {SIGNUP_OPEN
                      ? "Create your workspace and set up your first agent. Nothing calls anyone until you say so."
                      : "Calevate does not open accounts online. Every workspace is set up by hand with you."}
                  </p>
                  <Link
                    href="/signup"
                    className="mt-4 inline-flex items-center gap-2 rounded-full border border-line px-4 py-2 text-sm font-semibold text-ink transition-colors hover:border-brand/50 hover:bg-brand-soft/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
                  >
                    {SIGNUP_OPEN ? "Create a workspace" : "How to get one"}
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

              {/*
               * A last panel that ASKS rather than claims. The temptation at the bottom of
               * a landing page is one more superlative; there is nothing left to say that
               * is both true and new, so this repeats the offer in the buyer's own terms
               * and hands over the same door as above. The signup flag is read here for the
               * same reason the doors read it.
               */}
              <Reveal
                as="section"
                delay={0.08}
                className="relative mt-4 overflow-hidden rounded-2xl border border-line bg-surface p-8 sm:p-12"
              >
                <div
                  aria-hidden
                  className="mk-blob mk-blob--b pointer-events-none absolute -top-16 right-0 h-56 w-56"
                />
                <h2 className="max-w-3xl text-3xl font-semibold tracking-tight text-balance text-ink sm:text-4xl">
                  The calls you missed today are not on any report
                </h2>
                <p className="mt-4 max-w-2xl text-base text-pretty text-ink-muted">
                  Tell us what your callers ring about and what you need written down
                  about each one. We build the agent with you, in your language, on your
                  own price list and timings — and nothing dials anybody until you say so.
                </p>
                <div className="mt-8 flex flex-wrap items-center gap-3">
                  <Link href="/signup" className={CTA_PRIMARY}>
                    {SIGNUP_OPEN ? "Create a workspace" : "Start a conversation"}
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
            </div>
          </section>
        </main>

        {/*
          THE LEGAL LINKS ARE DERIVED FROM `LEGAL_DOCUMENTS`, not typed out.
          A hand-written list here would be a second enumeration of the eight documents,
          and the one that falls behind is the footer — which is precisely the surface a
          payment aggregator's reviewer checks before approving a merchant account, and
          the surface a data principal is told to look at. `slug` is documented as stable
          for exactly this reason, so iterating is safe as well as shorter.
        */}
        <footer className="border-t border-line px-6 py-10">
          <div className={`${SHELL} flex flex-col gap-5 px-0`}>
            {/* The tagline lockup, and this is the one place it belongs: a footer is
                where a signature reads as a signature rather than as a second headline. */}
            <div className="flex items-center">
              <BrandLockup height={52} />
            </div>
            <nav aria-label="Legal">
              <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
                {LEGAL_DOCUMENTS.map((doc) => (
                  <li key={doc.slug}>
                    <Link
                      href={`/legal/${doc.slug}`}
                      // `inline-block py-1`: see `lib/legal/document.tsx`'s table of
                      // contents for the argument. These eight were an 11px-tall target
                      // in a wrapped list — the shortest in the product — and this is the
                      // footer a payment aggregator's reviewer clicks through.
                      className="inline-block py-1 text-ink-faint underline-offset-4 hover:text-ink hover:underline"
                    >
                      {doc.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            <p className="text-xs text-ink-faint">
              Calevate — AI phone agents for Indian businesses.
            </p>
          </div>
        </footer>
      </div>
    </SmoothScroll>
  );
}
