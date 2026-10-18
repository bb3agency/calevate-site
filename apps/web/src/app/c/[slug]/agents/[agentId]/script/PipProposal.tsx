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

import { PipMark } from "@/components/illustration/pip";
import { NoticeBox, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { EMPTY_SCRIPT, useClearProposal, useScriptProposal, type CallScript } from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { ProposalReview } from "./ProposalReview";

/** Steps made from a hand-written script start empty, keeping the owner's own switches. */
export function structuredBase(script: CallScript): CallScript {
  return { ...EMPTY_SCRIPT, policies: script.policies, variables: script.variables };
}

export function PipProposal({
  agentId,
  script,
  canWrite,
  onKeep,
}: {
  agentId: string;
  /** The editor's working copy. */
  script: CallScript;
  canWrite: boolean;
  onKeep: (next: CallScript) => void;
}) {
  const session = useClientSession();
  const pending = useScriptProposal(session, agentId);
  const clear = useClearProposal(session, agentId);
  const [read, setRead] = useState(false);
  const proposal = pending.data;
  if (!proposal) return null;

  const dismiss = (
    <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canWrite || clear.isPending} onClick={() => clear.mutate(proposal.id)}>
      Dismiss
    </button>
  );

  if (proposal.status === "drafting") {
    return (
      <p role="status" className="flex max-w-3xl items-center gap-2 text-meta text-ink-muted">
        <PipMark size={16} thinking className="shrink-0" />
        <span>
          <span>{ASSISTANT_NAME} is writing your suggestion…</span> It takes about half a minute.
        </span>
      </p>
    );
  }
  if (proposal.status === "failed" || proposal.script === null) {
    return (
      <NoticeBox tone="warn" title={`${ASSISTANT_NAME} could not write that suggestion`} action={dismiss}>
        <p className="mt-1 text-meta">{proposal.note}</p>
      </NoticeBox>
    );
  }

  const steps = proposal.mode === "steps";
  if (steps !== (script.raw_override !== null)) {
    return (
      <NoticeBox tone="neutral" title="This suggestion no longer fits" action={dismiss}>
        <p className="mt-1 text-meta">
          The script was switched between steps and writing by hand after {ASSISTANT_NAME} wrote it.
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
      >
        {proposal.request && <p className="text-meta text-ink-muted">You asked: “{proposal.request}”</p>}
        {proposal.mode === "whole" && <p className="text-meta text-ink-muted">Drafted from your answers.</p>}
        {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
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
              <p className="mt-2 text-meta">Add them to a step after keeping the changes, or discard and edit your text.</p>
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
