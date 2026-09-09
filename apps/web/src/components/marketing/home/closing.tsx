import Link from "next/link";

import { ArrowRight, ArrowUpRight } from "lucide-react";

import { Reveal } from "@/components/marketing/motion";
import {
  CARD,
  CTA_LABEL,
  CTA_PRIMARY,
  CTA_SECONDARY,
  SECTION,
  SHELL,
} from "@/components/marketing/pageShell";
import { CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";
import { SIGNUP_CONTACT_EMAIL, SIGNUP_OPEN } from "@/lib/api/signup";

/**
 * The closing offer and the two doors. MOVED, NOT REWRITTEN.
 *
 * Both reassurance lines were checked against the code before they were first written and
 * are carried over verbatim: approval before anything is answerable
 * (`apps/api/kb/service.py:437::approve_source` review states,
 * `apps/api/agents/service.py:1193::publish_agent`), and the campaign launch gate
 * (`apps/api/campaigns/service.py:1199` — a campaign is a draft until a person launches it).
 *
 * The self-serve door (D-34) is told the truth about on the page a stranger reads FIRST:
 * `self_serve_signup_enabled` defaults OFF (R-11's kill switch), so on most deployments the
 * answer is "we open accounts with you" — and rendering "Sign up free" over that is a claim
 * the product cannot keep, dressed as a button. "How to get one" is the one deliberate
 * exception to the one-door-one-label rule, because it answers the question its own card
 * heading asks; `publicLanding.test.tsx` pins it separately.
 *
 * This is NOT a `Chapter`: it is the page's sign-off rather than another subject, it has no
 * eyebrow and no band heading, and giving it a ranked `<h2>` would have put a fourth
 * `anchor` on a page whose whole point is that three of them carry the argument.
 */
export function Closing({ devSlug }: { devSlug?: string }) {
  return (
    <section className="border-t border-line">
      <div className={`${SHELL} ${SECTION}`}>
        <Reveal
          as="section"
          className="relative overflow-hidden rounded-2xl border border-line bg-surface p-8 sm:p-12 lg:p-16"
        >
          <div
            aria-hidden
            className="mk-blob mk-blob--b pointer-events-none absolute -top-16 right-0 h-56 w-56"
          />
          <h2 className="max-w-4xl text-[2rem] leading-[1.1] font-semibold tracking-tight text-balance text-ink sm:text-5xl">
            Your next customer could already be trying to reach you
          </h2>
          <p className="mt-6 max-w-2xl text-lg text-pretty text-ink-muted sm:text-xl">
            Tell us what your callers ring about and what you need written down about each
            one. We build the agent with you, in your language, on your own price list and
            timings. You approve the agent before it goes live, and nothing calls a customer
            until you launch it.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-3">
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

        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          <Reveal as="section" className={`${CARD} sm:p-8`}>
            <h2 className="text-xl font-semibold text-ink sm:text-2xl">Already a client</h2>
            <p className="mt-3 text-base text-pretty text-ink-muted sm:text-lg">
              Your workspace is at{" "}
              <code className="rounded bg-black/5 px-1 font-mono text-[13px] text-ink dark:bg-white/10">
                /c/your-slug
              </code>{" "}
              — the URL your account manager gave you.
            </p>
            <Link
              href={CLIENT_SIGN_IN_PATH}
              className="mt-5 inline-flex items-center gap-1.5 text-base font-semibold text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-surface dark:text-brand-bright"
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

          <Reveal as="section" delay={0.06} className={`${CARD} sm:p-8`}>
            <h2 className="text-xl font-semibold text-ink sm:text-2xl">
              {SIGNUP_OPEN ? "New here" : "Not a client yet"}
            </h2>
            <p className="mt-3 text-base text-pretty text-ink-muted sm:text-lg">
              {SIGNUP_OPEN
                ? "Set up your first agent. Nothing calls anyone until you say so."
                : "Calevate does not open accounts online. Every workspace is set up by hand with you."}
            </p>
            <Link
              href="/signup"
              className="mt-5 inline-flex items-center gap-2 rounded-full border border-line px-5 py-2.5 text-base font-semibold text-ink transition-colors hover:border-brand/50 hover:bg-brand-soft/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
            >
              How to get one
              <ArrowRight aria-hidden className="h-4 w-4" />
            </Link>
            {/* Only when there is an address to give. An invented one bounces. */}
            {!SIGNUP_OPEN && SIGNUP_CONTACT_EMAIL && (
              <p className="mt-4 text-base text-ink-muted">
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
  );
}
