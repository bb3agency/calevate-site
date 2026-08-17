import Link from "next/link";
import {
  ArrowRight,
  BadgeCheck,
  Building2,
  Clock,
  Database,
  FileAudio,
  GraduationCap,
  Languages,
  Megaphone,
  PhoneIncoming,
  ShieldCheck,
  Stethoscope,
  Table2,
  Umbrella,
  Webhook,
} from "lucide-react";

import { CallDemo } from "@/components/marketing/callDemo";
import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { Faq } from "@/components/marketing/faq";
import { HeroStagger, Reveal, SmoothScroll } from "@/components/marketing/motion";
import { SIGNUP_CONTACT_EMAIL, SIGNUP_OPEN } from "@/lib/api/signup";

/**
 * Root of `app.calevate.tech` — one of exactly two screens a stranger can reach.
 *
 * ## Every line here is a promise, so every line is one the product already keeps
 *
 * This rule predates the redesign and survives it unchanged: name a behaviour that is
 * enforced in code today, or leave it out. The page got longer and more animated; it did
 * not get a single new claim. What is still deliberately ABSENT, because the absences are
 * the load-bearing part and a rewrite is exactly when they get quietly reinstated:
 *
 * - **No prices.** D-11's managed pricing is negotiated per client and D-34's self-serve
 *   tier has no published number. A price here is a quote nobody can honour.
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
 * - **No data-residency, storage-location or certification claim.** This one was NOT
 *   absent and had to be removed: the data section used to say "It stays in India —
 *   calls, transcripts and recordings are processed and stored in Indian regions", and
 *   nothing in this repository supports it. DEPLOYMENT §0 puts the whole site stack,
 *   including the Postgres holding every transcript and phone number, on a
 *   general-purpose VPS with **India co-location explicitly NOT required**; §1 puts
 *   object storage on Cloudflare R2 with `AWS_REGION=auto`; SECURITY-COMPLIANCE §4
 *   records Bolna call recordings observed on S3 `us-east-1` and marks the residency
 *   posture as something to be pinned in a CONTRACT that does not exist yet; Clerk,
 *   Resend and Sentry are all outside India; and no deploy has ever run, so the hosting
 *   region is genuinely undecided rather than merely unwritten — a founder's decision
 *   this page must not pre-empt. What survives is the one narrow claim that is
 *   ENFORCED: model endpoints are pinned to an Indian region, and
 *   `scripts/check_model_residency.py` fails the build on anything else. A softer verb
 *   over the same implication ("your data lives in India") is the same
 *   misrepresentation, so `publicLanding.test.tsx` bans the shape rather than trusting
 *   the next writer to remember why. Certifications (SOC 2, ISO 27001, HIPAA) are
 *   likewise absent because the company holds none.
 *
 * ## What the redesign added, and why each section is defensible
 *
 * Every capability below maps to a shipped surface, and the compliance section is the one
 * that is genuinely differentiating rather than decorative — each of its four lines is an
 * invariant enforced on the dispatch path (hard rule 5), not a policy page. The recording
 * and key-moments card is D-153/D-156, both shipped. The retention line is the TRAI
 * 90-day floor, enforced by a database CHECK rather than by intent.
 *
 * ## The sections added after the redesign, and what each one is reading from
 *
 * - **Verticals.** The field lists are COPIED from `scripts/seed.py`'s
 *   `VERTICAL_TEMPLATES`, label for label, so the page shows the columns a new agent
 *   really starts with rather than a plausible-looking set. Which two have a scenario
 *   suite behind them is stated rather than implied: `tests/fixtures/
 *   golden_transcripts.json` carries `cl_*` and `re_*` cases and nothing for the other
 *   two, and BRD §3 calls insurance and education fast-follow.
 * - **Languages.** Three, because three is what the product offers — `Language` in
 *   `apps/api/agents/voices.py` and `CreateOrgIn.language` in `apps/api/admin/routes.py`
 *   are `te-IN | hi-IN | en-IN` — and Telugu leads because `agents.language_primary`
 *   server-defaults to it. No comprehension or naturalness figure: D-36 records Telugu
 *   extraction quality as UNMEASURED, and TRD §5 records Bulbul's wider language count
 *   without a list, which is why the page names three and not eleven.
 * - **Quality.** D-15's client-facing report, which is a shipped screen
 *   (`/c/<slug>/quality`, `GET /v1/quality/reports`). The section says what the report
 *   REFUSES to print, because that is the differentiating part and it is enforced in
 *   `lib/api/quality.ts` rather than promised here.
 * - **FAQ** — see `components/marketing/faq.tsx`, which carries its own answer-by-answer
 *   backing, including why the cost answer names a structure and no number.
 * - **A closing invitation** rather than a closing claim. It repeats the doors' honesty
 *   about how an account is actually opened instead of introducing a new promise.
 *
 * ## Motion
 *
 * `SmoothScroll` installs Lenis and the shared GSAP ticker (D-161). All of it is an
 * enhancement: content renders visible and is animated FROM a displaced state, so a
 * failed bundle or a reader who asked for reduced motion gets the same page, immediately.
 * `data-marketing-root` is what lets `globals.css` hand the document back its scrollbar
 * without the rule being able to reach the fixed app shells under /c and /admin.
 */

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
    title: "Every call says it is an AI",
    body:
      "The disclosure is part of the agent and cannot be left empty. There is no " +
      "configuration that turns it off.",
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
 * cover today (`cl_*`, `re_*`) — stated on the card rather than left to be assumed of
 * all four.
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

export default function Home() {
  const devSlug = process.env.NEXT_PUBLIC_DEV_ORG_SLUG;

  return (
    <SmoothScroll>
      <div data-marketing-root className="bg-app">
        <header className="sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-4">
            <span className="text-base font-semibold tracking-tight text-ink">Calevate</span>
            <nav className="flex items-center gap-2">
              <Link
                href="/sign-in"
                className="rounded-md px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
              >
                Sign in
              </Link>
              <Link
                href="/signup"
                className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-strong"
              >
                {SIGNUP_OPEN ? "Create a workspace" : "Get a workspace"}
                <ArrowRight aria-hidden className="h-3.5 w-3.5" />
              </Link>
            </nav>
          </div>
        </header>

        <main>
          {/* --- Hero ------------------------------------------------------------- */}
          <section className="mx-auto w-full max-w-5xl px-6 pt-16 pb-8 sm:pt-24">
            <HeroStagger>
              <p
                data-hero-item
                className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-muted"
              >
                <Languages aria-hidden className="h-3.5 w-3.5" />
                Telugu, Hindi and English
              </p>
              <h1
                data-hero-item
                className="mt-5 max-w-3xl text-4xl font-semibold tracking-tight text-balance text-ink sm:text-5xl"
              >
                The calls you miss are the customers you lose.
              </h1>
              <p data-hero-item className="mt-5 max-w-2xl text-lg text-ink-muted">
                Calevate answers the phone when you can&apos;t, follows up on the enquiries
                you already have, and writes down what each caller actually wanted — in the
                language they actually speak.
              </p>
              <div data-hero-item className="mt-8 flex flex-wrap items-center gap-3">
                <Link
                  href="/signup"
                  className="inline-flex items-center gap-2 rounded-md bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-strong"
                >
                  {SIGNUP_OPEN ? "Create a workspace" : "Get a workspace"}
                  <ArrowRight aria-hidden className="h-4 w-4" />
                </Link>
                <Link
                  href="#how"
                  className="inline-flex items-center gap-2 rounded-md border border-line px-5 py-2.5 text-sm font-semibold text-ink hover:bg-black/5 dark:hover:bg-white/5"
                >
                  See how it works
                </Link>
              </div>
            </HeroStagger>

            <CallDemo />
          </section>

          {/* --- How it works ------------------------------------------------------ */}
          <section id="how" className="mx-auto w-full max-w-5xl scroll-mt-20 px-6 py-20">
            <Reveal>
              <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                Three things happen, and you only set up the first one
              </h2>
            </Reveal>
            <ol className="mt-10 grid gap-6 sm:grid-cols-3">
              {[
                {
                  step: "01",
                  title: "You say what matters",
                  body:
                    "Tell the agent about your business and list what it has to find out " +
                    "from each caller. That list becomes your columns.",
                },
                {
                  step: "02",
                  title: "It takes the call",
                  body:
                    "Someone rings, or the agent works through a list you uploaded. It " +
                    "opens by saying it is an AI, and answers from what you approved.",
                },
                {
                  step: "03",
                  title: "You get a row, not a recording to wade through",
                  body:
                    "The enquiry lands filled in, with the audio attached and the key " +
                    "moments timestamped if you want to hear it yourself.",
                },
              ].map(({ step, title, body }, index) => (
                <Reveal as="li" key={step} delay={index * 0.08}>
                  <span className="font-mono text-xs text-brand-strong dark:text-brand-bright">
                    {step}
                  </span>
                  <h3 className="mt-2 text-lg font-semibold text-ink">{title}</h3>
                  <p className="mt-1.5 text-sm text-ink-muted">{body}</p>
                </Reveal>
              ))}
            </ol>
          </section>

          {/* --- Capabilities ------------------------------------------------------ */}
          <section className="border-y border-line bg-surface/50">
            <div className="mx-auto w-full max-w-5xl px-6 py-20">
              <Reveal>
                <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                  What it does once it is running
                </h2>
              </Reveal>
              <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {CAPABILITIES.map(({ icon: Icon, title, body }, index) => (
                  <Reveal
                    as="section"
                    key={title}
                    delay={(index % 3) * 0.06}
                    className="rounded-card border border-line bg-surface p-5"
                  >
                    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
                      <Icon aria-hidden className="h-5 w-5" />
                    </span>
                    <h3 className="mt-3 text-[17px] font-semibold text-ink">{title}</h3>
                    <p className="mt-1 text-sm text-ink-muted">{body}</p>
                  </Reveal>
                ))}
              </div>
            </div>
          </section>

          {/* --- Verticals --------------------------------------------------------- */}
          <section id="verticals" className="mx-auto w-full max-w-5xl scroll-mt-20 px-6 py-20">
            <Reveal>
              <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                It starts with the questions your line of work actually asks
              </h2>
              <p className="mt-4 max-w-2xl text-base text-ink-muted">
                A clinic needs to know what hurts and how soon. A property office needs a
                budget and an area. These are the field lists a new agent starts from —
                and then you change them, because the columns are yours rather than ours.
              </p>
            </Reveal>
            <div className="mt-10 grid gap-4 sm:grid-cols-2">
              {VERTICALS.map(({ icon: Icon, name, fields, suite }, index) => (
                <Reveal
                  as="section"
                  key={name}
                  delay={(index % 2) * 0.06}
                  className="rounded-card border border-line bg-surface p-5"
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
                      <Icon aria-hidden className="h-5 w-5" />
                    </span>
                    <h3 className="text-[17px] font-semibold text-ink">{name}</h3>
                  </div>
                  <ul className="mt-4 flex flex-wrap gap-2">
                    {fields.map((field) => (
                      <li
                        key={field}
                        className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-muted"
                      >
                        {field}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-4 text-xs text-ink-faint">
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
          </section>

          {/* --- Languages --------------------------------------------------------- */}
          <section className="border-y border-line bg-surface/50">
            <div className="mx-auto w-full max-w-5xl px-6 py-20">
              <Reveal>
                <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                  Telugu first, and not as a setting somebody remembered at the end
                </h2>
                <p className="mt-4 max-w-2xl text-base text-ink-muted">
                  Your callers do not switch to English for your convenience, and a
                  receptionist who makes them is one they hang up on. This was built for
                  Andhra Pradesh and Telangana before it was built for anywhere else.
                </p>
              </Reveal>
              <dl className="mt-10 grid gap-8 sm:grid-cols-3">
                {[
                  {
                    term: "Telugu is where an agent starts",
                    detail:
                      "A newly created agent is a Telugu agent until somebody changes it. " +
                      "That is the default in the database, not a suggestion in a guide.",
                  },
                  {
                    term: "Hindi and English are the other two",
                    detail:
                      "Three languages are offered, and only three, because those are the " +
                      "ones we are willing to put a client's callers in front of.",
                  },
                  {
                    term: "The whole agent moves with the language",
                    detail:
                      "The opening line that says it is an AI, the script and the material " +
                      "it answers from are all in the language it speaks.",
                  },
                ].map(({ term, detail }, index) => (
                  <Reveal key={term} delay={index * 0.08}>
                    <dt className="text-[17px] font-semibold text-ink">{term}</dt>
                    <dd className="mt-1.5 text-sm text-ink-muted">{detail}</dd>
                  </Reveal>
                ))}
              </dl>
              <Reveal delay={0.2}>
                <p className="mt-10 max-w-2xl text-sm text-ink-faint">
                  We publish no score for how well it understands any of them, because a
                  number we cannot show you the working for is worth nothing. What we do
                  publish, for your own agent, is the report below.
                </p>
              </Reveal>
            </div>
          </section>

          {/* --- Compliance -------------------------------------------------------- */}
          <section className="mx-auto w-full max-w-5xl px-6 py-20">
            <Reveal>
              <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                Built around the Indian rules, in the code rather than in a policy page
              </h2>
              <p className="mt-4 max-w-2xl text-base text-ink-muted">
                An automated call is regulated here, and the agent speaks on your
                registration. These are not settings with sensible defaults — they are
                limits the product enforces on every dial.
              </p>
            </Reveal>
            <div className="mt-10 grid gap-4 sm:grid-cols-2">
              {COMPLIANCE.map(({ icon: Icon, title, body }, index) => (
                <Reveal
                  as="section"
                  key={title}
                  delay={(index % 2) * 0.06}
                  className="rounded-card border border-line bg-surface p-5"
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
                    <Icon aria-hidden className="h-5 w-5" />
                  </span>
                  <h3 className="mt-3 text-[17px] font-semibold text-ink">{title}</h3>
                  <p className="mt-1 text-sm text-ink-muted">{body}</p>
                </Reveal>
              ))}
            </div>
          </section>

          {/* --- Data ------------------------------------------------------------- */}
          <section className="border-y border-line bg-surface/50">
            <div className="mx-auto w-full max-w-5xl px-6 py-20">
              <Reveal>
                <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                  Your customers&apos; data
                </h2>
              </Reveal>
              <dl className="mt-10 grid gap-8 sm:grid-cols-3">
                {[
                  {
                    /*
                     * NARROWED, because the sentence it replaces was not true (see the
                     * residency note in this file's header). What the repository
                     * actually enforces is a fact about MODEL ENDPOINTS —
                     * SECURITY-COMPLIANCE §4's own words, "every model endpoint this
                     * repository can reach is pinned to an Indian region" — and
                     * `scripts/check_model_residency.py` fails the build on a host, a
                     * `locations/…` segment or a console-editable region that says
                     * otherwise. Nothing here is said about where the database, the
                     * object store or the recordings sit, because that is undecided
                     * (DEPLOYMENT §0) and is the founder's call to make.
                     */
                    term: "The AI runs on Indian endpoints",
                    detail:
                      "Speech, language and the reading of your transcripts are Indian " +
                      "services. The one model endpoint that is not is pinned to " +
                      "Mumbai by a check that fails our build if a line of code ever " +
                      "points somewhere else.",
                  },
                  {
                    term: "One business cannot see another",
                    detail:
                      "Separation is enforced by the database on every query, not by " +
                      "application code remembering to filter.",
                  },
                  {
                    term: "Phone numbers are hidden by default",
                    detail:
                      "Transcripts come back redacted. Seeing the raw text takes the " +
                      "right role and writes an audit entry.",
                  },
                ].map(({ term, detail }, index) => (
                  <Reveal key={term} delay={index * 0.08}>
                    <dt className="text-[17px] font-semibold text-ink">{term}</dt>
                    <dd className="mt-1.5 text-sm text-ink-muted">{detail}</dd>
                  </Reveal>
                ))}
              </dl>
              <Reveal delay={0.2}>
                <p className="mt-10 max-w-2xl text-sm text-ink-faint">
                  If one of your customers asks you to delete what we hold on them, there
                  is a button for it and it produces a certificate saying what was
                  destroyed and when.
                </p>
              </Reveal>
            </div>
          </section>

          {/* --- Quality ----------------------------------------------------------- */}
          <section id="quality" className="mx-auto w-full max-w-5xl scroll-mt-20 px-6 py-20">
            <Reveal>
              <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                We test your agent, and you read the same report we do
              </h2>
              <p className="mt-4 max-w-2xl text-base text-ink-muted">
                An agent that sounds good on the demo call and loses a detail on the
                fortieth one is the ordinary failure of this whole category. So the
                testing is not a promise we make on this page — it is a screen in your
                dashboard, and it is allowed to say bad news.
              </p>
            </Reveal>
            <dl className="mt-10 grid gap-8 sm:grid-cols-3">
              {QUALITY.map(({ term, detail }, index) => (
                <Reveal key={term} delay={index * 0.08}>
                  <dt className="text-[17px] font-semibold text-ink">{term}</dt>
                  <dd className="mt-1.5 text-sm text-ink-muted">{detail}</dd>
                </Reveal>
              ))}
            </dl>
          </section>

          {/* --- Questions --------------------------------------------------------- */}
          <section id="faq" className="scroll-mt-20 border-y border-line bg-surface/50">
            <div className="mx-auto w-full max-w-5xl px-6 py-20">
              <Reveal>
                <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
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

          {/* --- Doors ------------------------------------------------------------- */}
          <section className="mx-auto w-full max-w-5xl px-6 py-20">
            <div className="grid gap-4 sm:grid-cols-2">
              <Reveal
                as="section"
                className="rounded-card border border-line bg-surface p-6"
              >
                <h2 className="text-[17px] font-semibold text-ink">Already a client</h2>
                <p className="mt-1 text-sm text-ink-muted">
                  Your workspace is at{" "}
                  <code className="rounded bg-black/5 px-1 font-mono text-[13px] text-ink dark:bg-white/10">
                    /c/your-slug
                  </code>{" "}
                  — the URL your account manager gave you.
                </p>
                <Link
                  href="/sign-in"
                  className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                >
                  Sign in
                  <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                </Link>
                {/* Local development only: unset in every deployed build, so this renders
                    nothing rather than offering a stranger a link into somebody's tenant. */}
                {devSlug && (
                  <Link
                    href={`/c/${devSlug}`}
                    className="mt-3 inline-flex items-center gap-2 rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-strong"
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
                className="rounded-card border border-line bg-surface p-6"
              >
                <h2 className="text-[17px] font-semibold text-ink">
                  {SIGNUP_OPEN ? "New here" : "Not a client yet"}
                </h2>
                <p className="mt-1 text-sm text-ink-muted">
                  {SIGNUP_OPEN
                    ? "Create your workspace and set up your first agent. Nothing calls anyone until you say so."
                    : "Calevate does not open accounts online. Every workspace is set up by hand with you."}
                </p>
                <Link
                  href="/signup"
                  className="mt-3 inline-flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-sm font-semibold text-ink hover:bg-black/5 dark:hover:bg-white/5"
                >
                  {SIGNUP_OPEN ? "Create a workspace" : "How to get one"}
                  <ArrowRight aria-hidden className="h-4 w-4" />
                </Link>
                {/* Only when there is an address to give. An invented one bounces. */}
                {!SIGNUP_OPEN && SIGNUP_CONTACT_EMAIL && (
                  <p className="mt-3 text-sm text-ink-muted">
                    Or write to{" "}
                    <a
                      className="font-medium text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                      href={`mailto:${SIGNUP_CONTACT_EMAIL}`}
                    >
                      {SIGNUP_CONTACT_EMAIL}
                    </a>
                    .
                  </p>
                )}
              </Reveal>
            </div>
          </section>

          {/* --- Closing invitation ------------------------------------------------ */}
          {/*
           * A last section that ASKS rather than claims. The temptation at the bottom of
           * a landing page is one more superlative; there is nothing left to say that is
           * both true and new, so this repeats the offer in the buyer's own terms and
           * hands over the same two doors as above. The signup flag is read here for the
           * same reason the doors read it: a button whose label the deployment cannot
           * honour is the exact defect this page is written against.
           */}
          <section className="border-y border-line bg-surface/50">
            <div className="mx-auto w-full max-w-5xl px-6 py-20">
              <Reveal>
                <h2 className="max-w-3xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                  The calls you missed today are not on any report
                </h2>
                <p className="mt-4 max-w-2xl text-base text-ink-muted">
                  Tell us what your callers ring about and what you need written down
                  about each one. We build the agent with you, in your language, on your
                  own price list and timings — and nothing dials anybody until you say so.
                </p>
                <div className="mt-8 flex flex-wrap items-center gap-3">
                  <Link
                    href="/signup"
                    className="inline-flex items-center gap-2 rounded-md bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-strong"
                  >
                    {SIGNUP_OPEN ? "Create a workspace" : "Start a conversation"}
                    <ArrowRight aria-hidden className="h-4 w-4" />
                  </Link>
                  {/* Only when there is an address to give — an invented one bounces. */}
                  {SIGNUP_CONTACT_EMAIL && (
                    <a
                      href={`mailto:${SIGNUP_CONTACT_EMAIL}`}
                      className="inline-flex items-center gap-2 rounded-md border border-line px-5 py-2.5 text-sm font-semibold text-ink hover:bg-black/5 dark:hover:bg-white/5"
                    >
                      Write to us
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
        <footer className="border-t border-line px-6 py-8">
          <div className="mx-auto flex max-w-5xl flex-col gap-4">
            <nav aria-label="Legal">
              <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
                {LEGAL_DOCUMENTS.map((doc) => (
                  <li key={doc.slug}>
                    <Link
                      href={`/legal/${doc.slug}`}
                      className="text-ink-faint underline-offset-4 hover:text-ink hover:underline"
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
