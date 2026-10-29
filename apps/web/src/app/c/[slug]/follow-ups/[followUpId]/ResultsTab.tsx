"use client";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Fact, ProblemNotice, Skeleton, formatCount } from "@/components/ui";
import { useFollowUpResults, type FollowUpOut, type FollowUpResultsOut } from "@/lib/api/followUps";
import { useClientRealm } from "@/lib/api/session";

import { exitWords } from "../followUpCopy";

type StepResult = FollowUpResultsOut["steps"][number] & { summary: string };

/**
 * How it went over the last 30 days: three totals, then each step's count and where its
 * leads went from it. A table, because the reader compares numbers along one row.
 */
export function ResultsTab({ followUp }: { followUp: FollowUpOut }) {
  const { session } = useClientRealm();
  const results = useFollowUpResults(session, followUp.id);

  if (results.isLoading) return <Skeleton rows={4} label="Loading the results" />;
  const data = results.data;
  if (!data) return <ProblemNotice error={results.error} onRetry={() => void results.refetch()} />;

  const summaries = new Map(followUp.steps.map((step) => [step.id, step.summary]));
  const rows: StepResult[] = data.steps.map((step) => ({
    ...step,
    summary: summaries.get(step.step_id) ?? "A step no longer in it",
  }));

  const columns: DataColumn<StepResult>[] = [
    { id: "step", header: "Step", cell: (row) => <span className="text-ink [overflow-wrap:anywhere]">{row.summary}</span> },
    {
      id: "reached",
      header: "Reached",
      align: "right",
      cell: (row) => <span className="tabular-nums text-ink">{formatCount(row.reached)}</span>,
    },
    {
      id: "exits",
      header: "Then",
      card: "block",
      cell: (row) => {
        const exits = Object.entries(row.exits);
        return exits.length ? (
          <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-meta text-ink-muted">
            {exits.map(([key, count]) => (
              <li key={key}>
                {exitWords(key)} <span className="font-medium tabular-nums text-ink">{formatCount(count)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-meta text-ink-faint">—</span>
        );
      },
    },
  ];

  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-3 gap-4">
        <Fact label={`Started, ${data.days} days`}>
          <span className="tabular-nums">{formatCount(data.started)}</span>
        </Fact>
        <Fact label="Finished">
          <span className="tabular-nums">{formatCount(data.finished)}</span>
        </Fact>
        <Fact label="Reached goal">
          <span className="tabular-nums">{formatCount(data.goal_reached)}</span>
        </Fact>
      </dl>
      <div className="border-y border-line">
        <DataTable label={`Each step, last ${data.days} days`} rows={rows} columns={columns} getRowId={(row) => row.step_id} />
      </div>
    </div>
  );
}
