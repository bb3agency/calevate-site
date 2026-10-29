"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useId, useState, type ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { ConfirmDialog } from "@/components/confirmDialog";
import { TypedConfirmation } from "@/components/typedConfirmation";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { FIELD_INLINE, FIELD_LABEL, NoticeBox, ProblemNotice, formatCount } from "@/components/ui";
import { ApiProblem, type Session } from "@/lib/api/client";
import {
  FOLLOW_UP_START_MAX,
  useFollowUps,
  useStartFollowUp,
  type FollowUpStartOut,
  type FollowUpSummaryOut,
} from "@/lib/api/followUps";
import type { LeadLens } from "@/lib/api/leads";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { TYPED_CONFIRMATION_FROM, type BulkSelection } from "./BulkActionBar";

/** The query parameter a Follow-up's "Start for leads" arrives with. */
export const START_FOLLOW_UP_PARAM = "follow_up";

/**
 * "Start a Follow-up" for the leads the table has selected (D-940): the same shape as
 * `AddToCampaign`, beside it rather than inside the bulk bar, because it starts something
 * that runs on each lead rather than changing a field. Only a Follow-up that is ON and is
 * started by hand is offered; the others start themselves.
 *
 * The scope is the bulk bar's: ticked rows go as `lead_ids`, every matching lead goes as
 * the table's lens with the count the person confirmed. More than one request takes comes
 * back as a plan, drawn with its own card.
 */
interface StartFollowUpProps {
  session: Session;
  slug: string;
  href: (path: string) => string;
  selection: BulkSelection;
  lens: LeadLens;
  filteredTotal: number | undefined;
  /** `leads:dispatch`. */
  canStart: boolean;
  startReason: string | null;
  renderPlan: (planId: string, onDismiss: () => void) => ReactNode;
  onStarted: () => void;
}

type Started = { followUp: FollowUpSummaryOut; result: FollowUpStartOut };

export function StartFollowUp(props: StartFollowUpProps) {
  const [result, setResult] = useState<Started | null>(null);
  const params = useSearchParams();
  const preselected = params.get(START_FOLLOW_UP_PARAM);
  const active = props.selection.wholeQuery || props.selection.ids.length > 0;
  return (
    <>
      {result && (
        <StartedNotice
          {...result}
          slug={props.slug}
          href={props.href}
          renderPlan={props.renderPlan}
          onDismiss={() => setResult(null)}
        />
      )}
      {!active && preselected && !result && (
        <NoticeBox tone="neutral" role="status">
          Tick the leads to start the Follow-up for.
        </NoticeBox>
      )}
      {/* Mounted only with a selection, so the Leads page reads no Follow-ups until then. */}
      {active && <Chooser {...props} preselected={preselected} onResult={setResult} />}
    </>
  );
}

function Chooser({
  session,
  slug,
  href,
  selection,
  lens,
  filteredTotal,
  canStart,
  startReason,
  onStarted,
  preselected,
  onResult,
}: StartFollowUpProps & { preselected: string | null; onResult: (started: Started) => void }) {
  const followUps = useFollowUps(session);
  const start = useStartFollowUp(session);
  const feedback = useActionFeedback(start, { errorDisplay: "inline" });
  const [chosenId, setChosenId] = useState(preselected ?? "");
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const selectId = useId();

  const resetStart = start.reset;
  useEffect(() => {
    setConfirming(false);
    setTyped("");
    resetStart();
  }, [selection, resetStart]);

  const startable = followUps.data
    ? followUps.data.items.filter((item) => item.status === "live" && item.trigger.kind === "manual")
    : [];
  const chosen = startable.find((item) => item.id === chosenId) ?? startable[0];
  const count = selection.wholeQuery ? filteredTotal : selection.ids.length;
  const needsTyping = count !== undefined && count >= TYPED_CONFIRMATION_FROM;
  const armed = count !== undefined && (!needsTyping || typed.trim() === String(count));
  const noun = count === 1 ? "lead" : "leads";

  // More than the server starts at once (422 `follow_up_start_too_many`): said before
  // anyone confirms when the count is known, and again if the server says it anyway.
  const tooMany = (count !== undefined && count > FOLLOW_UP_START_MAX) || isTooMany(start.error);

  const run = () => {
    if (!chosen || count === undefined) return;
    start.mutate(
      selection.wholeQuery
        ? { followUpId: chosen.id, lens, expectedCount: count }
        : { followUpId: chosen.id, leadIds: selection.ids },
      {
        onSuccess: (result) => {
          onResult({ followUp: chosen, result });
          setConfirming(false);
          onStarted();
        },
        // Too many is answered beside the button, with Pip's offer, not inside the dialog.
        onError: (error) => {
          if (isTooMany(error)) setConfirming(false);
        },
      },
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <label htmlFor={selectId} className={FIELD_LABEL}>
            Start a Follow-up
          </label>
          {followUps.isLoading ? (
            <select id={selectId} disabled className={`${FIELD_INLINE} mt-1 w-full touch:min-h-11`}>
              <option>Loading your Follow-ups…</option>
            </select>
          ) : followUps.error || !followUps.data ? null : startable.length === 0 ? (
            <p className="mt-1 text-body text-ink-muted">
              None you start by hand is on.{" "}
              <Link href={href(`/c/${slug}/follow-ups`)} className={TEXT_ACTION}>
                See Follow-ups
              </Link>
            </p>
          ) : (
            <select
              id={selectId}
              value={chosen?.id ?? ""}
              onChange={(event) => setChosenId(event.target.value)}
              className={`${FIELD_INLINE} mt-1 w-full touch:min-h-11`}
            >
              {startable.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          )}
        </div>
        {startable.length > 0 && !tooMany && (
          <ActionButton
            variant="secondary-sm"
            disabled={!canStart || count === undefined || !chosen}
            title={startReason ?? undefined}
            onClick={() => setConfirming(true)}
          >
            {count === undefined ? "Start for these leads" : `Start for ${formatCount(count)} ${noun}`}
          </ActionButton>
        )}
      </div>
      {followUps.error != null && <ProblemNotice error={followUps.error} onRetry={() => followUps.refetch()} />}
      {tooMany && chosen && (
        <NoticeBox
          tone="neutral"
          role="status"
          action={
            canStart ? (
              <AskAssistant
                label={`Ask ${ASSISTANT_NAME} to start them`}
                prompt={`Start my Follow-up “${chosen.name}” for ${
                  selection.wholeQuery ? "every lead my Leads filter matches" : "the leads I ticked"
                }${count !== undefined ? ` (${count} leads)` : ""}.`}
              />
            ) : undefined
          }
        >
          {`Up to ${FOLLOW_UP_START_MAX} leads start here at once.`}
        </NoticeBox>
      )}

      {confirming && chosen && count !== undefined ? (
        <ConfirmDialog
          title={`Start “${chosen.name}” for ${formatCount(count)} ${noun}?`}
          confirmLabel={`Start for ${formatCount(count)}`}
          pendingLabel="Starting…"
          status={feedback.status}
          confirmDisabled={!armed}
          error={start.error}
          onCancel={() => setConfirming(false)}
          onConfirm={run}
        >
          <p className="font-medium text-ink">
            {selection.wholeQuery ? "Every matching lead, not just this page." : "The leads you ticked."}
          </p>
          <p>Calls keep to your calling hours.</p>
          <p>Leads already in it are skipped.</p>
          {needsTyping && (
            <TypedConfirmation phrase={String(count)} value={typed} onChange={setTyped} inputMode="numeric" />
          )}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function isTooMany(error: unknown): boolean {
  return error instanceof ApiProblem && error.code === "follow_up_start_too_many";
}

function StartedNotice({
  followUp,
  result,
  slug,
  href,
  renderPlan,
  onDismiss,
}: Started & {
  slug: string;
  href: (path: string) => string;
  renderPlan: (planId: string, onDismiss: () => void) => ReactNode;
  onDismiss: () => void;
}) {
  if (result.plan_id) return <div className="mt-1">{renderPlan(result.plan_id, onDismiss)}</div>;
  return (
    <NoticeBox
      tone={result.started > 0 ? "ok" : "warn"}
      role="status"
      action={
        <span className="flex flex-wrap gap-x-3">
          <Link href={href(`/c/${slug}/follow-ups/${followUp.id}`)} className={TEXT_ACTION}>
            Open it
          </Link>
          <button type="button" onClick={onDismiss} className={`${TEXT_ACTION} touch:min-h-11`}>
            Dismiss
          </button>
        </span>
      }
    >
      Started “{followUp.name}” for {formatCount(result.started)}
      {result.skipped > 0 ? ` · ${formatCount(result.skipped)} skipped` : ""}
    </NoticeBox>
  );
}
