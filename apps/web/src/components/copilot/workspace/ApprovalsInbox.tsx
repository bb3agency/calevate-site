"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { useToast } from "@/components/interior/toaster";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatIST,
} from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  useApprovalPreview,
  useApproveAction,
  useCopilotApprovals,
  useRejectAction,
  type CopilotActionOut,
} from "@/lib/copilot/workspace";

/**
 * THE APPROVALS INBOX: the steps a background task or a routine reached that call someone,
 * spend money or cannot be undone, waiting for a person (D-694).
 *
 * Nothing here runs on its own. Opening a row asks the server what approving would do NOW
 * (the planner re-run against today's records), so the person reads what changes, the cost
 * and whether it can be taken back before the button that does it — and Approve is offered
 * only while that reading says the step still applies.
 */
export function ApprovalsInbox({ session }: { session: Session }) {
  const approvals = useCopilotApprovals(session);
  const rows = approvals.data?.actions ?? [];

  if (approvals.error != null) {
    return <ProblemNotice error={approvals.error} onRetry={() => void approvals.refetch()} />;
  }
  if (approvals.data === undefined) return <Skeleton rows={3} label="Loading approvals…" />;
  if (rows.length === 0) {
    return (
      <EmptyState
        message="Nothing is waiting for you."
        hint="When a task or routine needs to call someone, spend money or make a change that can't be undone, it waits here."
      />
    );
  }
  return (
    <ul className="space-y-3" aria-label="Waiting for your approval">
      {rows.map((row) => (
        <ApprovalRow key={row.id} session={session} row={row} />
      ))}
    </ul>
  );
}

function ApprovalRow({ session, row }: { session: Session; row: CopilotActionOut }) {
  const [open, setOpen] = useState(false);
  const preview = useApprovalPreview(session, open ? row.id : null);
  const approve = useApproveAction(session);
  const reject = useRejectAction(session);
  const { toast } = useToast();
  const detailsId = `approval-${row.id}`;
  const ready = preview.data !== undefined && preview.data.still_applies;
  const busy = approve.isPending || reject.isPending;

  return (
    <li className="rounded-card border border-line bg-surface">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen((value) => !value)}
        className="press flex w-full min-w-0 items-start gap-3 rounded-card px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <span className="min-w-0 flex-1">
          <span className="block break-words text-sm font-medium text-ink [overflow-wrap:anywhere]">
            {row.summary ?? "A change waiting for you"}
          </span>
          <span className="mt-0.5 block text-xs text-ink-muted">
            Asked {formatIST(row.created_at)}
            {row.job_id !== null ? " · from a background task" : ""}
          </span>
        </span>
        <ChevronDown
          aria-hidden
          className={`mt-0.5 h-4 w-4 shrink-0 text-ink-faint transition-transform duration-(--duration-fast) ease-out ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div id={detailsId} className="space-y-3 border-t border-line px-4 py-3">
          {preview.error != null && (
            <ProblemNotice error={preview.error} onRetry={() => void preview.refetch()} />
          )}
          {preview.data === undefined && preview.error == null && (
            <Skeleton rows={3} label="Checking what this would change…" />
          )}
          {preview.data !== undefined && (
            <>
              <p className="text-sm font-medium text-ink">{preview.data.title}</p>
              {preview.data.still_applies ? (
                <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
                  <dt className="text-ink-faint">What changes</dt>
                  <dd className="min-w-0 break-words text-ink [overflow-wrap:anywhere]">
                    {preview.data.summary}
                  </dd>
                  {preview.data.current != null && (
                    <>
                      <dt className="text-ink-faint">Now</dt>
                      <dd className="min-w-0 break-words text-ink-muted">{preview.data.current}</dd>
                    </>
                  )}
                  {preview.data.proposed != null && (
                    <>
                      <dt className="text-ink-faint">After</dt>
                      <dd className="min-w-0 break-words text-ink">{preview.data.proposed}</dd>
                    </>
                  )}
                  <dt className="text-ink-faint">Cost</dt>
                  <dd className="min-w-0 text-ink">{preview.data.cost ?? "Nothing"}</dd>
                  <dt className="text-ink-faint">Can it be undone?</dt>
                  <dd className="min-w-0 break-words text-ink">{preview.data.reversal}</dd>
                  <dt className="text-ink-faint">Decide by</dt>
                  <dd className="min-w-0 text-ink-muted">{formatIST(preview.data.expires_at)}</dd>
                </dl>
              ) : (
                <p className="text-sm text-ink-muted">{preview.data.refusal}</p>
              )}
            </>
          )}
          {approve.error != null && <ProblemNotice error={approve.error} />}
          {reject.error != null && <ProblemNotice error={reject.error} />}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!ready || busy}
              onClick={() =>
                approve.mutate(row.id, {
                  onSuccess: (result) =>
                    toast({
                      tone: result.applied ? "success" : "info",
                      title: result.applied ? "Approved and done" : "Nothing to do",
                      description: result.detail,
                    }),
                })
              }
              className={PRIMARY_BUTTON}
            >
              {approve.isPending ? "Approving…" : "Approve"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                reject.mutate(row.id, {
                  onSuccess: () => toast({ tone: "info", title: "Declined. Nothing was changed." }),
                })
              }
              className={SECONDARY_BUTTON}
            >
              {reject.isPending ? "Declining…" : "Decline"}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
