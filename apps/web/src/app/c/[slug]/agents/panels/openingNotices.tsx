"use client";

/**
 * THE OPENING NOTICES — a compliance surface, and the one sentence no switch reaches.
 *
 * Split out of `agents/panels.tsx` with the rest of that file's four subjects. It is the
 * one piece of the agent workspace that UX-DOCTRINE §8 forbids putting behind a
 * disclosure: an obligation a client can switch off must be visible without a click, and
 * the guarantee it does NOT switch off must be visible above it.
 */

import { CircleAlert, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import {
  NOTICE_TONES,
  ProblemNotice,
  SectionHeading,
  TermGloss,
  ToggleSwitch,
} from "@/components/ui";
import { useSetDisclosure, type Agent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";

/**
 * The two opening notices, as switches — and the one sentence the switches do not reach.
 *
 * ## What the client is actually deciding (D-163)
 *
 * SEC-COMP §2 states two invariants that used to share one database column: "this is an
 * AI" (TRAI/UCC) and "this call is recorded" (DPDP notice-and-consent). They are separate
 * obligations under separate regimes, and they are separate switches — because the client
 * is the Principal Entity and the exposure is theirs to carry. `org:manage` is the
 * owner's permission and no admin or impersonating session holds it against a tenant
 * (D-22), so this is one of the few controls on the client app that is genuinely and only
 * theirs. Every flip is written to the audit log.
 *
 * ## Why the copy is written the way it is
 *
 * Three sentences a screen like this gets wrong, all of them avoided here:
 *
 * - **"Off" does not mean the agent lies.** `truthful_answer_rule` comes from the server
 *   (`compliance/disclosure.TRUTHFUL_ANSWER_PROMISE`) and is rendered verbatim, above the
 *   switches rather than under them. Paraphrasing it here is how a client ends up
 *   believing they bought a bot that can pass for human.
 * - **"Off" does not stop the recording.** Nothing in the product can, so the recording
 *   switch says what it moves — the notice — and not what it does not.
 * - **"Off" does not discharge the obligation.** It moves where the notice is given.
 *   Naming that plainly is the difference between a setting and a trap.
 *
 * `opening_line` is the SERVER's composition of what callers now hear, quoted back. This
 * screen never joins the two sentences itself: that would be a second implementation of a
 * compliance rule, and the second one is where the drift starts.
 *
 * ## The wording of the two sentences is not client-editable, and the screen says so
 *
 * `agents.ai_disclosure_line` / `recording_notice_line` are NOT NULL and non-blank by
 * CHECK constraint (hard rule 5), the dial gate refuses an agent with no AI sentence, and
 * every write to them is admin-realm. So there is no textbox here and there must not be
 * one — but a quoted sentence with no control beside it reads as an oversight, so the
 * reason is stated rather than left to be inferred.
 *
 * ## The third sentence, and why it has no switch (D-507)
 *
 * An agent that remembers callers between calls says so, as a third sentence in its
 * opening. It is NOT a third toggle, and rendering it as one would be a lie the screen
 * tells: the two above are switchable because their obligations hold whatever this product
 * is configured to do, while cross-call memory exists ONLY because somebody turned memory
 * on. So it appears here as a FACT — shown when `caller_memory_enabled` is true, absent
 * otherwise — with the switch it actually follows named in the copy, so a client reading
 * an opening with three sentences in it can see where the third came from.
 */
export function OpeningNotices({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const setDisclosure = useSetDisclosure(session, agent.id);

  return (
    <section>
      <SectionHeading icon={<ShieldCheck className="h-3.5 w-3.5" />}>
        What it says at the start of every call
      </SectionHeading>

      {/* FIRST, and deliberately not last: the guarantee has to be read before the
          switches, or a client reads two "off" positions and infers the opposite. */}
      <p
        className={`mt-2 flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES.neutral}`}
      >
        <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{agent.truthful_answer_rule}</span>
      </p>

      {setDisclosure.error && <ProblemNotice error={setDisclosure.error} />}

      <div className="mt-4 space-y-3">
        <NoticeToggle
          label="Say it is an AI assistant"
          hint="Spoken first, before anything else, in your language."
          quote={agent.ai_disclosure_line}
          checked={agent.ai_disclosure_enabled}
          pending={setDisclosure.isPending}
          offNote="Callers are not told at the start of the call. If one asks, the agent still says it is an AI."
          onChange={(next) => setDisclosure.mutate({ ai_disclosure_enabled: next })}
        />
        <NoticeToggle
          label="Say the call is being recorded"
          hint="Spoken with the line above, at the start of the call."
          quote={agent.recording_notice_line}
          checked={agent.recording_notice_enabled}
          pending={setDisclosure.isPending}
          offNote={
            <>
              Calls are still recorded — this only stops the agent announcing it. Telling
              callers their call is recorded is still your responsibility under the{" "}
              <TermGloss term="DPDP">
                India&apos;s Digital Personal Data Protection Act
              </TermGloss>{" "}
              Act; with this off, it has to be covered by your own privacy notice or
              consent. If a caller asks, the agent still says yes.
            </>
          }
          onChange={(next) => setDisclosure.mutate({ recording_notice_enabled: next })}
        />

        {/* NO SWITCH, deliberately (D-507): this sentence is spoken exactly when the agent
            remembers callers, so the only control over it is the memory setting itself.
            Shown as a bordered card like the two above so it reads as part of the same
            opening, and without the toggle affordance so it cannot read as one more thing
            to turn off. */}
        {agent.caller_memory_enabled && (
          <div className="rounded-card border border-line bg-app p-4">
            <p className="text-sm font-medium text-ink">Say that it remembers callers</p>
            <p className="mt-0.5 text-xs text-ink-muted">
              Spoken last, after the sentences above.
            </p>
            <blockquote className="mt-3 border-l-2 border-line pl-3 text-sm italic text-ink-muted">
              “{agent.caller_memory_notice_line}”
            </blockquote>
            <p
              className={`mt-3 flex items-start gap-2 rounded-lg border p-3 text-xs ${NOTICE_TONES.neutral}`}
            >
              <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                This one has no switch. It is said because this agent remembers what callers
                asked about between calls — turn that off and the sentence goes with it. An
                agent that remembers people without telling them is not something this
                product can be configured into.
              </span>
            </p>
          </div>
        )}
      </div>

      {/* The server's composition, quoted — this is the actual first utterance. */}
      <div className="mt-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
          What callers hear first
        </p>
        {agent.opening_line.trim() ? (
          <blockquote className="mt-2 border-l-2 border-brand pl-3 text-sm italic text-ink">
            “{agent.opening_line}”
          </blockquote>
        ) : (
          <p className="mt-2 text-sm text-ink-muted">
            Nothing. The agent opens straight into its script. It still answers honestly if
            a caller asks whether it is an AI or whether the call is recorded.
          </p>
        )}
        <p className="mt-2 text-xs text-ink-muted">
          Changes take effect on the next call. The sentences themselves are written by your
          account manager and cannot be edited here or switched off entirely — every agent
          must have all of them on file. Tell them if anything in the wording is wrong.
        </p>
      </div>
    </section>
  );
}

/**
 * One notice, as a switch with its sentence under it.
 *
 * The control is the shared `ToggleSwitch` (components/ui.tsx) rather than a fourth copy
 * of the `peer-checked:` class string — see that component for why the native
 * `<input type="checkbox" role="switch">` is the right element and why the label wraps it.
 * What stays local is everything that is ABOUT a compliance notice: the quoted sentence
 * and the amber "what off does not do" note.
 *
 * `pending` disables BOTH switches while either is in flight. The two write one row, and a
 * second click before the first response is a lost update the API has no way to catch —
 * `null` means "leave alone", so the second request would carry the pre-flight value of
 * neither field and simply race.
 */
function NoticeToggle({
  label,
  hint,
  quote,
  checked,
  pending,
  offNote,
  onChange,
}: {
  label: string;
  hint: string;
  quote: string;
  checked: boolean;
  pending: boolean;
  offNote: ReactNode;
  onChange: (next: boolean) => void;
}) {
  return (
    <ToggleSwitch
      label={label}
      hint={hint}
      checked={checked}
      disabled={pending}
      onChange={onChange}
      className="rounded-card border border-line bg-app p-4"
    >
      <blockquote className="mt-3 border-l-2 border-line pl-3 text-sm italic text-ink-muted">
        “{quote}”
      </blockquote>
      {!checked && (
        <p
          className={`mt-3 flex items-start gap-2 rounded-lg border p-3 text-xs ${NOTICE_TONES.warn}`}
        >
          <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{offNote}</span>
        </p>
      )}
    </ToggleSwitch>
  );
}
