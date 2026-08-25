"use client";

/**
 * The two whole-screen global states this app had none of: a crash, and an address that
 * does not exist.
 *
 * ## Why a component rather than four copies
 *
 * There are five call sites — `app/error.tsx`, `app/global-error.tsx`, `app/not-found.tsx`
 * and the two realm boundaries — and they differ ONLY in which exits they offer and, for
 * `global-error`, in the fact that it has to carry its own `<html>`. Everything else (the
 * copy discipline, the support reference, the retry control, the heading structure) is one
 * job, and this repo's own history says what happens when a shell is copied instead of
 * extracted: `navDrawer.tsx:59-65` records the second modal shipping without the focus trap
 * the first one had.
 *
 * ## It follows the house error doctrine rather than inventing one
 *
 * BUILD-LOG §52 — *loading is a skeleton, failure is a refusal, and neither is a number, a
 * state, or an empty state* — is enforced across 71 screens by `tests/surfaceStatesGuard`.
 * The unanticipated failure path had nothing at all, which is the one place a plausible
 * zero was never at risk and a plausible SILENCE was. So: a crash renders a refusal in the
 * same `NoticeBox tone="stop"` vocabulary the anticipated failures use, and it says which
 * screen it is talking about.
 *
 * An `ApiProblem` thrown during render is unwrapped rather than flattened, for
 * `ProblemNotice`'s reason: the API distinguishes a compliance refusal from a transient
 * failure with `retryable` + `remediation` + `trace_id`, and "something went wrong" would
 * turn a compliance gate into a bug report. When one carries a `trace_id`, or Next carries
 * an `error.digest`, it is shown as a quotable SUPPORT REFERENCE — that is the string an
 * operator greps the server log for, and it is the only reason a user has to read anything
 * technical on this screen.
 *
 * ## What is NEVER shown
 *
 * `error.message` from anything that is not an `ApiProblem`, and `error.stack`, ever.
 * CLAUDE.md: user-safe messages, no internals. In production Next already strips a server
 * error's message to a digest, but a CLIENT-side throw keeps its real message —
 * `undefined is not a function`, a module path, sometimes a URL — and that is exactly the
 * text a user cannot act on and an attacker can. It goes to `console.error` instead, which
 * is where an operator's browser-side collector picks it up, and the user gets a sentence
 * about what to do next.
 */

import type { ReactNode } from "react";

import Link from "next/link";
import { PhoneOff, TriangleAlert } from "lucide-react";

import { DisconnectedCall } from "@/components/illustration/disconnectedCall";
import { MonoValue, NoticeBox, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";

/** One way out of this screen. The first is rendered as the primary action. */
export interface Exit {
  href: string;
  label: string;
}

/**
 * What a user is told about a crash, derived from what the failure actually is.
 *
 * Exported for the test, which is the point: the rule "never render a raw error message"
 * is only a rule if something asserts it, and asserting it through a rendered tree makes
 * the assertion about the tree. Here it is a pure function over the thrown value.
 */
export function failureCopy(error: unknown): {
  detail: string;
  remediation: string | null;
  reference: string | null;
} {
  const digest =
    typeof error === "object" && error !== null && "digest" in error
      ? String((error as { digest?: unknown }).digest ?? "")
      : "";

  if (error instanceof ApiProblem) {
    return {
      // Server-authored, user-facing text: this is the RFC-9457 `detail` the API wrote for
      // a person to read, and every screen in the app already renders it.
      detail: error.message,
      remediation: error.remediation ?? null,
      reference: error.traceId ?? (digest || null),
    };
  }

  return {
    detail:
      "This screen stopped before it could finish. Nothing you were looking at has been " +
      "changed or lost.",
    remediation:
      "Try again. If it keeps happening, move on to another screen and tell us — quote " +
      "the reference below if there is one.",
    reference: digest || null,
  };
}

/** The frame both states sit in: centred, readable, and correct inside a shell or without one. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full w-full flex-1 flex-col items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg text-center">{children}</div>
    </div>
  );
}

/** The exits, as buttons. First is primary; the rest are secondary and wrap on a phone. */
function Exits({ exits, before }: { exits: Exit[]; before?: ReactNode }) {
  return (
    <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
      {before}
      {exits.map((exit, i) => (
        <Link key={exit.href} href={exit.href} className={i === 0 && !before ? PRIMARY_BUTTON : SECONDARY_BUTTON}>
          {exit.label}
        </Link>
      ))}
    </div>
  );
}

/**
 * A crash, rendered as a refusal.
 *
 * `reset` is Next's error-boundary reset (it re-renders the boundary's subtree). It is
 * OPTIONAL because `global-error` and a static render both have call sites without one, and
 * a "Try again" button that cannot try again is worse than no button.
 */
export function FailureScreen({
  heading,
  error,
  reset,
  exits,
}: {
  heading: string;
  error: unknown;
  reset?: () => void;
  exits: Exit[];
}) {
  const { detail, remediation, reference } = failureCopy(error);
  return (
    <Frame>
      <NoticeBox
        tone="stop"
        className="text-left"
        icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
        title={<h1 className="text-base font-semibold">{heading}</h1>}
      >
        <p className="mt-1">{detail}</p>
        {remediation && <p className="mt-2">{remediation}</p>}
        {reference && (
          <p className="mt-3 text-xs">
            Support reference: <MonoValue>{reference}</MonoValue>
          </p>
        )}
      </NoticeBox>
      <Exits
        exits={exits}
        before={
          reset && (
            <button type="button" onClick={reset} className={PRIMARY_BUTTON}>
              Try again
            </button>
          )
        }
      />
    </Frame>
  );
}

/**
 * An address that does not answer.
 *
 * The copy is deliberately in plain language and deliberately NOT "Error 404: NOT_FOUND":
 * the reader is as likely to be a procurement reviewer following a stale legal link, or an
 * owner who typed a slug wrong, as an engineer. It says what happened, that nothing is
 * broken, and where to go — and the illustration says the same thing a second way for a
 * reader who is scanning rather than reading. The figure is `aria-hidden`; delete it and
 * the page still says everything it needs to.
 */
export function NotFoundScreen({
  heading = "We could not connect you to that page.",
  detail,
  exits,
}: {
  heading?: string;
  detail: string;
  exits: Exit[];
}) {
  return (
    <Frame>
      <DisconnectedCall className="mx-auto h-40 w-auto max-w-[240px]" />
      <p className="mt-2 flex items-center justify-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
        <PhoneOff aria-hidden className="h-3.5 w-3.5" />
        Page not found
      </p>
      <h1 className="mt-2 text-2xl font-bold tracking-tight text-ink">{heading}</h1>
      <p className="mt-3 text-sm text-ink-muted">{detail}</p>
      <Exits exits={exits} />
    </Frame>
  );
}
