"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { CheckCircle2 } from "lucide-react";

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
  callsLine,
  clientStateLine,
  useAgentMistakes,
  type AgentMistake,
  type MistakeState,
} from "@/lib/api/callMistakes";
import { useClientRealm } from "@/lib/api/session";

const STATE_TONES: Record<MistakeState, NoticeTone> = {
  back: "warn",
  fixing: "neutral",
  fixed: "ok",
};

/**
 * MISTAKES ON REAL CALLS (D-949): what this agent got wrong on live calls, most urgent
 * first (the server's order: came back, being fixed, fixed). Each kind is a rule of ours,
 * so the copy says we are fixing it and never asks the owner to; the one action is hearing
 * the last call it happened on. What a good receptionist does instead sits behind a tap,
 * so the closed list is a label, a count and a state.
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
  mistake,
  windowDays,
  enterClass,
  rowHeading: RowHeading,
}: {
  mistake: AgentMistake;
  windowDays: number;
  enterClass: string;
  rowHeading: "h3" | "h4";
}) {
  const { session, href } = useClientRealm();
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <li className={`py-3 ${enterClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <RowHeading className="text-sm font-semibold text-ink [overflow-wrap:anywhere]">
            {mistake.label}
          </RowHeading>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-muted">
            <span className="tabular-nums">{callsLine(mistake.calls, windowDays)}</span>
            <StatusPill tone={STATE_TONES[mistake.state]} wrap>
              {clientStateLine(mistake.state, formatISTDate(mistake.fixed_at))}
            </StatusPill>
          </p>
        </div>
        <Link
          href={href(`/c/${session.orgSlug}/calls/${mistake.last_call_id}`)}
          className={SECONDARY_BUTTON_SM}
        >
          Hear the last one
        </Link>
      </div>
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
