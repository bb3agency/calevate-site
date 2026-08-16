import Link from "next/link";
import {
  ArrowRight,
  BadgeCheck,
  Clock,
  Database,
  FileAudio,
  Languages,
  Megaphone,
  PhoneIncoming,
  ShieldCheck,
  Table2,
  Webhook,
} from "lucide-react";

import { CallDemo } from "@/components/marketing/callDemo";
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
 *
 * ## What the redesign added, and why each section is defensible
 *
 * Every capability below maps to a shipped surface, and the compliance section is the one
 * that is genuinely differentiating rather than decorative — each of its four lines is an
 * invariant enforced on the dispatch path (hard rule 5), not a policy page. The recording
 * and key-moments card is D-153/D-156, both shipped. The retention line is the TRAI
 * 90-day floor, enforced by a database CHECK rather than by intent.
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
                    term: "It stays in India",
                    detail:
                      "Calls, transcripts and recordings are processed and stored in " +
                      "Indian regions.",
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
        </main>

        <footer className="border-t border-line px-6 py-8">
          <p className="mx-auto max-w-5xl text-xs text-ink-faint">
            Calevate — AI phone agents for Indian businesses.
          </p>
        </footer>
      </div>
    </SmoothScroll>
  );
}
