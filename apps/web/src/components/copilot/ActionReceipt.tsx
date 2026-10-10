"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Undo2 } from "lucide-react";

import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useUndoAction } from "@/lib/api/copilot";
import type { CopilotAction } from "@/lib/copilot/types";

/**
 * What the assistant HAS ALREADY DONE — a receipt, never an offer.
 *
 * `ProposalCard` and this render two opposite promises and must not look alike: a proposal
 * is an offer with a Confirm button and nothing behind it yet; this is a record of a change
 * that has happened. The heading says "Done", not "Suggestion".
 *
 * ## The Undo (D-694)
 *
 * The server sends a receipt only for an action that is reversible, reaches no caller and
 * spends nothing, and since D-694 it carries `action_id` and `undoable_until`. While that
 * instant is ahead, the receipt offers Undo, which posts back to the action log; the server
 * checks nothing has changed the record since and either puts it back or says why it
 * could not. After the instant, or when `applied` is false, there is nothing to undo and
 * the button is not drawn. `reversal` is still shown in words, because it is also how to
 * take the change back by hand.
 */
export function ActionReceipt({
  action,
  session,
  realm,
}: {
  action: CopilotAction;
  session: Session;
  realm: "client" | "admin";
}) {
  const undo = useUndoAction(session, realm);
  const [open, setOpen] = useState(() => undoOpen(action));

  // One wake-up at the deadline, `ProposalCard`'s timer shape and its 32-bit ceiling.
  useEffect(() => {
    setOpen(undoOpen(action));
    if (action.undoable_until == null) return;
    const remaining = Date.parse(action.undoable_until) - Date.now();
    if (Number.isNaN(remaining) || remaining <= 0 || remaining > MAX_TIMEOUT_MS) return;
    const timer = setTimeout(() => setOpen(false), remaining);
    return () => clearTimeout(timer);
  }, [action]);

  const undone = undo.data;
  return (
    <div className="border-l-2 border-brand pl-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
        <CheckCircle2 aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
        {undone !== undefined ? "Undone" : action.applied ? "Done" : "Already done"}
      </p>
      <p className="mt-0.5 text-xs text-ink">{action.title}</p>
      <p className="mt-0.5 text-xs text-ink-muted">{undone?.detail ?? action.detail}</p>
      {undone === undefined && (
        <dl className="mt-1.5 space-y-1 text-xs">
          <div className="flex gap-1.5">
            <dt className="shrink-0 text-ink-faint">Where</dt>
            <dd className="text-ink-muted">{action.where}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="shrink-0 text-ink-faint">Undo</dt>
            <dd className="text-ink-muted">{action.reversal}</dd>
          </div>
        </dl>
      )}
      {undone === undefined && open && action.action_id != null && (
        <button
          type="button"
          onClick={() => undo.mutate(action.action_id as string)}
          disabled={undo.isPending}
          aria-label={`Undo — ${action.title}`}
          className={`${SECONDARY_BUTTON} mt-2 inline-flex items-center gap-1`}
        >
          <Undo2 aria-hidden className="h-3.5 w-3.5" />
          {undo.isPending ? "Undoing…" : "Undo"}
        </button>
      )}
      {undo.isError && (
        <div className="mt-2">
          <ProblemNotice error={undo.error} />
        </div>
      )}
    </div>
  );
}

/** `setTimeout` stores its delay in a signed 32-bit int; longer wraps to "now". */
const MAX_TIMEOUT_MS = 2_147_483_647;

function undoOpen(action: CopilotAction): boolean {
  if (!action.applied || action.action_id == null || action.undoable_until == null) return false;
  const until = Date.parse(action.undoable_until);
  return !Number.isNaN(until) && until > Date.now();
}
