"use client";

/**
 * THE SUGGESTION PIP PREPARED, REVIEWED WHERE THE SCRIPT LIVES (D-820).
 *
 * Pip writes a suggestion when the owner asks it to (`agent_script_suggest`); the server
 * keeps it on the agent until it is kept or discarded. This shows it while it is written,
 * then as the same tick-to-keep list the old helper used (`ProposalReview`): the kept parts
 * go into the working copy, never live. A suggestion made from a hand-written script (steps)
 * waits until the owner has read any lines that fit nowhere.
 *
 * Changes are listed against the script the suggestion was made from, so an edit made
 * since is never offered back; the kept ones are applied to the working copy.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { PipMark } from "@/components/illustration/pip";
import { NoticeBox, ProblemNotice } from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import {
  EMPTY_SCRIPT,
  useClearProposal,
  useScriptProposal,
  type CallScript,
  type ScriptProposal,
} from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { onePartRequest } from "./PipAsk";
import { ProposalReview } from "./ProposalReview";
import { DEFAULT_LIMITS, type Limits } from "./scriptModel";
import { languageName } from "./sectionParts";

/**
 * The parts Pip left as the owner had them because its words for them broke a call rule:
 * the rest of the suggestion is still offered, and these are named rather than dropped
 * without a word.
 */
function LeftOutNotice({ parts }: { parts: ScriptProposal["left_out"] }) {
  const one = parts.length === 1;
  return (
    <NoticeBox tone="neutral" title={`${parts.length} ${one ? "part" : "parts"} kept as you had ${one ? "it" : "them"}`}>
      <ul className="mt-2 space-y-1 text-meta">
        {parts.map((part) => (
          <li key={part.part} className="break-words [overflow-wrap:anywhere]">
            <span className="font-semibold">{part.label}</span>
            {part.added ? " (not added)" : ""}: {part.rule}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-meta">Edit {one ? "it" : "them"} yourself, or ask {ASSISTANT_NAME} for one at a time.</p>
    </NoticeBox>
  );
}

/** Steps made from a hand-written script start empty, keeping the owner's own switches. */
export function structuredBase(script: CallScript): CallScript {
  return { ...EMPTY_SCRIPT, policies: script.policies, variables: script.variables };
}

export function PipProposal({
  agentId,
  script,
  canWrite,
  onKeep,
  limits = DEFAULT_LIMITS,
  language,
}: {
  agentId: string;
  /** The editor's working copy. */
  script: CallScript;
  canWrite: boolean;
  onKeep: (next: CallScript) => void;
  /** The builder's limits, which a reworded suggestion is held to. */
  limits?: Limits;
  /** The agent's language code. */
  language?: string;
}) {
  const session = useClientSession();
  const pending = useScriptProposal(session, agentId);
  const clear = useClearProposal(session, agentId);
  // The suggestion leaves the screen when it is cleared; a refusal is drawn under it.
  const clearFeedback = useActionFeedback(clear, { errorDisplay: "inline" });
  const [read, setRead] = useState(false);
  const proposal = pending.data;
  if (!proposal) return null;

  const dismiss = (
    <ActionButton
      variant="secondary-sm"
      status={clearFeedback.status}
      pendingLabel="Dismissing…"
      successLabel="Dismissed"
      disabled={!canWrite}
      onClick={() => clearFeedback.run(proposal.id)}
    >
      Dismiss
    </ActionButton>
  );

  if (proposal.status === "drafting") {
    return (
      <p role="status" className="flex max-w-3xl items-center gap-2 text-meta text-ink-muted">
        <PipMark size={16} thinking className="shrink-0" />
        <span>
          <span>
            {proposal.mode === "knowledge"
              ? `${ASSISTANT_NAME} is adding your new file to this script…`
              : `${ASSISTANT_NAME} is writing your suggestion…`}
          </span>{" "}
          A big change can take a couple of minutes.
        </span>
      </p>
    );
  }
  if (proposal.status === "failed" || proposal.script === null) {
    return (
      <NoticeBox tone="warn" title={`${ASSISTANT_NAME} could not write that suggestion`} action={dismiss}>
        <p className="mt-1 text-meta">{proposal.note}</p>
        {canWrite && (proposal.left_out ?? []).length > 0 && (
          <ul aria-label="Parts to ask for one at a time" className="mt-2 flex flex-wrap gap-2">
            {(proposal.left_out ?? []).map((part) => (
              <li key={part.part}>
                <AskAssistant
                  label={`Ask for ${part.label.charAt(0).toLowerCase()}${part.label.slice(1)} alone`}
                  prompt={onePartRequest(part.label, proposal.request)}
                />
              </li>
            ))}
          </ul>
        )}
      </NoticeBox>
    );
  }

  const steps = proposal.mode === "steps";
  if (steps !== (script.raw_override !== null)) {
    return (
      <NoticeBox tone="neutral" title="This suggestion no longer fits" action={dismiss}>
        <p className="mt-1 text-meta">
          The script changed form after {ASSISTANT_NAME} wrote it.
        </p>
      </NoticeBox>
    );
  }
  if (!canWrite) {
    return (
      <NoticeBox tone="neutral" title={`A suggestion from ${ASSISTANT_NAME} is waiting`}>
        <p className="mt-1 text-meta">Someone who can edit this script can review it.</p>
      </NoticeBox>
    );
  }

  const { unplaced } = proposal;
  return (
    <section aria-label={`${ASSISTANT_NAME}'s suggestion`} className="max-w-3xl rounded-card border border-line p-4">
      <ProposalReview
        key={proposal.id}
        current={steps ? structuredBase(script) : script}
        base={steps ? undefined : proposal.base_script}
        proposal={proposal.script}
        onApply={(next) => clear.mutate(proposal.id, { onSuccess: () => onKeep(next) })}
        onDiscard={() => clear.mutate(proposal.id)}
        gate={steps && unplaced.length > 0 && !read ? "Read the lines that did not fit anywhere first." : null}
        limits={limits}
        language={languageName(language)}
      >
        {proposal.request && <p className="text-meta text-ink-muted">You asked: “{proposal.request}”</p>}
        {proposal.mode === "whole" && <p className="text-meta text-ink-muted">Drafted from your answers.</p>}
        {proposal.mode === "opening" && (
          <p className="text-meta text-ink-muted">An opening line for after your agent says who it is.</p>
        )}
        {proposal.mode === "starter" && (
          <p className="text-meta text-ink-muted">Your script, written for your business. Keep what fits.</p>
        )}
        {proposal.mode === "written" && (
          <p className="text-meta text-ink-muted">An opening line written for your business, in {languageName(language)}.</p>
        )}
        {proposal.mode === "knowledge" && (
          <p className="text-meta text-ink-muted">
            From your new file: {proposal.documents.map((name) => `“${name}”`).join(", ")}. Your own lines stay.
          </p>
        )}
        {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
        {(proposal.left_out ?? []).length > 0 && <LeftOutNotice parts={proposal.left_out} />}
        {steps &&
          (unplaced.length === 0 ? (
            <p className="text-meta text-ink">Every line of your script has a place in these steps.</p>
          ) : (
            <NoticeBox
              tone="warn"
              title={`${unplaced.length} ${unplaced.length === 1 ? "line does" : "lines do"} not appear in the steps`}
            >
              <ul className="mt-2 list-disc space-y-1 pl-5 text-meta">
                {unplaced.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
              <p className="mt-2 text-meta">Add them to a step later, or discard this.</p>
              <label className="mt-2 flex items-start gap-2 text-meta">
                <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />
                <span>I have read these lines</span>
              </label>
            </NoticeBox>
          ))}
      </ProposalReview>
      {clear.error && (
        <div className="mt-3">
          <ProblemNotice error={clear.error} />
        </div>
      )}
    </section>
  );
}
