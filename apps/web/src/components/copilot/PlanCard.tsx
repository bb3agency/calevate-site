"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ListChecks, ShieldAlert } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProgressBar } from "@/components/interior/progress-bar";
import { NOTICE_BAR, ProblemNotice, SECONDARY_BUTTON, Skeleton, formatIST } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { confirmProposal } from "@/lib/api/copilot";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import {
  PLAN_TARGET_PAGE,
  countOf,
  estimateWords,
  isActive,
  planKeys,
  planStatusWords,
  refreshAfterPlan,
  approvePlan,
  refreshPlanById,
  useCancelPlan,
  usePlan,
  usePlanTargets,
  type CopilotPlanOut,
  type PlanStatus,
} from "@/lib/copilot/plans";
import { approveAction } from "@/lib/copilot/workspace";

/**
 * HOW THIS CARD'S APPROVE IS SENT. The same plan is approved three ways, and each keeps
 * the record its door keeps:
 *
 * - `proposal` — Pip's card in the panel: the signed token from the `proposal` frame goes
 *   to `POST /v1/copilot/confirm`, with the emailed code when the action needs one.
 * - `approval` — a plan a background task or routine staged: the Approvals inbox's own
 *   `POST /v1/copilot/approvals/{id}/approve`, so the inbox row is decided with it.
 * - `plan` — anywhere else (Tasks, a console screen): `POST /v1/copilot/plans/{id}/approve`
 *   with the hash the card was drawn from.
 */
export type PlanDecision =
  | { kind: "proposal"; token: string; confirmAction: string | null }
  | { kind: "approval"; actionId: string; confirmAction: string | null }
  | { kind: "plan" };

/** Plans that reach a caller: their Approve is the danger colour and arms late. */
const REACHES_CALLERS = new Set(["calls_place_bulk", "callbacks_book_bulk", "campaign_add_leads"]);

/** `ProposalCard`'s reason: a button that appears under a moving hand ignores it briefly. */
const ARM_MS = 400;

/**
 * THE PLAN CARD (D-893): one card, one click, for an action over many records.
 *
 * Every sentence on it is the server's — the title, why, who, the estimate's note, each
 * reason someone is left out, the result. The browser adds only the frame: the counts, the
 * status words, the buttons. The list of who is behind "See them", one page at a time,
 * because a plan can hold thousands and the card is read in a side panel on a phone.
 *
 * It is the same card in the Pip panel, the Approvals inbox, Tasks and under the Leads
 * table's bulk bar, so a plan reads the same wherever a person meets it.
 */
export function PlanCard({
  session,
  planId,
  decision = { kind: "plan" },
  onChange,
  onDismiss,
  onDecided,
}: {
  session: Session;
  planId: string;
  decision?: PlanDecision;
  /** "Change": put the request back in the ask box so the person can say it differently. */
  onChange?: () => void;
  /** Remove the card from wherever it is shown. */
  onDismiss?: () => void;
  /** Called once Approve or Cancel has an answer. */
  onDecided?: () => void;
}) {
  const plan = usePlan(session, planId);
  const client = useQueryClient();
  const data = plan.data;

  // The screens the plan's action touches are refreshed once, when it ends.
  const lastStatus = useRef<PlanStatus | undefined>(undefined);
  useEffect(() => {
    if (data === undefined) return;
    const was = lastStatus.current;
    lastStatus.current = data.status;
    if (was !== undefined && isActive(was) && !isActive(data.status)) {
      refreshAfterPlan(client, session.orgSlug, data);
    }
  }, [data, client, session.orgSlug]);

  if (plan.error != null && data === undefined) {
    return (
      <div className={`border-l-2 ${NOTICE_BAR.neutral} py-1 pl-3`}>
        <ProblemNotice error={plan.error} onRetry={() => void plan.refetch()} />
      </div>
    );
  }
  if (data === undefined) {
    return <Skeleton rows={3} label="Loading the plan…" />;
  }
  return (
    <PlanBody
      session={session}
      plan={data}
      decision={decision}
      onChange={onChange}
      onDismiss={onDismiss}
      onDecided={() => {
        void client.invalidateQueries({ queryKey: planKeys.plan(session.orgSlug, planId) });
        onDecided?.();
      }}
    />
  );
}

function PlanBody({
  session,
  plan,
  decision,
  onChange,
  onDismiss,
  onDecided,
}: {
  session: Session;
  plan: CopilotPlanOut;
  decision: PlanDecision;
  onChange?: () => void;
  onDismiss?: () => void;
  onDecided: () => void;
}) {
  const going = plan.target_count - plan.excluded_count;
  const consequential = REACHES_CALLERS.has(plan.tool);
  const [armed, setArmed] = useState(!consequential);
  useEffect(() => {
    if (armed) return;
    const timer = setTimeout(() => setArmed(true), ARM_MS);
    return () => clearTimeout(timer);
  }, [armed]);

  const approve = useApprove(session, decision);
  const approveFeedback = useActionFeedback(approve, { errorDisplay: "inline" });
  const cancel = useCancelPlan(session);
  const cancelFeedback = useActionFeedback(cancel, { errorDisplay: "inline" });
  // Once per card: the parent's callback is a new function each render, and calling it
  // again on every render after a success would re-read the plan in a loop.
  const told = useRef(false);
  useEffect(() => {
    if (told.current || !(approve.isSuccess || cancel.isSuccess)) return;
    told.current = true;
    onDecided();
  }, [approve.isSuccess, cancel.isSuccess, onDecided]);

  const proposed = plan.status === "proposed";
  const active = isActive(plan.status);
  const settled = plan.done_count + plan.skipped_count + plan.failed_count;

  return (
    <section
      aria-label={`Plan: ${plan.title}`}
      className={`border-l-2 ${NOTICE_BAR.neutral} space-y-2 py-1 pl-3`}
    >
      <p className="flex items-center gap-1.5 text-meta font-semibold text-ink-muted">
        {consequential && proposed ? (
          <ShieldAlert aria-hidden className="h-3.5 w-3.5" />
        ) : (
          <ListChecks aria-hidden className="h-3.5 w-3.5" />
        )}
        {proposed ? "Plan — nothing has happened yet" : planStatusWords(plan.status)}
      </p>
      <div>
        <p className="break-words text-xs font-medium text-ink [overflow-wrap:anywhere]">
          {plan.title}
        </p>
        <p className="mt-0.5 break-words text-xs text-ink-muted [overflow-wrap:anywhere]">
          {plan.why}
        </p>
      </div>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        <dt className="text-ink-faint">Who</dt>
        <dd className="min-w-0 break-words text-ink [overflow-wrap:anywhere]">
          {countOf(going, plan.target_type)} — {plan.who}
        </dd>
        <dt className="text-ink-faint">When</dt>
        <dd className="min-w-0 text-ink">
          {plan.run_at !== null
            ? formatIST(plan.run_at)
            : proposed
              ? "As soon as you approve"
              : plan.started_at !== null
                ? `Started ${formatIST(plan.started_at)}`
                : "Starting"}
        </dd>
        <dt className="text-ink-faint">Cost</dt>
        <dd className="min-w-0 break-words text-ink-muted [overflow-wrap:anywhere]">
          <span className="font-medium text-ink">{estimateWords(plan)}</span>
          {plan.estimate_note && plan.estimate_inr !== "0.00" ? ` · ${plan.estimate_note}` : ""}
        </dd>
        {plan.excluded_count > 0 && (
          <>
            <dt className="text-ink-faint">Left out</dt>
            <dd className="min-w-0 text-ink-muted">
              <span className="text-ink">{countOf(plan.excluded_count, plan.target_type)}</span>
              <ul className="mt-0.5 space-y-0.5">
                {plan.exclusions.map((exclusion) => (
                  <li key={exclusion.reason} className="break-words [overflow-wrap:anywhere]">
                    {exclusion.count.toLocaleString("en-IN")} — {exclusion.reason}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
      </dl>

      {active && (
        <ProgressBar
          value={settled}
          max={Math.max(plan.target_count, 1)}
          label={`${settled.toLocaleString("en-IN")} of ${plan.target_count.toLocaleString("en-IN")} done`}
          pendingLabel="Working"
          completeLabel="Finishing"
        />
      )}
      {!proposed && !active && plan.result !== null && (
        <p role="status" className="break-words text-xs text-ink [overflow-wrap:anywhere]">
          {plan.result}
        </p>
      )}
      {plan.campaign_id !== null && (
        <p className="text-xs text-ink-muted">The calls run as a campaign, under Campaigns.</p>
      )}

      <TargetList session={session} plan={plan} />

      {approve.error != null && <ProblemNotice error={approve.error} />}
      {cancel.error != null && <ProblemNotice error={cancel.error} />}

      {proposed && (
        <div className="flex flex-wrap gap-2 pt-1">
          <ActionButton
            status={approveFeedback.status}
            variant={consequential ? "danger" : "primary"}
            disabled={!armed || cancel.isPending}
            onClick={() => approveFeedback.run(plan)}
            aria-label={`Approve — ${plan.title}`}
            pendingLabel="Approving…"
            successLabel="Approved"
          >
            Approve
          </ActionButton>
          {onChange && (
            <button type="button" onClick={onChange} className={SECONDARY_BUTTON}>
              Change
            </button>
          )}
          <ActionButton
            variant="secondary"
            status={cancelFeedback.status}
            disabled={approve.isPending}
            onClick={() => cancelFeedback.run(plan.id)}
            aria-label={`Cancel — ${plan.title}`}
            pendingLabel="Cancelling…"
            successLabel="Cancelled"
          >
            Cancel
          </ActionButton>
        </div>
      )}
      {active && (
        <div className="flex flex-wrap gap-2 pt-1">
          <ActionButton
            variant="secondary-sm"
            status={cancelFeedback.status}
            onClick={() => cancelFeedback.run(plan.id)}
            aria-label={`Stop — ${plan.title}`}
            pendingLabel="Stopping…"
            successLabel="Stopped"
          >
            Stop
          </ActionButton>
        </div>
      )}
      {!proposed && !active && onDismiss && (
        <button type="button" onClick={onDismiss} className={SECONDARY_BUTTON}>
          Close
        </button>
      )}
      {plan.status === "expired" && (
        <p className="text-xs text-ink-muted">Ask {ASSISTANT_NAME} again to make a fresh plan.</p>
      )}
    </section>
  );
}

/** The approve mutation for this card's door (`PlanDecision`). Not retried: a second post
 * of an approval that landed is answered "already decided". */
function useApprove(session: Session, decision: PlanDecision) {
  const client = useQueryClient();
  return useMutation<unknown, unknown, CopilotPlanOut>({
    mutationFn: (plan) => {
      if (decision.kind === "proposal") {
        return confirmProposal(session, "client", decision.confirmAction, decision.token);
      }
      if (decision.kind === "approval") {
        return approveAction(session, decision.actionId, decision.confirmAction);
      }
      return approvePlan(session, plan);
    },
    onSuccess: (_result, plan) => {
      refreshPlanById(client, session.orgSlug, plan.id);
      if (decision.kind === "approval") {
        void client.invalidateQueries({ queryKey: ["copilot-approvals", session.orgSlug] });
        void client.invalidateQueries({ queryKey: ["copilot-actions", "client", session.orgSlug] });
      }
    },
  });
}

/** Who the plan is about, a page at a time, behind one button. */
function TargetList({ session, plan }: { session: Session; plan: CopilotPlanOut }) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const page = usePlanTargets(session, plan.id, offset, open);
  const listId = `plan-targets-${plan.id}`;
  const noun = countOf(plan.target_count, plan.target_type);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
        className="press inline-flex items-center gap-1 rounded-sm text-xs font-medium text-ink-muted underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        <ChevronDown
          aria-hidden
          className={`h-3.5 w-3.5 transition-transform duration-(--duration-fast) ease-out ${open ? "rotate-180" : ""}`}
        />
        {open ? "Hide the list" : `See all ${noun}`}
      </button>
      {open && (
        <div id={listId} className="mt-1.5">
          {page.error != null && (
            <ProblemNotice error={page.error} onRetry={() => void page.refetch()} />
          )}
          {page.data === undefined && page.error == null && (
            <Skeleton rows={3} label="Loading the list…" />
          )}
          {page.data !== undefined && (
            <>
              <ul className="divide-y divide-line border-y border-line text-xs">
                {page.data.targets.map((target) => (
                  <li key={target.target_id} className="flex min-w-0 flex-wrap items-baseline gap-x-2 py-1.5">
                    <span className="min-w-0 break-words font-medium text-ink [overflow-wrap:anywhere]">
                      {target.label ?? "No name"}
                    </span>
                    <span className="text-ink-muted">
                      {target.excluded
                        ? "Left out"
                        : TARGET_STATUS[target.status as keyof typeof TARGET_STATUS]}
                    </span>
                    {target.reason !== null && (
                      <span className="basis-full break-words text-ink-faint [overflow-wrap:anywhere]">
                        {target.reason}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                <span>
                  {offset + 1}–{Math.min(offset + PLAN_TARGET_PAGE, page.data.total)} of{" "}
                  {page.data.total.toLocaleString("en-IN")}
                </span>
                {offset > 0 && (
                  <button
                    type="button"
                    onClick={() => setOffset(Math.max(0, offset - PLAN_TARGET_PAGE))}
                    className="rounded-sm font-medium underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                  >
                    Previous
                  </button>
                )}
                {offset + PLAN_TARGET_PAGE < page.data.total && (
                  <button
                    type="button"
                    onClick={() => setOffset(offset + PLAN_TARGET_PAGE)}
                    className="rounded-sm font-medium underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                  >
                    Next
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const TARGET_STATUS = {
  pending: "Waiting",
  done: "Done",
  skipped: "Skipped",
  failed: "Could not be done",
} as const;
