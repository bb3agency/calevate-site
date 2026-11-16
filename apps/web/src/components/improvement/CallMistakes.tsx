"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Section, TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { useEnterClass } from "@/components/live/arrivals";
import {
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatISTDate,
  type NoticeTone,
} from "@/components/ui";
import {
  FOUND_IN_SCRIPT,
  callsLine,
  clientStateLine,
  useAgentMistakes,
  useUndoMistakeFix,
  type AgentMistake,
  type MistakeState,
} from "@/lib/api/callMistakes";
import { useClientRealm } from "@/lib/api/session";

const STATE_TONES: Record<MistakeState, NoticeTone> = {
  back: "warn",
  fixing: "neutral",
  fixed: "ok",
  script_fixing: "neutral",
  script_proposed: "warn",
  no_job: "neutral",
  script_live: "ok",
  script_fixed: "ok",
  script_rolled_back: "warn",
  script_undone: "neutral",
  with_team: "neutral",
};

/**
 * MISTAKES ON REAL CALLS (D-949): what this agent got wrong on live calls, most urgent
 * first (the server's order: came back, waiting for review, being fixed, fixed). Where a line
 * of a script is the cause, we write the fix as a draft on the Inbound line or campaign the
 * call was on (D-1005) and "Review it" opens it there; a call on neither has no script to
 * fix, and the row says so. The other actions are hearing the last call it happened on and
 * undoing a fix we put live before that. What a good receptionist does instead sits behind
 * a tap, so the closed list is a label, a count and a state.
 */
export function CallMistakes({
  agentId,
  headingLevel = 2,
  className,
}: {
  agentId: string;
  headingLevel?: 2 | 3;
  className?: string;
}) {
  const { session } = useClientRealm();
  const mistakes = useAgentMistakes(session, agentId);
  const title = "Mistakes on real calls";
  const enter = useEnterClass(mistakes.data ? mistakes.data.items.map((m) => m.kind) : null);

  if (mistakes.isLoading) {
    return (
      <Section title={title} headingLevel={headingLevel} className={className}>
        <Skeleton rows={2} label="Loading the mistakes on real calls" />
      </Section>
    );
  }
  if (mistakes.error || !mistakes.data) {
    return (
      <Section title={title} headingLevel={headingLevel} className={className}>
        <ProblemNotice
          error={mistakes.error ?? new Error("The mistakes on real calls did not load.")}
          onRetry={() => void mistakes.refetch()}
        />
      </Section>
    );
  }

  const { items, window_days } = mistakes.data;
  return (
    <Section title={title} headingLevel={headingLevel} className={className}>
      {items.length === 0 ? (
        <p className="flex items-center gap-2 text-meta text-ink-muted">
          <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
          <span>No mistakes found on real calls in the last {window_days} days.</span>
        </p>
      ) : (
        <ul className="divide-y divide-line border-y border-line" aria-label={title}>
          {items.map((mistake) => (
            <MistakeRow
              key={mistake.kind}
              agentId={agentId}
              mistake={mistake}
              windowDays={window_days}
              enterClass={enter(mistake.kind)}
              rowHeading={headingLevel === 3 ? "h4" : "h3"}
            />
          ))}
        </ul>
      )}
    </Section>
  );
}

function MistakeRow({
  agentId,
  mistake,
  windowDays,
  enterClass,
  rowHeading: RowHeading,
}: {
  agentId: string;
  mistake: AgentMistake;
  windowDays: number;
  enterClass: string;
  rowHeading: "h3" | "h4";
}) {
  const { session, href } = useClientRealm();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const undo = useUndoMistakeFix(session, agentId);
  // The failure is shown beside the row (ProblemNotice below), so it is not toasted too.
  const undoFeedback = useActionFeedback(undo, { errorDisplay: "inline" });

  return (
    <li className={`py-3 ${enterClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <RowHeading className="text-sm font-semibold text-ink [overflow-wrap:anywhere]">
            {mistake.label}
          </RowHeading>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-muted">
            <span className="tabular-nums">
              {mistake.found_in_script ? FOUND_IN_SCRIPT : callsLine(mistake.calls, windowDays)}
            </span>
            <StatusPill tone={STATE_TONES[mistake.state]} wrap>
              {clientStateLine(
                mistake.state,
                formatISTDate(mistake.fixed_at),
                mistake.clean_calls,
                mistake.fix_waiting,
              )}
            </StatusPill>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {mistake.state === "script_proposed" && mistake.fix_waiting && mistake.fix_holder ? (
            <Link
              href={href(
                mistake.fix_holder.kind === "inbound_line"
                  ? `/c/${session.orgSlug}/inbound/${mistake.fix_holder.id}`
                  : `/c/${session.orgSlug}/campaigns/${mistake.fix_holder.id}`,
              )}
              aria-label={`Review our fix on ${mistake.fix_holder.name}: ${mistake.label}`}
              className={SECONDARY_BUTTON_SM}
            >
              Review it
            </Link>
          ) : null}
          {mistake.can_undo ? (
            <ActionButton
              variant="secondary-sm"
              aria-label={`Undo our fix: ${mistake.label}`}
              status={undoFeedback.status}
              pendingLabel="Undoing…"
              successLabel="Undone"
              onClick={() => undoFeedback.run(mistake.kind)}
            >
              Undo
            </ActionButton>
          ) : null}
          {mistake.last_call_id ? (
            <Link
              href={href(`/c/${session.orgSlug}/calls/${mistake.last_call_id}`)}
              className={SECONDARY_BUTTON_SM}
            >
              Hear the last one
            </Link>
          ) : null}
        </div>
      </div>
      {undo.error ? (
        <div className="mt-2">
          <ProblemNotice error={undo.error} />
        </div>
      ) : null}
      <button
        type="button"
        className={`${TEXT_ACTION_SM} -mx-2 mt-1`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? "Hide what it should do" : "What it should do"}
      </button>
      <p id={panelId} hidden={!open} className="mt-1 text-meta text-ink">
        {mistake.instead}
      </p>
    </li>
  );
}
