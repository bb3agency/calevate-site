"use client";

/**
 * ONE SWITCH, TWO ABILITIES — remembering callers, and booking the call-backs they ask
 * for (D-513/D-514).
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
 *
 * ## Paused on an older statement (D-900)
 *
 * When the statement changes, an account that accepted the old one no longer has memory on
 * any agent until its owner accepts the new one; the switch stays where they left it. The
 * agent row says so (`caller_memory_paused`) and carries the statement to accept, so the
 * re-accept prompt is rendered from the server's words like the first one.
 */

import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NoticeBox, ProblemNotice, RestrictionNote, ToggleSwitch } from "@/components/ui";
import { HowItWorks } from "@/components/console/howItWorks";
import { useSetCallerMemory, type Agent } from "@/lib/api/agents";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

import { problemCode } from "./openingLineFix";

/** The refusal code the API uses when this account has not confirmed what its calls hold. */
const NEEDS_ATTESTATION = "caller_memory_attestation_required";

function remediation(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const text = (error as { remediation?: unknown }).remediation;
  return typeof text === "string" ? text : null;
}

export function CallerContinuity({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const setCallerMemory = useSetCallerMemory(session, agent.id);
  // Every refusal here has its own place on the screen (the notice and
  // the attestation), so none is toasted.
  const memoryFeedback = useActionFeedback(setCallerMemory, { errorDisplay: "inline" });
  // Which control sent the last request: the confirm button shows its own state only for
  // its own press, not the switch's first refusal that brought it onto the screen.
  const [confirming, setConfirming] = useState(false);
  const [reaccepting, setReaccepting] = useState(false);
  const paused = agent.caller_memory_paused && Boolean(agent.caller_memory_statement);
  // Local, and only for the width of one refusal: the server decides whether an
  // attestation is still needed, so this is the record of "the client has now READ it",
  // which is a fact about this screen and about nothing else.
  const [readStatement, setReadStatement] = useState(false);

  /**
   * THE SWITCH IS ONE THING AND THE ATTESTATION IS ANOTHER (D-587), and only the second is
   * withheld. Flipping caller memory is `org:manage`, which a view-as operator holds — a
   * client on the phone asking us to switch it off is exactly the support job the
   * reversal exists for. ATTESTING is refused by name
   * (`agents/routes.py:974`, `compliance.caller_memory_attestation`): the row it writes is
   * `organizations.caller_memory_attested_by`, a `users.id` of the account, and an
   * operator has none. So the confirm control below reads the ground instead of posting an
   * `accept: true` the server answers 403 to.
   */
  const attest = useActAccess(
    session,
    "org:manage",
    "compliance.caller_memory_attestation",
    "confirm what this account's calls collect",
  );

  const needsAttestation = problemCode(setCallerMemory.error) === NEEDS_ATTESTATION;
  const statement = needsAttestation ? remediation(setCallerMemory.error) : null;

  return (
    <section>
      <h3 className="text-heading text-ink">Remembering callers</h3>
      <p className="mt-1 text-body text-ink-muted">
        Greets returning callers with what they asked last time, and books the call-backs
        they ask for.
      </p>

      {setCallerMemory.error && !needsAttestation && (
        <ProblemNotice error={setCallerMemory.error} />
      )}

      {paused && (
        <div className="mt-4">
          <NoticeBox tone="warn" role="status" title="Caller memory is paused until you accept the updated statement">
            No agent remembers callers until then. Accepting resumes it on every agent you left on.
          </NoticeBox>
          <blockquote className="mt-3 border-l-2 border-brand pl-4 text-body text-ink">
            {agent.caller_memory_statement}
          </blockquote>
          <div className="mt-3">
            <RestrictionNote reason={attest.reason} />
          </div>
          <ActionButton
            className="mt-3"
            status={reaccepting ? memoryFeedback.status : "idle"}
            successLabel="Resumed"
            disabled={!attest.allowed || setCallerMemory.isPending}
            title={attest.reason ?? undefined}
            onClick={() => {
              setConfirming(false);
              setReaccepting(true);
              setCallerMemory.mutate({ enabled: true, accept: true });
            }}
          >
            Accept and resume
          </ActionButton>
        </div>
      )}

      <div className="mt-4">
        <ToggleSwitch
          label="Remember callers and book their call-backs"
          checked={agent.caller_memory_enabled}
          disabled={setCallerMemory.isPending}
          onChange={(next) => {
            setConfirming(false);
            setReaccepting(false);
            setCallerMemory.mutate({ enabled: next, accept: readStatement });
          }}
        />
        <p className="mt-2 flex items-start gap-2 text-xs text-ink-muted">
          <ShieldCheck aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {paused
              ? "Once resumed, the agent tells"
              : agent.caller_memory_enabled
                ? "This agent tells"
                : "When on, the agent tells"}{" "}
            callers, as it says goodbye, that a short note is kept. Notes are charged like
            other assistant work and stop at your spending limit.
          </span>
        </p>

        <HowItWorks
          items={[
            "Kept: what they wanted, what happened, and preferences like language, call time or contact.",
            "Never kept: health details, amounts of money, or their exact words.",
            "Used only for that person's calls with you, never shared. Deleted after 180 days, or sooner if asked.",
            "The goodbye sentence goes with this switch; it cannot be turned off on its own.",
            "If the statement you confirm changes, memory pauses on every agent until you accept the new one.",
          ]}
        />
      </div>

      {/* THE ATTESTATION, rendered ONLY from the server's own refusal — see the module
          note. A statement composed here could drift from the one the API enforces, and
          the drift would be a promise a client made about words nobody checked. */}
      {statement && (
        <div className="mt-6 border-t border-line pt-5">
          <p className="text-body font-semibold text-ink">
            Confirm what these calls collect
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            Asked once for your whole account, not once per agent.
          </p>
          <blockquote className="mt-3 border-l-2 border-brand pl-4 text-body text-ink">
            {statement}
          </blockquote>
          <div className="mt-3">
            <RestrictionNote reason={attest.reason} />
          </div>
          <label className="mt-3 flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-0.5"
              disabled={!attest.allowed}
              checked={readStatement}
              onChange={(event) => setReadStatement(event.target.checked)}
            />
            <span>I have read this and confirm it is true of my business.</span>
          </label>
          <ActionButton
            className="mt-4"
            status={confirming ? memoryFeedback.status : "idle"}
            successLabel="Switched on"
            disabled={!attest.allowed || !readStatement || (setCallerMemory.isPending && !confirming)}
            title={attest.reason ?? undefined}
            onClick={() => {
              setConfirming(true);
              setCallerMemory.mutate({ enabled: true, accept: true });
            }}
          >
            Confirm and switch on
          </ActionButton>
        </div>
      )}
    </section>
  );
}
