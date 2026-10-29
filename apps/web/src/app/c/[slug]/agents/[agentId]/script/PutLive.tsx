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

import Link from "next/link";
import { useState, type MouseEvent, type ReactNode } from "react";

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
import { useApplyScript, usePublishScript, useScriptCheck, type CallScript, type ScriptOut } from "@/lib/api/script";
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
 * What the script lint found in the draft (D-945), before it goes live: a count and one
 * button back to the script, the lines behind "Why?". A warning, never a block. Offers and
 * urgency are not among them: `promo` (the D-943 check) is the dialog's one promotional
 * warning, and `/script/check` leaves that wording to it.
 */
function ScriptWarnings({
  agentId,
  draft,
  onFix,
  scriptLink,
}: {
  agentId: string;
  draft: CallScript;
  onFix: () => void;
  scriptLink?: ScriptLink;
}) {
  const session = useClientSession();
  const check = useScriptCheck(session, agentId, draft);
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
  const fixLabel = warnings.length === 1 ? "Fix it first" : "Fix them first";
  return (
    <div role="status" className="mt-3 rounded-md bg-warn-soft px-3 py-2">
      <p className="text-body text-ink">
        {warnings.length === 1 ? "1 line to fix first" : `${warnings.length} lines to fix first`}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {/* Off the Script tab (the header's Put it live), closing the dialog alone would
            leave the owner on a tab with no script to fix, so it opens the Script tab. */}
        {scriptLink ? (
          <Link
            href={scriptLink.href}
            scroll={false}
            className={SECONDARY_BUTTON}
            onClick={(event) => {
              scriptLink.onClick?.(event);
              onFix();
            }}
          >
            {fixLabel}
          </Link>
        ) : (
          <button type="button" className={SECONDARY_BUTTON} onClick={onFix}>
            {fixLabel}
          </button>
        )}
        <Why inline className="text-meta text-ink-muted">
          {warnings.join(" ")}
        </Why>
      </div>
    </div>
  );
}

/** Where the Script tab is, from a dialog opened on another tab (`useSectionLink("script")`). */
export type ScriptLink = { href: string; onClick?: (event: MouseEvent<HTMLAnchorElement>) => void };

export function PutLiveDialog({
  agentId,
  scriptLink,
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
  /** Set when the dialog is opened away from the Script tab: "Fix it first" goes there. */
  scriptLink?: ScriptLink;
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
      {promo && <div className="mt-3">{promo}</div>}
      {agentId && <ScriptWarnings agentId={agentId} draft={draft} onFix={onCancel} scriptLink={scriptLink} />}
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
