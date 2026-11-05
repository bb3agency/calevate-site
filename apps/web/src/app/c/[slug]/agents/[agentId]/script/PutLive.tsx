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

import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

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
  scriptKeys,
  useApplyScript,
  useClearProposal,
  useFixScriptLines,
  useKeepFixedScript,
  usePublishScript,
  useSaveDraft,
  useScript,
  useScriptCheck,
  useScriptProposal,
  type CallScript,
  type ScriptOut,
  type ScriptProposal,
} from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";

import { changeSummary, diffScripts, type Change } from "./scriptDiff";
import { sameScript } from "./scriptDraft";
import { sectionReadable } from "./scriptModel";

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
 * `/script/fix-lines`, and a suggestion that may change only those lines is written in the
 * background. Once it is ready the owner sees each line before and after and chooses: the
 * fix goes into the draft only on "Use these fixes" (A-02), with an Undo after. A fix that
 * changed nothing says so (A-15). A script written as one text is not sent: the writer works
 * on steps and would replace it (A-01).
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
  const queryClient = useQueryClient();
  const check = useScriptCheck(session, agentId, draft);
  const stored = useScript(session, agentId);
  const fix = useFixScriptLines(session, agentId);
  const keep = useKeepFixedScript(session, agentId);
  const clear = useClearProposal(session, agentId);
  const putBack = useSaveDraft(session, agentId);
  const fixFeedback = useActionFeedback(fix, { errorDisplay: "inline" });
  useActionFeedback(keep, { errorDisplay: "inline" });
  const [fixing, setFixing] = useState<{ id: string; savedAt: string } | null>(null);
  const [review, setReview] = useState<{ proposal: ScriptProposal; savedAt: string } | null>(null);
  const [undo, setUndo] = useState<{ script: CallScript; savedAt: string } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const settle = useCallback(
    (proposal: ScriptProposal) => {
      const savedAt = fixing?.savedAt ?? "";
      setFixing(null);
      const outcome = fixOutcome(proposal);
      if (outcome.kind === "review") {
        setReview({ proposal, savedAt });
        return;
      }
      if (outcome.kind === "nothing") clear.mutate(proposal.id);
      setFailed(outcome.message);
    },
    [fixing, clear],
  );

  const busy = fixing !== null || fix.isPending || keep.isPending || review !== null;
  useEffect(() => onBusy(busy), [busy, onBusy]);

  if (review) {
    const { proposal, savedAt } = review;
    const fixed = proposal.script as CallScript;
    return (
      <FixReview
        before={proposal.base_script}
        after={fixed}
        pending={keep.isPending}
        error={keep.error}
        onUse={() =>
          keep.mutate(
            { proposalId: proposal.id, script: fixed, baseSavedAt: savedAt },
            {
              onSuccess: (saved) => {
                setReview(null);
                setUndo({ script: proposal.base_script, savedAt: saved.saved_at });
                onFixed?.(fixed);
              },
            },
          )
        }
        onDiscard={() => {
          clear.mutate(proposal.id);
          setReview(null);
        }}
      />
    );
  }

  // The way back from a fix the owner used, wherever the dialog was opened (A-26).
  const undoRow = undo && (
    <div role="status" className="mt-3 flex flex-wrap items-center gap-3 text-meta text-ink-muted">
      <p>Pip fixed those lines in your draft.</p>
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={putBack.isPending}
        onClick={() =>
          putBack.mutate(
            { script: undo.script, base_saved_at: undo.savedAt },
            {
              onSuccess: () => {
                const script = undo.script;
                setUndo(null);
                onFixed?.(script);
                void queryClient.invalidateQueries({ queryKey: scriptKeys.one(session.orgSlug, agentId) });
              },
            },
          )
        }
      >
        {putBack.isPending ? "Undoing…" : "Undo"}
      </button>
      {putBack.error && <ProblemNotice error={putBack.error} />}
    </div>
  );

  if (check.isPending) return undoRow || null;
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
  if (warnings.length === 0) return undoRow || null;
  const lines = warnings.length === 1 ? "1 line" : `${warnings.length} lines`;
  const handWritten = draft.raw_override !== null && draft.raw_override !== undefined;

  if (busy) {
    return (
      <>
        {fixing !== null && (
          <FixWatcher agentId={agentId} proposalId={fixing.id} onSettled={settle} />
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
    <>
    {undoRow}
    <div role="status" className="mt-3 rounded-md bg-warn-soft px-3 py-2">
      <p className="text-body text-ink">{lines} to fix first</p>
      {handWritten && <p className="text-meta text-ink-muted">Edit them in your text before it goes live.</p>}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {!handWritten && (
          <ActionButton
            status={fixFeedback.status}
            pendingLabel="Fixing…"
            variant="secondary"
            onClick={() => {
              setFailed(null);
              setUndo(null);
              fix.mutate(
                { script: draft, baseSavedAt: stored.data ? (stored.data.draft?.saved_at ?? null) : undefined },
                { onSuccess: (asked) => setFixing({ id: asked.id, savedAt: asked.draft_saved_at }) },
              );
            }}
          >
            {warnings.length === 1 ? "Fix it first" : "Fix them first"}
          </ActionButton>
        )}
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
    </>
  );
}

/**
 * What a finished fix leads to: the owner's review, or a plain line saying why there is
 * nothing to review. A fix that changed nothing is said as such, never as a silent repeat
 * of the same warning (A-15).
 */
export function fixOutcome(
  proposal: ScriptProposal,
): { kind: "review" } | { kind: "nothing" | "failed"; message: string } {
  if (proposal.status !== "ready" || !proposal.script) {
    return { kind: "failed", message: proposal.note ?? "Pip could not fix these lines this time." };
  }
  if (diffScripts(proposal.base_script, proposal.script).length === 0) {
    return { kind: "nothing", message: "Pip could not fix these. Edit them, or put it live anyway." };
  }
  return { kind: "review" };
}

/**
 * The fix Pip wrote, each line before and after, for the owner to use or not (A-02). The
 * server already kept every line the check did not name; this is where the owner sees the
 * ones it did.
 */
export function FixReview({
  before,
  after,
  pending,
  error,
  onUse,
  onDiscard,
}: {
  before: CallScript;
  after: CallScript;
  pending: boolean;
  error: unknown;
  onUse: () => void;
  onDiscard: () => void;
}) {
  const changes = diffScripts(before, after);
  return (
    <div role="status" className="mt-3 rounded-md bg-info-soft px-3 py-3">
      <p className="text-body font-medium text-ink">
        {changes.length === 1 ? "Pip's fix for 1 line" : `Pip's fix for ${changes.length} lines`}
      </p>
      <ul className="mt-2 space-y-3">
        {changes.map((change) => {
          const [was, now] = changeTexts(change);
          return (
            <li key={change.id} className="min-w-0">
              <p className="text-meta text-ink-muted">{change.label}</p>
              {was && (
                <p className="break-words text-body text-ink-muted line-through decoration-ink-muted/50">{was}</p>
              )}
              <p className="break-words text-body text-ink">{now || "(left empty)"}</p>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={pending} onClick={onUse}>
          {pending ? "Using them…" : "Use these fixes"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={pending} onClick={onDiscard}>
          Keep my lines
        </button>
      </div>
      {Boolean(error) && (
        <div className="mt-2">
          <ProblemNotice error={error} />
        </div>
      )}
    </div>
  );
}

function changeTexts(change: Change): [string, string] {
  switch (change.kind) {
    case "part":
      return [change.before, change.after];
    case "section-changed":
      return [sectionReadable(change.before), sectionReadable(change.after)];
    case "section-added":
      return ["", sectionReadable(change.after)];
    case "section-removed":
      return [sectionReadable(change.before), ""];
  }
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
  // The note follows the draft (a fix or its Undo changes it) until the owner types their
  // own (A-26).
  const typed = useRef(false);
  const suggested = changeSummary(live, draft);
  useEffect(() => {
    if (!typed.current) setSummary(suggested);
  }, [suggested]);
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
          onChange={(e) => {
            typed.current = true;
            setSummary(e.target.value);
          }}
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
