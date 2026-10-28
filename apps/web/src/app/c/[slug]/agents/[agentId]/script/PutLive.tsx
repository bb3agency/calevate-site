"use client";

/**
 * "PUT IT LIVE" — the one step between the draft and callers, used by the builder and by
 * the agent page's header so both mean exactly the same thing.
 *
 * One request (`POST .../script/publish`) makes the draft a history entry with the
 * owner's note and applies it. A change saved the older way and still waiting is applied
 * instead (`POST .../script/apply`). Both carry the version the owner was looking at, so a
 * change made somewhere else in between is refused rather than overwritten.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { ModalDialog } from "@/components/modalDialog";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON,
} from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useApplyScript, usePublishScript, type CallScript, type ScriptOut } from "@/lib/api/script";

import { changeSummary } from "./scriptDiff";
import { sameScript } from "./scriptDraft";

export type PutLiveResult = { live: boolean };

export function usePutLive(session: Session, agentId: string) {
  const publish = usePublishScript(session, agentId);
  const apply = useApplyScript(session, agentId);
  // The dialog shows a refusal beside its own button, and the screen says where it went live.
  const publishFeedback = useActionFeedback(publish, { errorDisplay: "inline" });
  const applyFeedback = useActionFeedback(apply, { errorDisplay: "inline" });
  const run = (out: ScriptOut, local: CallScript, summary: string, onDone: (r: PutLiveResult) => void) => {
    const onlyWaiting = out.version !== null && out.has_pending && sameScript(local, out.script);
    if (onlyWaiting) {
      apply.mutate(
        { expected_version: out.version },
        { onSuccess: (r) => onDone({ live: r.applied && r.engine_synced }) },
      );
      return;
    }
    publish.mutate(
      { summary: summary.trim().slice(0, 200) || "Put the script live", script: local, expected_version: out.version },
      { onSuccess: (r) => onDone({ live: r.live }) },
    );
  };
  return {
    run,
    pending: publish.isPending || apply.isPending,
    /** Whichever of the two ran last (a cancel resets both). */
    status: (applyFeedback.status !== "idle" ? applyFeedback.status : publishFeedback.status) as FeedbackStatus,
    error: publish.error ?? apply.error,
    reset: () => {
      publish.reset();
      apply.reset();
    },
  };
}

export function PutLiveDialog({
  live,
  draft,
  agentOn,
  voiceLine,
  pending,
  status,
  error,
  onCancel,
  onConfirm,
}: {
  /** What callers hear now (the saved script). */
  live: CallScript;
  draft: CallScript;
  /** Whether the agent is switched on, so the consequence is said truly. */
  agentOn: boolean;
  /** The voice tier callers hear it in ("Clear voice · ₹2.50 / min"), when known. */
  voiceLine?: string | null;
  pending: boolean;
  /** The put-live action's state (`usePutLive().status`); `pending` alone is read as busy. */
  status?: FeedbackStatus;
  error: unknown;
  onCancel: () => void;
  onConfirm: (summary: string) => void;
}) {
  const [summary, setSummary] = useState(() => changeSummary(live, draft));
  const shown: FeedbackStatus = status ?? (pending ? "pending" : "idle");
  return (
    <ModalDialog
      title="Put these changes live?"
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
          <button type="button" className={SECONDARY_BUTTON} onClick={onCancel} disabled={pending}>
            Not yet
          </button>
          <ActionButton
            status={shown}
            pendingLabel="Putting it live…"
            successLabel="Live"
            disabled={summary.trim() === ""}
            onClick={() => onConfirm(summary)}
          >
            Put it live
          </ActionButton>
        </>
      }
    >
      {voiceLine && <p className="mt-2 text-meta text-ink-muted">Voice: {voiceLine}</p>}
      <div className="mt-4">
        <label className={FIELD_LABEL} htmlFor="put-live-summary">
          What changed
        </label>
        <span className={FIELD_HINT}>A short note for History, so you can find this later.</span>
        <input
          id="put-live-summary"
          className={FIELD}
          value={summary}
          maxLength={200}
          onChange={(e) => setSummary(e.target.value)}
        />
      </div>
      {error != null && (
        <div className="mt-3">
          <ProblemNotice error={error} />
        </div>
      )}
    </ModalDialog>
  );
}
