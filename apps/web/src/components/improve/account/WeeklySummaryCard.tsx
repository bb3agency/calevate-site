"use client";

/**
 * THIS WEEK, IN A PARAGRAPH: the summary Pip writes each Monday about the week that closed,
 * from counts only (`workers/weekly_summary`), with the figures it was written from. Past
 * weeks open on request.
 */

import { useState, type ReactNode } from "react";

import { InfoTip } from "@/components/console/infoTip";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatCount, formatISTDate } from "@/components/ui";
import { PAST_WEEKS, useWeeklySummaries, type WeeklySummary } from "@/lib/api/accountImprove";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { ImproveCard, percent } from "../ImproveCard";
import { Quiet } from "./shared";

export const WEEKLY_SUMMARY_TITLE = "Your week";

export function WeeklySummaryCard() {
  const { session } = useClientRealm();
  const latest = useWeeklySummaries(session, 1);
  const [pastOpen, setPastOpen] = useState(false);
  const past = useWeeklySummaries(session, PAST_WEEKS, pastOpen);
  return (
    <ImproveCard
      headingLevel={2}
      title={WEEKLY_SUMMARY_TITLE}
      hint={`${ASSISTANT_NAME} writes it every Monday about the week before.`}
      info="Written from your call counts only, never from what anyone said on a call."
    >
      {latest.isLoading ? (
        <Skeleton rows={2} label="Reading your weekly summary" />
      ) : !latest.data ? (
        <ProblemNotice error={latest.error} onRetry={() => void latest.refetch()} />
      ) : latest.data.length === 0 ? (
        <Quiet>The first one comes the Monday after a week with calls.</Quiet>
      ) : (
        <>
          <Summary summary={latest.data[0]!} />
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} mt-3`}
            aria-expanded={pastOpen}
            onClick={() => setPastOpen(!pastOpen)}
          >
            {pastOpen ? "Hide past weeks" : "Past weeks"}
          </button>
          {pastOpen &&
            (past.isLoading ? (
              <Skeleton rows={2} label="Reading past weeks" />
            ) : !past.data ? (
              <ProblemNotice error={past.error} onRetry={() => void past.refetch()} />
            ) : past.data.length <= 1 ? (
              <Quiet>No earlier weeks yet.</Quiet>
            ) : (
              <ul className="mt-3 divide-y divide-line border-t border-line" aria-label="Past weeks">
                {past.data.slice(1).map((s) => (
                  <li key={s.id} className="py-3">
                    <Summary summary={s} />
                  </li>
                ))}
              </ul>
            ))}
        </>
      )}
    </ImproveCard>
  );
}

function Summary({ summary }: { summary: WeeklySummary }) {
  const { calls = null, answer_rate: rate = null, goals = null, fixes = null } = summary.figures;
  return (
    <div>
      <p className="text-meta text-ink-muted">
        Week of {formatISTDate(`${summary.week_start}T00:00:00+05:30`)}
      </p>
      <p className="mt-1 max-w-prose text-body text-ink">{summary.paragraph}</p>
      <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-meta text-ink-muted tabular-nums">
        {calls !== null && <Fig term="Calls" value={formatCount(calls)} />}
        {rate !== null && <Fig term="Answered" value={percent(rate)} />}
        {goals !== null && <Fig term="Goals reached" value={formatCount(goals)} />}
        {fixes !== null && (
          <Fig
            term="Fixes"
            value={formatCount(fixes)}
            info={
              <InfoTip label="fixes" align="start">
                Script repairs, step outcomes and opening notices {ASSISTANT_NAME} wrote, and calling
                hours and opening tests it applied.
              </InfoTip>
            }
          />
        )}
      </dl>
    </div>
  );
}

function Fig({ term, value, info }: { term: string; value: string; info?: ReactNode }) {
  return (
    <div className="inline-flex items-center gap-1">
      <dt>{term}</dt>
      <dd className="inline-flex items-center gap-1 text-ink">
        {value}
        {info}
      </dd>
    </div>
  );
}
