"use client";

import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { type PipConsent, useTurnPipOn } from "@/lib/copilot/conversation";

/** The full pages the summary stands for. The panel names no provider (D-679); these do. */
const LEGAL_LINKS: readonly { href: string; label: string }[] = [
  { href: "/legal/privacy", label: "Privacy Policy" },
  { href: "/legal/dpa", label: "Data Processing Addendum" },
  { href: "/legal/subprocessors", label: "Sub-processors" },
  { href: "/legal/terms", label: "Terms of Service" },
];

/**
 * What the panel shows while Pip is off for the account (D-788).
 *
 * The OWNER reads the server's own disclosure and turns Pip on with one checkbox and one
 * button; everyone else learns who can. The text comes from the server with its hash, and
 * the hash goes back with the tick, so the words read and the words recorded are one.
 */
export function PipConsentGate({ session, consent }: { session: Session; consent: PipConsent }) {
  if (!consent.can_accept) return <PipLocked />;
  return <OwnerConsent session={session} consent={consent} />;
}

function PipLocked() {
  return (
    <div className="space-y-2 px-4 py-4" data-testid="pip-locked">
      <h3 className="text-body font-semibold text-ink">{ASSISTANT_NAME} is off for this account</h3>
      <p className="text-body text-ink-muted">
        The account owner needs to turn {ASSISTANT_NAME} on first. They can do it from this
        panel: when they open {ASSISTANT_NAME}, it asks them.
      </p>
    </div>
  );
}

function OwnerConsent({ session, consent }: { session: Session; consent: PipConsent }) {
  const [agreed, setAgreed] = useState(false);
  const turnOn = useTurnPipOn(session);
  const turnOnFeedback = useActionFeedback(turnOn, { errorDisplay: "inline" });
  const checkboxId = useId();
  const errorId = useId();
  const changed = consent.status === "outdated";

  return (
    <form
      className="space-y-4 px-4 py-4"
      data-testid="pip-consent"
      noValidate
      aria-describedby={turnOn.error != null ? errorId : undefined}
      onSubmit={(event) => {
        event.preventDefault();
        if (agreed && !turnOn.isPending) turnOn.mutate(consent);
      }}
    >
      <div className="space-y-2">
        <h3 className="text-body font-semibold text-ink">
          {changed ? `${ASSISTANT_NAME} needs turning on again` : `Turn on ${ASSISTANT_NAME} for your account`}
        </h3>
        {changed && (
          <p className="text-body text-ink">
            What {ASSISTANT_NAME} sends has changed since you turned it on. Read it and turn{" "}
            {ASSISTANT_NAME} on again for your team.
          </p>
        )}
        {/* The server separates its paragraphs with a blank line. */}
        <p className="whitespace-pre-line text-body text-ink">{consent.text}</p>
        <p className="text-meta text-ink-muted">
          The full details:{" "}
          {LEGAL_LINKS.map((link, index) => (
            <span key={link.href}>
              {index > 0 && " · "}
              <a
                href={link.href}
                target="_blank"
                rel="noopener"
                className="font-medium text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                {link.label}
              </a>
            </span>
          ))}
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id={checkboxId}
          type="checkbox"
          checked={agreed}
          onChange={(event) => setAgreed(event.target.checked)}
          className="mt-1 h-4 w-4 shrink-0 accent-brand touch:h-5 touch:w-5"
        />
        <label htmlFor={checkboxId} className="text-body text-ink">
          I&apos;ve read this, and I&apos;m turning {ASSISTANT_NAME} on for everyone on this account.
        </label>
      </div>

      <ActionButton type="submit" status={turnOnFeedback.status} disabled={!agreed} successLabel="Turned on">
        Turn on {ASSISTANT_NAME}
      </ActionButton>

      {turnOn.error != null && (
        <div id={errorId}>
          <ProblemNotice error={turnOn.error} />
        </div>
      )}
    </form>
  );
}
