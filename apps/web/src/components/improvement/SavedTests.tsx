"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Section } from "@/components/console/section";
import {
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { useDeleteTestCase, useRunTestCases, useTestCases, type TestCase } from "@/lib/api/teach";

/**
 * An agent's saved tests (made from real calls with "Make this call a test") and what the
 * LIVE agent answered on the last run. Run them after changing the script or knowledge; the
 * owner compares each answer with what they expected. For the agent page:
 * `<SavedTests agentId={agent.id} />`.
 */
export function SavedTests({
  agentId,
  canWrite = true,
  headingLevel = 2,
}: {
  agentId: string;
  canWrite?: boolean;
  headingLevel?: 2 | 3;
}) {
  const session = useClientSession();
  const cases = useTestCases(session, agentId);
  const run = useRunTestCases(session, agentId);
  // The run's failure is shown above the list, so it is not toasted.
  const runFeedback = useActionFeedback(run, { errorDisplay: "inline" });
  /* Deleting lives here, not in the row: the row is gone once it succeeds, so its own hook
     could not confirm it. */
  const remove = useDeleteTestCase(session, agentId);
  const removeFeedback = useActionFeedback(remove, {
    errorDisplay: "inline",
    successToast: "Test deleted",
  });
  const [deleting, setDeleting] = useState<TestCase | null>(null);

  const data = cases.data;
  const running = data?.cases.some((c) => c.status !== "idle") ?? false;

  return (
    <Section
      headingLevel={headingLevel}
      title="Saved tests"
      info={
        <p>
          Made from real calls. Each one sends the caller&apos;s words to your live agent and
          shows what it answers, so you can check a change fixed it.
        </p>
      }
      action={
        canWrite && data && data.cases.length > 0 ? (
          <ActionButton
            variant="primary-sm"
            // The run carries on on the server after the request returns; the button stays
            // busy until every case is back.
            status={running ? "pending" : runFeedback.status}
            pendingLabel="Running"
            successLabel="Done"
            disabled={!data.available}
            title={data.unavailable_reason ?? undefined}
            onClick={() => runFeedback.run()}
          >
            Run all
          </ActionButton>
        ) : undefined
      }
    >
      {cases.isLoading ? (
        <Skeleton rows={3} label="Loading saved tests" />
      ) : cases.error || !data ? (
        <ProblemNotice
          error={cases.error ?? new Error("We could not load the saved tests.")}
          onRetry={() => void cases.refetch()}
        />
      ) : data.cases.length === 0 ? (
        <p className="text-meta text-ink-muted">
          No saved tests yet. Open a call where the agent went wrong and choose Make this call
          a test.
        </p>
      ) : (
        <div className="space-y-3">
          {!data.available && data.unavailable_reason ? (
            <p className="text-meta text-ink-muted">{data.unavailable_reason}</p>
          ) : null}
          {run.error ? <ProblemNotice error={run.error} /> : null}
          <ul className="divide-y divide-line border-y border-line">
            {data.cases.map((testCase) => (
              <CaseRow
                key={testCase.id}
                testCase={testCase}
                liveVersion={data.live_version ?? null}
                canWrite={canWrite}
                onDelete={() => {
                  remove.reset();
                  setDeleting(testCase);
                }}
              />
            ))}
          </ul>
          <p className="text-meta text-ink-faint">{data.cost_note}</p>
        </div>
      )}
      {deleting ? (
        <ConfirmDialog
          title={`Delete the test "${deleting.title}"?`}
          confirmLabel="Delete test"
          pendingLabel="Deleting"
          status={removeFeedback.status}
          error={remove.error}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        >
          It stops running with this agent&apos;s other tests. The call it was made from is kept.
        </ConfirmDialog>
      ) : null}
    </Section>
  );
}

function CaseRow({
  testCase,
  liveVersion,
  canWrite,
  onDelete,
}: {
  testCase: TestCase;
  liveVersion: number | null;
  canWrite: boolean;
  onDelete: () => void;
}) {
  const result = testCase.last_result;
  const stale =
    result && liveVersion !== null && testCase.last_prompt_version !== liveVersion;
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="min-w-0 text-sm font-semibold text-ink [overflow-wrap:anywhere]">
          {testCase.title}
        </h4>
        <span className="text-meta text-ink-faint">
          {testCase.status !== "idle"
            ? "Running…"
            : testCase.last_run_at
              ? `Last run ${formatIST(testCase.last_run_at)}${stale ? " · before your latest change" : ""}`
              : "Not run yet"}
        </span>
      </div>
      <p className="text-meta text-ink-muted">Should: {testCase.expected}</p>
      {testCase.last_error ? (
        <p className="text-meta text-warn">The last run did not finish. Run it again.</p>
      ) : null}
      {result ? (
        <ol className="space-y-1.5">
          {result.map((turn, index) => (
            <li key={index} className="space-y-0.5 border-l-2 border-line pl-3 text-meta">
              <p className="text-ink-muted">Caller: {turn.said}</p>
              <p className="text-ink [overflow-wrap:anywhere]">
                Agent: {turn.reply || "(no answer)"}
                {turn.looked_up_knowledge ? (
                  <span className="text-ink-faint"> · looked it up</span>
                ) : null}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <ol className="space-y-1 text-meta text-ink-muted">
          {testCase.caller_lines.map((line, index) => (
            <li key={index}>Caller: {line}</li>
          ))}
        </ol>
      )}
      {canWrite ? (
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDelete}>
          Delete test
        </button>
      ) : null}
    </li>
  );
}
