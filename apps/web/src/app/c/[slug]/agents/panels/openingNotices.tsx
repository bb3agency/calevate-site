"use client";

/**
 * THE OPENING NOTICES — a compliance surface, and the one sentence no switch reaches.
 *
 * What stays on screen without a click (UX-DOCTRINE §3, §8 rule 7): the guarantee that the
 * agent answers honestly when asked, each switch with its one-line label and the sentence
 * the caller hears, and — while a notice is off — one line saying what off does NOT do.
 * Everything that explains rather than qualifies (where each notice falls in the opening,
 * the DPDP reasoning, why the memory sentence has no switch, when a change takes effect)
 * is in one closed disclosure under the block. The founder's reason (D-873, 24 Oct 2026):
 * every owner was made to read all of it on every visit, and stopped reading.
 */

import { PenLine, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import {
  Disclosure,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  ToggleSwitch,
  NOTICE_BAR,
  NOTICE_BASE,
} from "@/components/ui";
import { useSetDisclosure, type Agent, type DisclosureIn } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { Term } from "@/lib/glossary";

import { NOTICE_NEEDS_ROOM, OpeningLineFix, problemCode } from "./openingLineFix";

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
 * The two opening notices, as switches — and the one sentence the switches do not reach.
 *
 * ## What the client is actually deciding (D-163)
 *
 * "This is an AI" (TRAI/UCC) and "this call is recorded" (DPDP notice-and-consent) are
 * separate obligations under separate regimes, so they are separate switches; the client is
 * the Principal Entity and the exposure is theirs. `org:manage` is the owner's permission.
 * An operator in "view as client" can flip them too (D-587, over D-22's read-only rule):
 * every flip is audited, and an operator's names them and the view-as session.
 *
 * ## The three things "off" does not mean, each said on screen
 *
 * - **"Off" does not mean the agent lies.** `truthful_answer_rule` comes from the server and
 *   is drawn in the server's words, its first sentence above the switches. Paraphrasing it
 *   is how a client ends up believing they bought a bot that can pass for human.
 * - **"Off" does not stop the recording.** Nothing in the product can, so the recording
 *   switch's off line says the calls are still recorded.
 * - **"Off" does not discharge the obligation.** It moves where the notice is given; the
 *   off line says telling callers is still the owner's responsibility.
 *
 * `first_words` is the SERVER's composition of what callers hear first — the opening line
 * from the script, then the notices switched on (D-861) — quoted back, never joined here:
 * a second implementation of a compliance rule is where drift starts. No switch reaches the
 * opening line (D-708).
 *
 * The notice wording is not client-editable: `agents.ai_disclosure_line` /
 * `recording_notice_line` are NOT NULL and non-blank by CHECK constraint (hard rule 5) and
 * written only from the admin realm, so there is no textbox here, and the disclosure says
 * why rather than leaving a quote with no control beside it to read as an oversight.
 *
 * The memory sentence (D-507) has no switch: it is spoken exactly when the agent remembers
 * callers, so it is shown as a fact when `caller_memory_enabled` is true and its only
 * control is the memory setting. A toggle here would advertise a state ("remembers, says
 * nothing") the product cannot be configured into.
 */
export function OpeningNotices({ agent }: { agent: Agent }) {
  const { href } = useClientRealm();
  const session = useClientSession();
  const setDisclosure = useSetDisclosure(session, agent.id);
  // The switch's position is the success; a refusal is the notice (or the opening-line fix)
  // drawn here, so nothing is toasted.
  useActionFeedback(setDisclosure, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "switch these notices");
  const locked = setDisclosure.isPending || !write.allowed;
  const opening = agent.script_opening_line.trim();
  const firstWords = agent.first_words;
  const promise = splitPromise(agent.truthful_answer_rule);
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

  return (
    <section aria-labelledby="opening-notices-heading" className="max-w-3xl">
      <h3 id="opening-notices-heading" className="text-heading text-ink">
        What it says at the start of every call
      </h3>

      {/* Before the switches: two "off" positions read first would say the opposite. */}
      <p className="mt-2 flex items-start gap-2 text-sm text-ink">
        <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong" />
        <span>{promise.lead}</span>
      </p>

      {setDisclosure.error && !needsRoom && <ProblemNotice error={setDisclosure.error} />}
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

      {/* One left edge for the whole block: rows carry no side padding, and everything under
          a switch (its quote, its off line) is indented to the label, not to the switch. */}
      <div className="mt-3 divide-y divide-line border-y border-line">
        <NoticeToggle
          label="Say it is an AI assistant"
          quote={agent.ai_disclosure_line}
          checked={agent.ai_disclosure_enabled}
          pending={locked}
          offNote="If asked, it still says it is an AI."
          onChange={(next) => flip({ ai_disclosure_enabled: next }, next)}
        />
        <NoticeToggle
          label="Say the call is being recorded"
          quote={agent.recording_notice_line}
          checked={agent.recording_notice_enabled}
          pending={locked}
          offNote="Calls are still recorded. Tell callers yourself."
          onChange={(next) => flip({ recording_notice_enabled: next }, next)}
        />
        {agent.caller_memory_enabled && (
          <div className="py-3 pl-12">
            <p className="text-sm font-medium text-ink">Say that it remembers callers</p>
            <blockquote className="mt-2 border-l-2 border-line pl-3 text-sm italic text-ink-muted">
              “{agent.caller_memory_notice_line}”
            </blockquote>
            <p className="mt-2 text-xs text-ink-muted">
              No switch. Said while it remembers callers.
            </p>
          </div>
        )}
      </div>

      <div className="mt-4">
        <p className="text-xs font-medium text-ink-muted">What callers hear first</p>
        {firstWords.trim() ? (
          <blockquote className="mt-2 border-l-2 border-brand pl-3 text-sm italic text-ink">
            “{firstWords}”
          </blockquote>
        ) : (
          <p className="mt-2 text-sm text-ink-muted">Nothing yet.</p>
        )}
        {/* A button, not a sentence: the opening line is changed on the Script tab. */}
        <Link
          href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=script`)}
          className={`${SECONDARY_BUTTON_SM} mt-3 w-full justify-center sm:w-auto`}
        >
          <PenLine aria-hidden className="h-4 w-4" />
          {opening ? "Edit the opening line" : "Write an opening line"}
        </Link>
      </div>

      <Disclosure
        variant="inline"
        headingLevel={4}
        title="How these work"
        className="mt-2"
      >
        <NoticeDetails agent={agent} promiseRest={promise.rest} hasOpening={opening !== ""} />
      </Disclosure>
    </section>
  );
}

/** What the notices block explains on request: the reasoning, never a control. */
function NoticeDetails({
  agent,
  promiseRest,
  hasOpening,
}: {
  agent: Agent;
  promiseRest: string;
  hasOpening: boolean;
}) {
  return (
    <div className="space-y-2 pb-3 text-sm text-ink-muted">
      {promiseRest && <p>{promiseRest}</p>}
      <p>
        {hasOpening
          ? "The opening line is the agent's own greeting, from its script. "
          : "This agent's script has no opening line yet. "}
        These switches never change it. In Telugu and Hindi the AI notice is how the agent
        introduces itself, before its opening line. The recording notice is said after the
        opening line and the AI notice.
      </p>
      <p>
        Calls are still recorded — the recording switch only stops the agent announcing it.
        Telling callers their call is recorded is still your responsibility under the{" "}
        <Term id="dpdp" term="DPDP Act" />; with this off, it has to be covered by your own
        privacy notice or consent. If a caller asks, the agent still says yes.
      </p>
      {agent.caller_memory_enabled && (
        <p>
          The memory sentence is said once as the agent says goodbye, not when the caller
          asked to stop or hung up. It is said because this agent remembers what callers asked
          about between calls; turn that off and the sentence goes with it.
        </p>
      )}
      <p>
        Changes take effect on the next call. The notice sentences are written by us and
        cannot be edited here or switched off entirely — every agent must have all of them on
        file. Tell us if anything in the wording is wrong.
      </p>
    </div>
  );
}

/**
 * One notice, as a switch with its sentence under it.
 *
 * `pending` disables BOTH switches while either is in flight. The two write one row, and a
 * second click before the first response is a lost update the API has no way to catch —
 * `null` means "leave alone", so the second request would carry the pre-flight value of
 * neither field and simply race.
 */
function NoticeToggle({
  label,
  quote,
  checked,
  pending,
  offNote,
  onChange,
}: {
  label: string;
  quote: string;
  checked: boolean;
  pending: boolean;
  offNote: ReactNode;
  onChange: (next: boolean) => void;
}) {
  return (
    <ToggleSwitch label={label} checked={checked} disabled={pending} onChange={onChange} className="py-3">
      {/* `pl-12`: the switch (w-9) and its gap (gap-3), so these sit under the label. */}
      <div className="pl-12">
        <blockquote className="mt-2 border-l-2 border-line pl-3 text-sm italic text-ink-muted">
          “{quote}”
        </blockquote>
        {!checked && (
          <p className={`mt-2 ${NOTICE_BASE} ${NOTICE_BAR.warn}`}>
            <span>{offNote}</span>
          </p>
        )}
      </div>
    </ToggleSwitch>
  );
}
