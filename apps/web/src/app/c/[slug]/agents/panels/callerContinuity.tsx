"use client";

/**
 * ONE SWITCH, TWO ABILITIES — remembering callers, and booking the call-backs they ask
 * for (D-509/D-510).
 *
 * ## Why it is one switch and the screen says so out loud
 *
 * The founder's own framing: "two linked abilities, always on or off together". There is
 * one column behind this control and one reader, and a client who could switch one half
 * off would keep the half that REUSES what was remembered while withdrawing the half their
 * callers were told about. So the copy leads with both abilities rather than describing a
 * memory setting and mentioning call-backs as a footnote — a switch whose second effect is
 * discovered later is a switch nobody consented to.
 *
 * ## Why it is not in `OpeningNotices`
 *
 * That panel is about what the agent SAYS, and the memory sentence appears there as a
 * fact with no toggle precisely because it follows this switch. Putting the switch there
 * too would have made a data decision look like a third announcement setting. They point
 * at each other in copy instead: flip this and the sentence appears there.
 *
 * ## The attestation is a refusal, not a checkbox
 *
 * The API refuses the first switch-on with the statement to confirm as its remediation,
 * so this screen never renders an attestation it composed itself — it renders the one the
 * server sent, and sends `accept: true` only after the client has read that exact text.
 * Two consequences worth keeping: the screen and the refusal can never describe different
 * promises, and a business whose kind cannot use this at all is refused permanently by the
 * same channel with its own sentence, which `ProblemNotice` shows unchanged.
 */

import { BookOpenCheck, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { NOTICE_TONES, ProblemNotice, SectionHeading, ToggleSwitch } from "@/components/ui";
import { useSetCallerMemory, type Agent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";

/** The refusal code the API uses when this account has not confirmed what its calls hold. */
const NEEDS_ATTESTATION = "caller_memory_attestation_required";

function problemCode(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

function remediation(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const text = (error as { remediation?: unknown }).remediation;
  return typeof text === "string" ? text : null;
}

export function CallerContinuity({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const setCallerMemory = useSetCallerMemory(session, agent.id);
  // Local, and only for the width of one refusal: the server decides whether an
  // attestation is still needed, so this is the record of "the client has now READ it",
  // which is a fact about this screen and about nothing else.
  const [readStatement, setReadStatement] = useState(false);

  const needsAttestation = problemCode(setCallerMemory.error) === NEEDS_ATTESTATION;
  const statement = needsAttestation ? remediation(setCallerMemory.error) : null;

  return (
    <section>
      <SectionHeading icon={<BookOpenCheck className="h-3.5 w-3.5" />}>
        Remembering callers, and calling them back
      </SectionHeading>

      <p className="mt-2 text-sm text-ink-muted">
        Two things, always on or off together. Your agents remember the people they have
        spoken to, so someone who rings again is greeted with what they asked about last
        time. And when a caller asks to be rung back at a particular time, that call is
        booked for exactly then and goes out already knowing the conversation.
      </p>

      {setCallerMemory.error && !needsAttestation && (
        <ProblemNotice error={setCallerMemory.error} />
      )}

      <div className="mt-4 rounded-card border border-line bg-app p-4">
        <ToggleSwitch
          label="Remember callers and book their call-backs"
          checked={agent.caller_memory_enabled}
          disabled={setCallerMemory.isPending}
          onChange={(next) =>
            setCallerMemory.mutate({ enabled: next, accept: readStatement })
          }
        />
        <p className="mt-2 text-xs text-ink-muted">
          Off unless you switch it on.
        </p>

        {agent.caller_memory_enabled ? (
          <p
            className={`mt-3 flex items-start gap-2 rounded-lg border p-3 text-xs ${NOTICE_TONES.neutral}`}
          >
            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Your agents now say at the start of every call that a short note is kept.
              That sentence cannot be switched off on its own — it appears under{" "}
              <strong>What it says about itself</strong> above, and it goes away when this
              goes off.
            </span>
          </p>
        ) : null}

        <ul className="mt-3 space-y-1 text-xs text-ink-muted">
          <li>
            Kept: what the caller wanted, what happened, and anything they said they
            prefer — the language they like, when they prefer to be called, who they
            usually deal with.
          </li>
          <li>
            Never kept: health details, amounts of money, or anything quoted in their own
            words.
          </li>
          <li>
            Used only for that person&apos;s own future calls with you, never shared, and
            deleted after 180 days — or sooner if they ask.
          </li>
          <li>
            Writing these notes is charged to your account like any other assistant work,
            so your spending limit stops it along with everything else.
          </li>
        </ul>
      </div>

      {/* THE ATTESTATION, rendered ONLY from the server's own refusal — see the module
          note. A statement composed here could drift from the one the API enforces, and
          the drift would be a promise a client made about words nobody checked. */}
      {statement && (
        <div className="mt-4 rounded-card border border-line bg-app p-4">
          <p className="text-sm font-medium text-ink">
            Confirm what these calls collect
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            Asked once for your whole account, not once per agent.
          </p>
          <p className="mt-3 rounded-lg border border-line p-3 text-sm text-ink">
            {statement}
          </p>
          <label className="mt-3 flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={readStatement}
              onChange={(event) => setReadStatement(event.target.checked)}
            />
            <span>I have read this and confirm it is true of my business.</span>
          </label>
          <button
            type="button"
            className="mt-3 rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink disabled:opacity-50"
            disabled={!readStatement || setCallerMemory.isPending}
            onClick={() => setCallerMemory.mutate({ enabled: true, accept: true })}
          >
            Confirm and switch on
          </button>
        </div>
      )}
    </section>
  );
}
