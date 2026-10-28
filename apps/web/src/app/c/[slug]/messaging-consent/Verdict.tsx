"use client";

import { type ReactNode } from "react";
import {
  BadgeCheck,
  CalendarClock,
  CircleHelp,
  MessageSquareOff,
} from "lucide-react";

import { MonoValue, NOTICE_BAR, NOTICE_BASE, formatIST, type NoticeTone } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import { CONSENT_SOURCES, type MessagingConsent } from "@/lib/api/messagingConsent";

import { CONSENT_COPY as COPY, lapsedOn } from "./copy";

/**
 * The verdict, rendered from `messageable` and never recomputed from `status`.
 *
 * The distinction that matters: a `granted` row that has gone stale is NOT a green
 * tick. It gets the amber treatment and the date it lapsed, because the campaign
 * worker will refuse it and the client needs to know why before they wonder where
 * their follow-ups went.
 */
export function Verdict({ state }: { state: MessagingConsent }) {
  if (state.messageable) {
    return (
      <Box tone="ok" icon={<BadgeCheck className="h-4 w-4" />}>
        <p className="font-medium">{COPY.yes}</p>
        <Lines lines={[describeCapture(state), `${COPY.until} ${formatIST(state.expires_at)}.`]} />
      </Box>
    );
  }

  if (state.status === "granted") {
    return (
      <Box tone="warn" icon={<CalendarClock className="h-4 w-4" />}>
        <p className="font-medium">{COPY.expired}</p>
        <Lines lines={[describeCapture(state), lapsedOn(formatIST(state.expires_at)), COPY.askAgain]} />
      </Box>
    );
  }

  if (state.status === "declined" || state.status === "withdrawn") {
    return (
      <Box tone="stop" icon={<MessageSquareOff className="h-4 w-4" />}>
        <p className="font-medium">
          {state.status === "withdrawn" ? COPY.stopped : COPY.declined}
        </p>
        <Lines lines={[describeCapture(state)]} />
      </Box>
    );
  }

  // `status: "none"` — nobody has ever asked this person. A 200 and the normal state of
  // the world, not a 404 and not an error (MessagingConsentOut says so in its docstring),
  // so it is neutral in tone and still a no.
  if (state.status === "none") {
    return (
      <Box tone="neutral" icon={<CircleHelp className="h-4 w-4" />}>
        <p className="font-medium">{COPY.none}</p>
        <Lines lines={[COPY.noneSkip, COPY.noneHow]} />
      </Box>
    );
  }

  /* Any status this build predates. `MessagingConsentOut.status` is a bare `string`, so
     the API can grow a member without this file changing — and "nobody has asked them
     yet" would then be a confident, wrong sentence about a person whose record we simply
     cannot read. The verdict is unaffected (it comes from `messageable`, which is false
     here); what changes is that the screen stops explaining a record it does not
     understand, and shows the value so support can. */
  return (
    <Box tone="neutral" icon={<CircleHelp className="h-4 w-4" />}>
      <p className="font-medium">{COPY.unknown}</p>
      <p className="mt-1">
        {COPY.unknownQuote} <MonoValue className="text-xs">{state.status}</MonoValue>{" "}
        {COPY.unknownTail}
      </p>
    </Box>
  );
}

function describeCapture(state: MessagingConsent): string {
  // `source` is `string | null` on the wire — a `consent_ledger` column, never narrowed
  // by the schema — so this is a lookup that must tolerate a member this build predates.
  // It used to be a `value in CONSENT_SOURCES` guard, which walks the prototype chain:
  // a source of "constructor" passed the guard, the table handed back `Object`, and
  // `.label.toLowerCase()` threw during render. The whole verdict box — the one thing on
  // this screen that answers "may we message them?" — went blank. `lookup` (lib/lookup.ts)
  // is the one way this codebase reads a wire string out of a copy table.
  // Fail direction: an unnameable source is OMITTED, not printed. The sentence is about
  // where the consent came from, and rendering a raw enum name to a client says nothing;
  // the verdict itself comes from `messageable` and is unaffected either way.
  const source = lookup(CONSENT_SOURCES, state.source);
  const when = state.captured_at ? formatIST(state.captured_at) : null;
  if (source && when) return `Recorded ${when}, ${source.label.toLowerCase()}.`;
  if (when) return `Recorded ${when}.`;
  return "";
}

/** The detail under a verdict, one short line each, blanks dropped. */
function Lines({ lines }: { lines: string[] }) {
  const shown = lines.filter((line) => line.trim() !== "");
  if (shown.length === 0) return null;
  return (
    <div className="mt-1 space-y-0.5 text-ink-muted">
      {shown.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  );
}

/**
 * The verdict, as a quiet notice: the tone is the left rule (`NOTICE_BAR`), the text is ink.
 */
function Box({
  tone,
  icon,
  children,
}: {
  tone: NoticeTone;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`flex items-start gap-2 ${NOTICE_BASE} ${NOTICE_BAR[tone]}`}>
      <span className="mt-0.5 shrink-0 text-ink-faint" aria-hidden>
        {icon}
      </span>
      <div>{children}</div>
    </div>
  );
}
