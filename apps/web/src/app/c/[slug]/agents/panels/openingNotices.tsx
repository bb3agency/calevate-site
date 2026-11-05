"use client";

/**
 * THE OPENING NOTICES — two switches, and the answer neither of them reaches.
 *
 * What stays on screen without a click (UX-DOCTRINE §3, §8 rule 7): the guarantee that the
 * agent answers honestly when asked, each switch with one line saying what its position
 * does, and how a call starts. The reasoning (the DPDP duty, when a change takes effect)
 * is in one closed disclosure under the block (D-873).
 */

import { PenLine, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import {
  Disclosure,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  ToggleSwitch,
} from "@/components/ui";
import { useSetDisclosure, type Agent, type DisclosureIn } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { Term } from "@/lib/glossary";

import {
  IntroducedOpeningFix,
  NOTICE_NEEDS_ROOM,
  OPENING_INTRODUCES,
  OpeningLineFix,
  problemCode,
} from "./openingLineFix";

/**
 * The server's truthful-answer promise split at its first sentence: the guarantee, shown
 * above the switches, and the rest (the exact answers), shown in full in the disclosure.
 * The words are the server's either way (`compliance/disclosure.truthful_answer_promise`);
 * only where they are drawn changes. A promise with one sentence is not split.
 */
export function splitPromise(rule: string): { lead: string; rest: string } {
  const match = /^(.+?[.!?])\s+(\S[\s\S]*)$/.exec(rule.trim());
  return match ? { lead: match[1], rest: match[2] } : { lead: rule.trim(), rest: "" };
}

/**
 * The two opening notices, as switches.
 *
 * ## What the client is actually deciding (D-163)
 *
 * "This is an AI" (TRAI/UCC) and "this call is recorded" (DPDP notice-and-consent) are
 * separate obligations under separate regimes, so they are separate switches; the client is
 * the Principal Entity and the exposure is theirs. `org:manage` is the owner's permission.
 * An operator in "view as client" can flip them too (D-587, over D-22's read-only rule):
 * every flip is audited, and an operator's names them and the view-as session.
 *
 * ## No sentence is quoted
 *
 * With a switch on, the agent mentions the notice in its own words when it opens the call
 * (founder, 5 Nov 2026), so there is no fixed sentence to show: the screen says what the
 * switch does rather than quoting `ai_disclosure_line` / `recording_notice_line`, which
 * stay on the API untouched. The caller-memory sentence is no longer spoken and has no row.
 *
 * ## What "off" does not mean, said on screen
 *
 * - **"Off" does not mean the agent lies.** `truthful_answer_rule` comes from the server and
 *   is drawn in the server's words, its first sentence above the switches; the AI switch's
 *   off line repeats the point for that switch.
 * - **"Off" does not stop the recording, or discharge the duty to tell callers.** Nothing in
 *   the product stops recording, so the recording switch's off line is the panel's one
 *   warning.
 *
 * `first_words` is the server's own text for what the agent says first and is shown as
 * sent, never assembled here (D-861). No switch reaches the opening line (D-708).
 */
export function OpeningNotices({ agent }: { agent: Agent }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const setDisclosure = useSetDisclosure(session, agent.id);
  // The switch's position and the "Saved" line beside the heading are the success; a
  // refusal is the notice (or the opening-line fix) drawn here, so nothing is toasted.
  const feedback = useActionFeedback(setDisclosure, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "switch these notices");
  const locked = setDisclosure.isPending || !write.allowed;
  const opening = agent.script_opening_line.trim();
  const calling = agent.first_words_when_calling ?? null;
  const promise = splitPromise(agent.truthful_answer_rule);
  const name = agent.name.trim() || "The agent";
  // The switch last turned on, so a refusal for want of room can offer the room that
  // switch needs and turn the same one on again once the line is shorter.
  const [lastOn, setLastOn] = useState<DisclosureIn | null>(null);
  const flip = (payload: DisclosureIn, next: boolean) => {
    setLastOn(next ? payload : null);
    setDisclosure.mutate(payload);
  };
  const budget = agent.greeting_budget;
  const room =
    budget && lastOn
      ? lastOn.ai_disclosure_enabled
        ? budget.opening_room_with_ai_disclosure
        : budget.opening_room_with_recording_notice
      : undefined;
  const needsRoom = problemCode(setDisclosure.error) === NOTICE_NEEDS_ROOM && room !== undefined;
  const introducedTwice =
    problemCode(setDisclosure.error) === OPENING_INTRODUCES && lastOn?.ai_disclosure_enabled === true;

  return (
    <section aria-labelledby="opening-notices-heading" className="max-w-3xl">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 id="opening-notices-heading" className="text-heading text-ink">
          What it says at the start of every call
        </h3>
        <p role="status" className="text-meta text-ink-muted">
          {feedback.status === "pending"
            ? "Saving…"
            : feedback.status === "success"
              ? "Saved. The next call uses this."
              : ""}
        </p>
      </div>

      {/* Above the switches, so two "off" positions are never read as "it may pass for
          human". Quiet on purpose: a guarantee, not an alert. */}
      <p className="mt-1 text-meta text-ink-muted">{promise.lead}</p>

      {setDisclosure.error && !needsRoom && !introducedTwice && (
        <ProblemNotice error={setDisclosure.error} />
      )}
      {introducedTwice && lastOn && (
        <IntroducedOpeningFix
          agent={agent}
          error={setDisclosure.error}
          retrying={setDisclosure.isPending}
          retry={() => setDisclosure.mutate(lastOn)}
        />
      )}
      {needsRoom && lastOn && (
        <OpeningLineFix
          agent={agent}
          error={setDisclosure.error}
          room={room}
          retrying={setDisclosure.isPending}
          retry={() => setDisclosure.mutate(lastOn)}
        />
      )}
      {write.reason && (
        <div className="mt-3">
          <RestrictionNote reason={write.reason} />
        </div>
      )}

      <div className="mt-3 divide-y divide-line border-y border-line">
        <NoticeToggle
          label="Say it is an AI assistant"
          checked={agent.ai_disclosure_enabled}
          pending={locked}
          onLine={`${name} says so when the call starts.`}
          offLine={`${name} won't bring it up, but still says so if a caller asks.`}
          onChange={(next) => flip({ ai_disclosure_enabled: next }, next)}
        />
        <NoticeToggle
          label="Say the call is being recorded"
          checked={agent.recording_notice_enabled}
          pending={locked}
          onLine={`${name} tells callers when the call starts.`}
          offLine="Calls are still recorded. You must tell callers another way."
          offIsWarning
          onChange={(next) => flip({ recording_notice_enabled: next }, next)}
        />
      </div>

      <CallStart
        agent={agent}
        name={name}
        calling={calling}
        edit={
          // A button, not a sentence: the opening line is changed on the Script tab.
          <Link
            href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=script`)}
            className={`${SECONDARY_BUTTON_SM} shrink-0 bg-surface`}
          >
            <PenLine aria-hidden className="h-4 w-4" />
            {calling !== null
              ? "Edit the opening lines"
              : opening
                ? "Edit the opening line"
                : "Write an opening line"}
          </Link>
        }
      />

      <Disclosure variant="inline" headingLevel={4} title="How these work" className="mt-2">
        <NoticeDetails promiseRest={promise.rest} hasOpening={opening !== ""} />
      </Disclosure>
    </section>
  );
}

/**
 * How a call starts: the server's opening text as sent, then what the switched-on notices
 * add — described, never written out. The agent words those itself, so a sentence printed
 * here would be one it may never say.
 */
function CallStart({
  agent,
  name,
  calling,
  edit,
}: {
  agent: Agent;
  name: string;
  calling: string | null;
  edit: ReactNode;
}) {
  const mentions = [
    agent.ai_disclosure_enabled ? "that it is an AI assistant" : null,
    agent.recording_notice_enabled ? "that the call is being recorded" : null,
  ].filter((part): part is string => part !== null);
  return (
    <div className="mt-4 rounded-lg bg-surface-muted px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <p className="text-meta font-medium text-ink-muted">How a call starts</p>
        {edit}
      </div>
      {calling !== null ? (
        // A "both" agent opens the calls it places with a line of their own (D-920).
        <dl className="mt-2 space-y-2">
          <FirstWords label="When it answers" words={agent.first_words} lang={agent.language_primary} />
          <FirstWords label="When it calls" words={calling} lang={agent.language_primary} />
        </dl>
      ) : (
        <Words words={agent.first_words} lang={agent.language_primary} className="mt-1" />
      )}
      {mentions.length > 0 && (
        <p className="mt-2 text-meta text-ink-muted">
          {name} also mentions, in its own words, {mentions.join(" and ")}.
        </p>
      )}
    </div>
  );
}

function Words({ words, lang, className = "" }: { words: string; lang: string; className?: string }) {
  return words.trim() ? (
    <p lang={lang} className={`text-body text-ink [overflow-wrap:anywhere] ${className}`}>
      {words}
    </p>
  ) : (
    <p className={`text-body text-ink-muted ${className}`}>No opening line yet.</p>
  );
}

/** One of a "both" agent's two first turns, labelled by the call it opens. */
function FirstWords({ label, words, lang }: { label: string; words: string; lang: string }) {
  return (
    <div>
      <dt className="text-meta text-ink-muted">{label}</dt>
      <dd>
        <Words words={words} lang={lang} />
      </dd>
    </div>
  );
}

/** What the notices block explains on request: the reasoning, never a control. */
function NoticeDetails({ promiseRest, hasOpening }: { promiseRest: string; hasOpening: boolean }) {
  return (
    <div className="space-y-2 pb-3 text-sm text-ink-muted">
      {promiseRest && <p>{promiseRest}</p>}
      <p>
        {hasOpening
          ? "The opening line is the agent's own greeting, from its script. "
          : "This agent's script has no opening line yet. "}
        These switches never change it. With a switch on, the agent adds the notice when it
        starts the call, in its own words; there is no fixed sentence it reads out.
      </p>
      <p>
        Calls are still recorded — the recording switch only stops the agent announcing it.
        Telling callers their call is recorded is still your responsibility under the{" "}
        <Term id="dpdp" term="DPDP Act" />; with this off, it has to be covered by your own
        privacy notice or consent. If a caller asks, the agent still says yes.
      </p>
      <p>Changes take effect on the next call.</p>
    </div>
  );
}

/**
 * One notice, as a switch and one line saying what its current position does.
 *
 * `pending` disables BOTH switches while either is in flight. The two write one row, and a
 * second click before the first response is a lost update the API has no way to catch —
 * `null` means "leave alone", so the second request would carry the pre-flight value of
 * neither field and simply race.
 */
function NoticeToggle({
  label,
  checked,
  pending,
  onLine,
  offLine,
  offIsWarning = false,
  onChange,
}: {
  label: string;
  checked: boolean;
  pending: boolean;
  onLine: string;
  offLine: string;
  /** Off leaves a duty the owner must meet elsewhere, so the off line is a warning. */
  offIsWarning?: boolean;
  onChange: (next: boolean) => void;
}) {
  const lineId = useId();
  const warn = !checked && offIsWarning;
  return (
    <ToggleSwitch
      label={label}
      checked={checked}
      disabled={pending}
      onChange={onChange}
      describedBy={lineId}
      className="py-3"
    >
      {/* `pl-12`: the switch (w-9) and its gap (gap-3), so the line sits under the label. */}
      <p
        id={lineId}
        data-notice={warn ? "warn" : undefined}
        className={`mt-0.5 flex items-start gap-1.5 pl-12 text-meta ${warn ? "text-ink" : "text-ink-muted"}`}
      >
        {warn && <TriangleAlert aria-hidden className="mt-[3px] h-3.5 w-3.5 shrink-0 text-warn" />}
        <span>{checked ? onLine : offLine}</span>
      </p>
    </ToggleSwitch>
  );
}
