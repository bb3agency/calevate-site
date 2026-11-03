"use client";

import { useEffect, useState } from "react";

import type { Session } from "@/lib/api/client";
import { useScript, useScriptProposal, type CallScript } from "@/lib/api/script";

/**
 * WHERE THE SCRIPT WRITTEN FOR THIS BUSINESS HAS GOT TO.
 *
 * `POST /v1/agents` with a starter queues the whole script (`starter` proposal). While the
 * agent is an untouched draft the worker applies it at once and clears the proposal; after
 * any owner edit it waits as a suggestion (`ready`) instead. So:
 *
 * - `writing`: the proposal is `drafting`, or it has gone but the script read is still the
 *   one it was written over (the cached script predates the apply), so it is read again;
 * - `done`: the proposal is gone and the script is the written one;
 * - `ready`: written, waiting as a suggestion for the owner to review on the Script tab;
 * - `failed`: the job recorded a failure;
 * - `unread`: a read failed, said as a refusal rather than as any of the above.
 *
 * Mounted from the moment the agent is created, not when the Script step opens, so the
 * `drafting` proposal's `base_script` (the starter) is seen before the worker clears it.
 */
export type ScriptWriting =
  | { phase: "writing" }
  | { phase: "done"; script: CallScript }
  | { phase: "ready"; script: CallScript }
  | { phase: "failed"; note: string | null }
  | { phase: "unread"; error: Error; retry: () => void };

/** How often the reads are asked again while the proposal is gone but the apply unseen. */
const POLL_MS = 3000;

/** What decides "still the starter": its main task, its steps and its opening. */
function fingerprint(script: CallScript): string {
  return JSON.stringify([
    script.goal,
    script.stages.map((stage) => [stage.name, stage.instruction]),
    script.steps.map((step) => step.instruction),
    script.opening_line,
  ]);
}

export function useScriptWriting(session: Session, agentId: string): ScriptWriting {
  const proposal = useScriptProposal(session, agentId);
  const script = useScript(session, agentId);
  const [starter, setStarter] = useState<string | null>(null);

  const pending = proposal.data;
  if (pending?.status === "drafting" && starter === null) setStarter(fingerprint(pending.base_script));

  const shown = script.data ? (script.data.draft?.script ?? script.data.script) : null;
  const gone = pending === null;
  const applyUnseen = gone && shown !== null && starter !== null && fingerprint(shown) === starter;

  const refetchProposal = proposal.refetch;
  const refetchScript = script.refetch;
  // The proposal's own poll stops once it is gone; the script is then read until it moves.
  useEffect(() => {
    if (!gone) return;
    void refetchScript();
    if (!applyUnseen) return;
    const timer = setInterval(() => {
      void refetchProposal();
      void refetchScript();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [gone, applyUnseen, refetchProposal, refetchScript]);

  if (proposal.error || script.error) {
    const error = proposal.error ?? script.error ?? new Error("Couldn't read the script.");
    return {
      phase: "unread",
      error,
      retry: () => {
        void refetchProposal();
        void refetchScript();
      },
    };
  }
  if (pending === undefined || shown === null) return { phase: "writing" };
  if (pending === null) return applyUnseen ? { phase: "writing" } : { phase: "done", script: shown };
  if (pending.status === "drafting") return { phase: "writing" };
  if (pending.status === "failed") return { phase: "failed", note: pending.note };
  return pending.script ? { phase: "ready", script: pending.script } : { phase: "failed", note: pending.note };
}
