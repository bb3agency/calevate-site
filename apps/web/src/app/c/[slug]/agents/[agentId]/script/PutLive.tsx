"use client";

/**
 * "PUT IT LIVE" — on the agent page's header, only while a version of the agent's script is
 * waiting to go live: one the admin console staged for a live agent (`write_prompt_version`'s
 * slow lane). It applies that version (`POST .../script/apply`) with the version the owner was
 * looking at, so a change made somewhere else in between is refused rather than overwritten.
 *
 * Owners do not edit an agent's script (D-1005, D-1017): what a call says is the script of
 * its Inbound line or campaign, put live on that page. An autosaved draft from before that is
 * never put live from here.
 */

import type { ReactNode } from "react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { ModalDialog } from "@/components/modalDialog";
import { ProblemNotice } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useApplyScript, type ScriptOut } from "@/lib/api/script";

export type PutLiveResult = { live: boolean };

export function usePutLive(session: Session, agentId: string) {
  const apply = useApplyScript(session, agentId);
  // The dialog shows a refusal beside its own button, and the screen says where it went live.
  const feedback = useActionFeedback(apply, { errorDisplay: "inline" });
  const run = (out: ScriptOut, onDone: (r: PutLiveResult) => void) => {
    apply.mutate(
      { expected_version: out.version },
      { onSuccess: (r) => onDone({ live: r.applied && r.engine_synced }) },
    );
  };
  return {
    run,
    pending: apply.isPending,
    status: feedback.status as FeedbackStatus,
    error: apply.error,
    reset: () => apply.reset(),
  };
}

export function PutLiveDialog({
  agentOn,
  voiceLine,
  pending,
  status,
  error,
  onCancel,
  onConfirm,
  promo,
}: {
  /** Whether the agent is switched on, so the consequence is said truly. */
  agentOn: boolean;
  /** The voice tier callers hear it in ("Clear voice · ₹2.50 / min"), when known. */
  voiceLine?: string | null;
  pending: boolean;
  /** The put-live action's state (`usePutLive().status`); `pending` alone is read as busy. */
  status?: FeedbackStatus;
  error: unknown;
  onCancel: () => void;
  onConfirm: () => void;
  /** The promo check's warning (D-943), shown above the buttons; never blocks them. */
  promo?: ReactNode;
}) {
  const shown: FeedbackStatus = status ?? (pending ? "pending" : "idle");
  return (
    <ModalDialog
      title="Put the waiting changes live?"
      onClose={onCancel}
      initialFocus="first-tabbable"
      description={
        <p>
          {agentOn
            ? "From the next call. Calls on now keep the old one."
            : "Callers hear it once you switch the agent on."}
        </p>
      }
      actions={
        <>
          {/* Held while Put it live works; that button carries the spinner. */}
          <ActionButton variant="secondary" onClick={onCancel} disabled={shown === "pending"}>
            Not yet
          </ActionButton>
          <ActionButton status={shown} pendingLabel="Putting it live…" successLabel="Live" onClick={onConfirm}>
            Put it live
          </ActionButton>
        </>
      }
    >
      {voiceLine && <p className="mt-2 text-meta text-ink-muted">Voice: {voiceLine}</p>}
      {promo && <div className="mt-3">{promo}</div>}
      {error != null && (
        <div className="mt-3">
          <ProblemNotice error={error} />
        </div>
      )}
    </ModalDialog>
  );
}
