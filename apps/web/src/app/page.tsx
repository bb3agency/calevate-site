import Link from "next/link";
import {
  ArrowRight,
  Megaphone,
  PhoneIncoming,
  ShieldCheck,
  Table2,
} from "lucide-react";

import { SIGNUP_CONTACT_EMAIL, SIGNUP_OPEN } from "@/lib/api/signup";

/**
 * Root of `app.calevate.tech` — one of exactly two screens a stranger can reach.
 *
 * ## Every line here is a promise, so every line is one the product already keeps
 *
 * This page used to be four sentences and a `/c/your-slug` hint, which was honest but
 * said nothing about what the product does. It now says what it does — and the rule
 * applied to each sentence was: name a behaviour that is enforced in code today, or
 * leave it out. What was deliberately NOT written, and why, because the absences are
 * the load-bearing part:
 *
 * - **No prices.** D-11's managed pricing is a range negotiated per client and D-34's
 *   self-serve tier has no published number; there is no plan table to render. A price
 *   on this page is a quote, and a quote nobody can honour is worse than no page.
 * - **No customer counts, logos or testimonials.** There is no client #1 in production
 *   yet (ROADMAP M2). "Trusted by N businesses" would be a fabrication, and it is the
 *   single most-copied line on SaaS landing pages.
 * - **No uptime, latency or accuracy figures.** `calls.latency` was dropped in migration
 *   `f1a7c39d5be2` and D-49 removed the trace config, so the console itself refuses to
 *   print a latency tile (SURFACES §2c). A marketing page may not claim what the
 *   dashboard declines to state.
 * - **No turnaround promise.** The closed-signup panel used to end "usually the same
 *   day"; nothing in the product or in ops measures that, so it is gone from both
 *   screens rather than restyled.
 *
 * The four capability cards each map to a shipped gate or surface: the receptionist and
 * its extraction schema are created by signup itself (SURFACES §2c), campaigns and their
 * retry behaviour are `/c/<slug>/campaigns`, and the compliance sentence names three
 * things enforced on every dispatch path (hard rule 5: platform-fixed calling hours,
 * DNC scrub, non-null AI disclosure).
 *
 * ## Framing and scrolling
 *
 * There is no app shell around this route — `/c` and `/admin` each own a `fixed inset-0`
 * layout and this page has neither. `globals.css` sets `html, body { overflow: hidden }`
 * for those shells, so a marketing page that simply grows is SILENTLY CLIPPED on a short
 * viewport: the door and the contact address are the part that disappears. Hence the
 * `flex-1 min-h-0 overflow-y-auto` container — this page scrolls itself.
 */

/** A capability, stated as the behaviour a caller would observe. */
const CAPABILITIES: {
  icon: typeof PhoneIncoming;
  title: string;
  body: string;
}[] = [
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
    icon: ShieldCheck,
    title: "Built around the Indian rules",
    body:
      "Calls go out only between 9am and 9pm, numbers on the do-not-call list are never " +
      "dialled, and every call opens by saying it is an AI.",
  },
];

export default function Home() {
  const devSlug = process.env.NEXT_PUBLIC_DEV_ORG_SLUG;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-app">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-6 py-4">
          <span className="text-base font-semibold tracking-tight text-ink">Calevate</span>
          {/* The door, sized as a secondary control on purpose — see the panel below for
              why it is not the headline. */}
          <Link
            href="/signup"
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
          >
            {SIGNUP_OPEN ? "Create a workspace" : "Get a workspace"}
            <ArrowRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-12">
        <h1 className="max-w-2xl text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          AI phone agents for Indian businesses
        </h1>
        <p className="mt-3 max-w-2xl text-base text-ink-muted">
          Calevate answers the calls you miss and follows up on the enquiries you have
          already got — in the language your customers actually speak.
        </p>

        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {CAPABILITIES.map(({ icon: Icon, title, body }) => (
            <section
              key={title}
              className="rounded-card border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
                <Icon aria-hidden className="h-5 w-5" />
              </span>
              <h2 className="mt-3 text-[17px] font-semibold text-ink">{title}</h2>
              <p className="mt-1 text-sm text-ink-muted">{body}</p>
            </section>
          ))}
        </div>

        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          <section className="rounded-card border border-line bg-surface p-5">
            <h2 className="text-[17px] font-semibold text-ink">Already a client</h2>
            <p className="mt-1 text-sm text-ink-muted">
              Your workspace is at{" "}
              <code className="rounded bg-black/5 px-1 font-mono text-[13px] text-ink dark:bg-white/10">
                /c/your-slug
              </code>{" "}
              — the URL your account manager gave you.
            </p>
            {/* The door back in. It exists as of the Clerk integration — before that
                this card named a URL and stopped, because there was no sign-in route to
                point at. `/c/<slug>` redirects here by itself when a session has
                lapsed; this is for the person who reached for the front page instead. */}
            <Link
              href="/sign-in"
              className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong underline underline-offset-2 dark:text-brand-bright"
            >
              Sign in
              <ArrowRight aria-hidden className="h-3.5 w-3.5" />
            </Link>
            {/* Local development only: `NEXT_PUBLIC_DEV_ORG_SLUG` is unset in every
                deployed build, so this renders nothing rather than offering a stranger a
                link into somebody's tenant. */}
            {devSlug && (
              <Link
                href={`/c/${devSlug}`}
                className="mt-3 inline-flex items-center gap-2 rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-strong"
              >
                Open {devSlug}
                <ArrowRight aria-hidden className="h-4 w-4" />
              </Link>
            )}
          </section>

          {/*
           * The self-serve door (D-34), told the truth about on the page a stranger reads
           * FIRST rather than after five fields.
           *
           * `self_serve_signup_enabled` defaults OFF (R-11's kill switch), so on most
           * deployments the answer is "we open accounts with you". Rendering "Sign up
           * free" over that is the exact shape this migration bans: a claim the product
           * cannot keep, dressed as a button. The link stays in both states because
           * `/signup` is a real destination either way — open, it is the form; closed, it
           * is the panel that explains and hands over the contact address.
           */}
          <section className="rounded-card border border-line bg-surface p-5">
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
            {/* Only when there is an address to give. An invented one bounces, which is
                a worse answer than the sentence above on its own. */}
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
          </section>
        </div>
      </main>

      <footer className="border-t border-line px-6 py-6">
        <p className="mx-auto max-w-3xl text-xs text-ink-faint">
          Calevate — AI phone agents for Indian businesses.
        </p>
      </footer>
    </div>
  );
}
