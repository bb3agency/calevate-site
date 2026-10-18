"use client";

/**
 * "LET PIP DO IT" — how an owner asks for AI help with the script (D-820).
 *
 * Pip is the one assistant, so this strip writes nothing itself: every control prefills
 * Pip's ask box with a request about THIS agent's script, and the owner presses Ask there.
 * Pip prepares the suggestion; it comes back to this page for review (`PipProposal`).
 * The strip says before the first request that it spends the AI allowance.
 */

import { useState, type FormEvent } from "react";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { FIELD, FIELD_LABEL, RestrictionNote, SECONDARY_BUTTON } from "@/components/ui";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";

/** Example changes, kept from the helper this replaced; each prefills Pip as written. */
export const IDEAS = [
  "Handle callers who say the price is too high",
  "Make the opening line warmer and shorter",
  "Sound more like people talk here",
  "Ask for the delivery area before taking the order",
];

/** What Pip is asked, in the words the owner sees in its ask box. */
export const changeRequest = (change: string) => `Change this agent's script: ${change}`;
export const WHOLE_REQUEST = "Draft the whole script for this agent. Ask me the five questions first.";
/** The same request from a screen that is not the agent's own Script page. */
export const wholeRequestFor = (agentName: string) =>
  `Draft the whole script for my agent “${agentName}”. Ask me the five questions first.`;
export const STEPS_REQUEST = "Turn this agent's hand-written script into steps.";

export function PipAsk({ handWritten }: { handWritten: boolean }) {
  const session = useClientSession();
  // Asking Pip spends the account's AI allowance, which a view-as operator may not.
  const write = useActAccess(session, "org:manage", "billing.ai_assist", `ask ${ASSISTANT_NAME} to change this script`);
  const [change, setChange] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (change.trim()) openAssistant({ prompt: changeRequest(change.trim()) });
  };

  return (
    <section aria-label={`Ask ${ASSISTANT_NAME} to change the script`} className="max-w-3xl space-y-3 rounded-card border border-line p-4">
      <RestrictionNote reason={write.reason} />
      {handWritten ? (
        <div className="space-y-2">
          <p className="text-body text-ink">
            Your script is written by hand. {ASSISTANT_NAME} can lay it out as steps first, and
            change those after you keep them.
          </p>
          <AskAssistant label={`Let ${ASSISTANT_NAME} turn it into steps`} prompt={STEPS_REQUEST} disabled={!write.allowed} />
        </div>
      ) : (
        <>
          <form noValidate onSubmit={submit} className="space-y-1.5">
            <label className={FIELD_LABEL} htmlFor="pip-change">
              What should change?
            </label>
            <div className="flex flex-wrap gap-2">
              <input
                id="pip-change"
                className={`${FIELD} min-w-0 flex-1 basis-64`}
                maxLength={600}
                disabled={!write.allowed}
                value={change}
                placeholder="When someone asks for a discount, offer free delivery instead"
                onChange={(e) => setChange(e.target.value)}
              />
              <button type="submit" className={SECONDARY_BUTTON} disabled={!write.allowed || change.trim().length === 0}>
                Let {ASSISTANT_NAME} do it
              </button>
            </div>
          </form>
          <ul className="flex flex-wrap gap-1.5" aria-label="Ideas">
            {IDEAS.map((idea) => (
              <li key={idea}>
                <AskAssistant variant="chip" prompt={changeRequest(idea)} label={idea} disabled={!write.allowed} />
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <p className="text-meta text-ink-muted">
              Uses your AI allowance. You review every change here before it goes into your draft.
            </p>
            <AskAssistant label={`Let ${ASSISTANT_NAME} draft the whole script`} prompt={WHOLE_REQUEST} disabled={!write.allowed} />
          </div>
        </>
      )}
    </section>
  );
}
