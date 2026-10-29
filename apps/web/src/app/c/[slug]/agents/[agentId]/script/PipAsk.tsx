"use client";

/**
 * "TELL PIP WHAT TO CHANGE" — how an owner asks for AI help with the script (D-820), as a
 * panel beside the steps on a wide screen and under the opening line on a narrow one
 * (D-825).
 *
 * Pip is the one assistant, so this panel writes nothing itself: every control prefills
 * Pip's ask box with a request about THIS agent's script, and the owner presses Ask there.
 * Pip prepares the suggestion; it comes back to this page for review (`PipProposal`).
 * The panel says before the first request that it spends the AI allowance.
 */

import { useState, type FormEvent } from "react";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { FIELD, FIELD_LABEL, RestrictionNote, SECONDARY_BUTTON } from "@/components/ui";
import { PipMark } from "@/components/illustration/pip";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/** Example changes any business might ask for; each prefills Pip as written. The account's
 * own idea (`scriptChangeIdea`, D-827) is offered after them. */
export const IDEAS = [
  "Handle callers who say the price is too high",
  "Make the opening line warmer and shorter",
  "Sound more like people talk here",
];

/** What Pip is asked, in the words the owner sees in its ask box. */
export const changeRequest = (change: string) => `Change this agent's script: ${change}`;
export const WHOLE_REQUEST = "Draft the whole script for this agent. Ask me the six questions first.";
/** The same request from a screen that is not the agent's own Script page. */
export const wholeRequestFor = (agentName: string) =>
  `Draft the whole script for my agent “${agentName}”. Ask me the six questions first.`;
export const STEPS_REQUEST = "Turn this agent's hand-written script into steps.";

export function PipAsk({ handWritten }: { handWritten: boolean }) {
  const session = useClientSession();
  // Asking Pip spends the account's AI allowance, which a view-as operator may not.
  const write = useActAccess(session, "org:manage", "billing.ai_assist", `ask ${ASSISTANT_NAME} to change this script`);
  const [change, setChange] = useState("");
  const eg = useVerticalExamples();
  const ideas = IDEAS.includes(eg.scriptChangeIdea) ? IDEAS : [...IDEAS, eg.scriptChangeIdea];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (change.trim()) openAssistant({ prompt: changeRequest(change.trim()) });
  };

  return (
    <section aria-labelledby="pip-ask-heading" className="space-y-3 rounded-card border border-line bg-surface p-4">
      <h3 id="pip-ask-heading" className="flex items-center gap-2 text-heading text-ink">
        <PipMark size={18} className="shrink-0" />
        Tell {ASSISTANT_NAME} what to change
      </h3>
      <RestrictionNote reason={write.reason} />
      {handWritten ? (
        <div className="space-y-2">
          <p className="text-body text-ink">Written by hand. Turn it into steps first.</p>
          <AskAssistant label={`Let ${ASSISTANT_NAME} turn it into steps`} prompt={STEPS_REQUEST} disabled={!write.allowed} />
        </div>
      ) : (
        <>
          <form noValidate onSubmit={submit} className="space-y-2">
            <label className={FIELD_LABEL} htmlFor="pip-change">
              What should change?
            </label>
            <textarea
              id="pip-change"
              className={`${FIELD} mt-0`}
              rows={3}
              maxLength={600}
              disabled={!write.allowed}
              value={change}
              placeholder={eg.scriptChange}
              onChange={(e) => setChange(e.target.value)}
            />
            <button type="submit" className={SECONDARY_BUTTON} disabled={!write.allowed || change.trim().length === 0}>
              Let {ASSISTANT_NAME} do it
            </button>
          </form>
          <div className="space-y-1.5">
            <p className="text-meta text-ink-muted">Or tap one:</p>
            <ul className="flex flex-wrap gap-1.5" aria-label="Ideas">
              {ideas.map((idea) => (
                <li key={idea}>
                  <AskAssistant variant="chip" prompt={changeRequest(idea)} label={idea} disabled={!write.allowed} />
                </li>
              ))}
            </ul>
          </div>
          <p className="text-meta text-ink-muted">
            Uses your AI allowance. You check every change first.
          </p>
          <AskAssistant label={`Let ${ASSISTANT_NAME} draft the whole script`} prompt={WHOLE_REQUEST} disabled={!write.allowed} />
        </>
      )}
    </section>
  );
}
