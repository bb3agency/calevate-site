"use client";

import { type ReactNode } from "react";
import {
  BadgeCheck,
  CalendarClock,
  CircleHelp,
  MessageSquareOff,
} from "lucide-react";

import { MonoValue, NOTICE_TONES, formatIST, type NoticeTone } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import {
  CONSENT_SOURCES,
  CONSENT_VALIDITY_DAYS,
  type MessagingConsent,
} from "@/lib/api/messagingConsent";

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
        <p className="font-medium">You may send this person WhatsApp messages.</p>
        <p className="mt-1">
          {describeCapture(state)} This stays current until {formatIST(state.expires_at)}.
        </p>
      </Box>
    );
  }

  if (state.status === "granted") {
    return (
      <Box tone="warn" icon={<CalendarClock className="h-4 w-4" />}>
        <p className="font-medium">Not messageable — their opt-in has expired.</p>
        <p className="mt-1">
          {describeCapture(state)} An opt-in stays current for {CONSENT_VALIDITY_DAYS}{" "}
          days, and this one lapsed on {formatIST(state.expires_at)}. Ask again before
          messaging them.
        </p>
      </Box>
    );
  }

  if (state.status === "declined" || state.status === "withdrawn") {
    return (
      <Box tone="stop" icon={<MessageSquareOff className="h-4 w-4" />}>
        <p className="font-medium">
          {state.status === "withdrawn"
            ? "Not messageable — they asked us to stop."
            : "Not messageable — they were asked and said no."}
        </p>
        <p className="mt-1">{describeCapture(state)}</p>
      </Box>
    );
  }

  // `status: "none"` — nobody has ever asked this person. A 200 and the normal state of
  // the world, not a 404 and not an error (MessagingConsentOut says so in its docstring),
  // so it is neutral in tone and still a no.
  if (state.status === "none") {
    return (
      <Box tone="neutral" icon={<CircleHelp className="h-4 w-4" />}>
        <p className="font-medium">Not messageable — nobody has asked them yet.</p>
        <p className="mt-1">
          Campaign follow-ups will skip this number until someone records what they said.
          Recording it needs the customer&apos;s own answer, not an assumption.
        </p>
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
      <p className="font-medium">Not messageable — this record is one we cannot read.</p>
      <p className="mt-1">
        The system will not message this number. Quote{" "}
        <MonoValue className="text-xs">{state.status}</MonoValue> to us and we will
        explain what it means.
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
  if (source && when) return `Recorded ${when} — ${source.label.toLowerCase()}.`;
  if (when) return `Recorded ${when}.`;
  return "";
}

/**
 * The verdict box. Palette from `NOTICE_TONES` (ui.tsx) — the four states this product
 * already has words for — rather than a fifth private copy of the same four colours.
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
    <div className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES[tone]}`}>
      <span className="mt-0.5 shrink-0" aria-hidden>
        {icon}
      </span>
      <div>{children}</div>
    </div>
  );
}
