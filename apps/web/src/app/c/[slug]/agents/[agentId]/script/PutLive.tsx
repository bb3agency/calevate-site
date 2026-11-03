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

import { Loader2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { ModalDialog } from "@/components/modalDialog";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { Why } from "@/components/why";
import {
  useApplyScript,
  useFixScriptLines,
  useKeepFixedScript,
  usePublishScript,
  useScriptCheck,
  useScriptProposal,
  type CallScript,
  type ScriptOut,
  type ScriptProposal,
} from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";

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

/**
 * What the script lint found in the draft (D-945), before it goes live: a count, "Fix them
 * first" and the lines behind "Why?". A warning, never a block. Offers and urgency are not
 * among them: `promo` (the D-943 check) is the dialog's one promotional warning, and
 * `/script/check` leaves that wording to it.
 *
 * "Fix them first" fixes them here (founder, 3 Nov 2026): the draft on screen is sent to
 * `/script/fix-lines`, a suggestion that fixes exactly those lines is written in the
 * background, and once it is ready it becomes the draft and the check runs again. While it
 * is being written the block says so and the dialog's own button waits.
 */
function ScriptWarnings({
  agentId,
  draft,
  onFixed,
  onBusy,
}: {
  agentId: string;
  draft: CallScript;
  onFixed?: (script: CallScript) => void;
  onBusy: (busy: boolean) => void;
}) {
  const session = useClientSession();
  const check = useScriptCheck(session, agentId, draft);
  const fix = useFixScriptLines(session, agentId);
  const keep = useKeepFixedScript(session, agentId);
  const fixFeedback = useActionFeedback(fix, { errorDisplay: "inline" });
  useActionFeedback(keep, { errorDisplay: "inline" });
  const [fixing, setFixing] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const settle = (proposal: ScriptProposal) => {
    setFixing(null);
    if (proposal.status === "ready" && proposal.script) {
      const script = proposal.script;
      keep.mutate({ proposalId: proposal.id, script }, { onSuccess: () => onFixed?.(script) });
    } else {
      setFailed(proposal.note ?? "Pip could not fix these lines this time.");
    }
  };

  const busy = fixing !== null || fix.isPending || keep.isPending;
  useEffect(() => onBusy(busy), [busy, onBusy]);

  if (check.isPending) return null;
  if (check.isError) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-3 text-meta text-ink-muted">
        <p>We could not check its lines this time.</p>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => void check.refetch()}>
          Try again
        </button>
      </div>
    );
  }
  const { warnings } = check.data;
  if (warnings.length === 0) return null;
  const lines = warnings.length === 1 ? "1 line" : `${warnings.length} lines`;

  if (busy) {
    return (
      <>
        {fixing !== null && (
          <FixWatcher agentId={agentId} proposalId={fixing} onSettled={settle} />
        )}
      <div role="status" aria-live="polite" className="mt-3 flex items-start gap-3 rounded-md bg-info-soft px-3 py-3">
        <Loader2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-info" />
        <div>
          <p className="text-body text-ink">Fixing {lines}…</p>
          <p className="text-meta text-ink-muted">Pip rewrites only those lines. A few seconds.</p>
        </div>
      </div>
      </>
    );
  }
  return (
    <div role="status" className="mt-3 rounded-md bg-warn-soft px-3 py-2">
      <p className="text-body text-ink">{lines} to fix first</p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <ActionButton
          status={fixFeedback.status}
          pendingLabel="Fixing…"
          variant="secondary"
          onClick={() => {
            setFailed(null);
            fix.mutate(draft, { onSuccess: (asked) => setFixing(asked.id) });
          }}
        >
          {warnings.length === 1 ? "Fix it first" : "Fix them first"}
        </ActionButton>
        <Why inline className="text-meta text-ink-muted">
          {warnings.join(" ")}
        </Why>
      </div>
      {failed && <p className="mt-2 text-meta text-danger">{failed}</p>}
      {fix.error && (
        <div className="mt-2">
          <ProblemNotice error={fix.error} />
        </div>
      )}
      {keep.error && (
        <div className="mt-2">
          <ProblemNotice error={keep.error} />
        </div>
      )}
    </div>
  );
}

/** Follows the fix being written and hands it over once it is ready or failed. Mounted only
 * while a fix is under way, so the dialog reads no suggestion otherwise. */
function FixWatcher({
  agentId,
  proposalId,
  onSettled,
}: {
  agentId: string;
  proposalId: string;
  onSettled: (proposal: ScriptProposal) => void;
}) {
  const proposal = useScriptProposal(useClientSession(), agentId).data;
  const settled = proposal && proposal.id === proposalId && proposal.status !== "drafting" ? proposal : null;
  useEffect(() => {
    if (settled) onSettled(settled);
  }, [settled, onSettled]);
  return null;
}

export function PutLiveDialog({
  agentId,
  onFixed,
  live,
  draft,
  agentOn,
  voiceLine,
  pending,
  status,
  error,
  onCancel,
  onConfirm,
  promo,
}: {
  /** The agent, so the draft's lines are checked before it goes live (D-945). */
  agentId?: string;
  /** Takes the fixed script into the editor, where there is one ("Fix them first"). */
  onFixed?: (script: CallScript) => void;
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
  /** The promo check's warning (D-943), shown above the note; never blocks the button. */
  promo?: ReactNode;
}) {
  const [summary, setSummary] = useState(() => changeSummary(live, draft));
  const shown: FeedbackStatus = status ?? (pending ? "pending" : "idle");
  const [fixing, setFixing] = useState(false);
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
            disabled={summary.trim() === "" || fixing}
            onClick={() => onConfirm(summary)}
          >
            Put it live
          </ActionButton>
        </>
      }
    >
      {voiceLine && <p className="mt-2 text-meta text-ink-muted">Voice: {voiceLine}</p>}
      {promo && <div className="mt-3">{promo}</div>}
      {agentId && <ScriptWarnings agentId={agentId} draft={draft} onFixed={onFixed} onBusy={setFixing} />}
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
