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
 *
 * It is the teach card's shape (`knowledge/TeachBox`): one well holding the words and the
 * button that sends them, so the field and its action read as one control rather than a
 * box with a grey button floating under it. The ask stays pressable while empty and says
 * what is missing, because a greyed button gives no reason.
 */

import { useState } from "react";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { ActionButton } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { useFormValidation } from "@/components/formValidation";
import { RestrictionNote } from "@/components/ui";
import { PipMark } from "@/components/illustration/pip";
import { showsPrice, useBusinessProfile } from "@/lib/api/businessProfile";
import { useActAccess } from "@/lib/api/hooks";
import { useBusinessCapabilities } from "@/lib/businessCapabilities";
import { useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/** An idea: a few words on the chip, the full request in Pip's ask box. Short labels keep
 *  the ideas to a wrapping row or two in the side panel instead of a stack of sentences. */
export interface ChangeIdea {
  label: string;
  request: string;
}

/** Only for a business that quotes prices: to one that does not, it suggests a conversation its callers never have. */
export const PRICE_IDEA: ChangeIdea = { label: "Price is too high", request: "Handle callers who say the price is too high" };
/** Changes any business might ask for. */
export const IDEAS: readonly ChangeIdea[] = [
  { label: "Warmer, shorter opening", request: "Make the opening line warmer and shorter" },
  { label: "Sound more local", request: "Sound more like people talk here" },
];

/** What Pip is asked, in the words the owner sees in its ask box. */
export const changeRequest = (change: string) => `Change this agent's script: ${change}`;
export const WHOLE_REQUEST = "Draft the whole script for this agent. Ask me the six questions first.";
/** The same request from a screen that is not the agent's own Script page. */
export const wholeRequestFor = (agentName: string) =>
  `Draft the whole script for my agent “${agentName}”. Ask me the six questions first.`;
export const STEPS_REQUEST = "Turn this agent's hand-written script into steps.";

/**
 * The ideas offered: the account's own first (`scriptChangeIdea`, D-827), because it names
 * this business's callers and products; it is written under eight words, so it is its own
 * label. Then the price idea where prices apply, then the ones any business might ask for.
 */
export function changeIdeas({ idea, priced }: { idea: string; priced: boolean }): ChangeIdea[] {
  const own = idea.trim();
  const all = [own ? { label: own, request: own } : null, priced ? PRICE_IDEA : null, ...IDEAS].filter(
    (x): x is ChangeIdea => x !== null,
  );
  return all.filter((x, i) => all.findIndex((y) => y.request === x.request) === i);
}

/** Steps only: a hand-written script's one move is under the script (`HandWritten`). */
export function PipAsk({ drafting = false }: { drafting?: boolean } = {}) {
  const session = useClientSession();
  // Asking Pip spends the account's AI allowance, which a view-as operator may not.
  const write = useActAccess(session, "org:manage", "billing.ai_assist", `ask ${ASSISTANT_NAME} to change this script`);
  // One suggestion at a time: the server refuses a second ask while one is being written
  // (`script_proposal_in_progress`). The builder's suggestion read polls, so this lifts by
  // itself, and a draft stuck past the server's limit reads as failed and lifts it too.
  const asking = write.allowed && !drafting;
  const [change, setChange] = useState("");
  const eg = useVerticalExamples();
  const profile = useBusinessProfile(session);
  const caps = useBusinessCapabilities();
  const valid = useFormValidation();
  const changeField = valid.field("change", "Write what should change.");

  // Until the profile is read, no price idea: offering one to a business that quotes none
  // is the mistake, leaving it out for a moment is not.
  const priced = profile.data && caps.quotesPrices !== false
    ? showsPrice(profile.data.wording, profile.data.services.map((s) => ({ price_inr: s.price_inr ?? "" })))
    : false;
  const ideas = changeIdeas({ idea: eg.scriptChangeIdea, priced });

  return (
    <section aria-labelledby="pip-ask-heading" className="space-y-3 rounded-card border border-line bg-surface p-4">
      <h3 id="pip-ask-heading" className="flex items-center gap-2 text-heading text-ink">
        <PipMark size={18} className="shrink-0" />
        Tell {ASSISTANT_NAME} what to change
      </h3>
      <RestrictionNote reason={write.reason} />
      <form
        noValidate
        className="space-y-2"
        onSubmit={valid.onSubmit(() => {
          if (asking) openAssistant({ prompt: changeRequest(change.trim()) });
        })}
      >
        <label className="sr-only" htmlFor="pip-change">
          What should change?
        </label>
        {/* The well, not the bare textarea, carries the focus and invalid states, so the
            button inside it reads as part of the field. */}
        <div
          className={`rounded-card border border-line transition-[border-color,box-shadow] duration-(--duration-fast) ease-out focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20 has-[textarea[aria-invalid=true]]:border-danger ${
            write.allowed ? "bg-surface" : "bg-surface-muted"
          }`}
        >
          <textarea
            {...changeField}
            required
            id="pip-change"
            rows={2}
            // No `maxLength`: it cuts a paste without a word. Pip's ask box, which this
            // prefills, shows the count and holds Send past the limit.
            disabled={!write.allowed}
            value={change}
            placeholder="What should it say or do differently?"
            onChange={(e) => setChange(e.target.value)}
            className="block min-h-16 max-h-60 w-full resize-none rounded-t-card [field-sizing:content] bg-transparent px-3 pt-2.5 pb-1 text-body text-ink placeholder:text-ink-faint focus:outline-none disabled:cursor-not-allowed"
          />
          <div className="flex justify-end px-2 pb-2">
            <div className="flex flex-col items-end gap-1 text-right">
              <ActionButton
                type="submit"
                variant="primary-sm"
                disabled={!write.allowed}
                title={write.reason ?? undefined}
                waitingFor={write.allowed && drafting ? `Wait for ${ASSISTANT_NAME} to finish this suggestion` : null}
              >
                Ask {ASSISTANT_NAME}
              </ActionButton>
            </div>
          </div>
        </div>
        {valid.error("change")}
        <p className="text-meta text-ink-muted">Uses your AI allowance. You check every change first.</p>
      </form>
      {ideas.length ? (
        <div className="space-y-1.5">
          <p id="pip-ask-ideas" className="text-meta font-medium text-ink-muted">
            Or try
          </p>
          <ul aria-labelledby="pip-ask-ideas" className="flex flex-wrap gap-1.5">
            {ideas.map((idea) => (
              <li key={idea.request} className="min-w-0 max-w-full">
                <AskAssistant
                  variant="chip"
                  prompt={changeRequest(idea.request)}
                  label={idea.label}
                  disabled={!asking}
                  className="max-w-full text-left [overflow-wrap:anywhere]"
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="border-t border-line pt-2">
        <button
          type="button"
          className={TEXT_ACTION}
          disabled={!asking}
          onClick={() => openAssistant({ prompt: WHOLE_REQUEST })}
          // The name carries the request, as `AskAssistant` does: "the whole script" alone
          // does not say a screen-reader user will be asked six questions first.
          aria-label={`Let ${ASSISTANT_NAME} draft the whole script: ${WHOLE_REQUEST}`}
          title={WHOLE_REQUEST}
        >
          Let {ASSISTANT_NAME} draft the whole script
        </button>
      </div>
    </section>
  );
}
