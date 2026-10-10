"use client";

import { Section } from "@/components/console/section";
import {
  PRIMARY_BUTTON_SM,
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
export function SavedTests({ agentId, canWrite = true }: { agentId: string; canWrite?: boolean }) {
  const session = useClientSession();
  const cases = useTestCases(session, agentId);
  const run = useRunTestCases(session, agentId);

  const data = cases.data;
  const running = data?.cases.some((c) => c.status !== "idle") ?? false;

  return (
    <Section
      title="Saved tests"
      info={
        <p>
          Made from real calls. Each one sends the caller&apos;s words to your live agent and
          shows what it answers, so you can check a change fixed it.
        </p>
      }
      action={
        canWrite && data && data.cases.length > 0 ? (
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            disabled={!data.available || running || run.isPending}
            title={data.unavailable_reason ?? undefined}
            onClick={() => run.mutate()}
          >
            {running ? "Running…" : "Run all"}
          </button>
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
                agentId={agentId}
                testCase={testCase}
                liveVersion={data.live_version ?? null}
                canWrite={canWrite}
              />
            ))}
          </ul>
          <p className="text-meta text-ink-faint">{data.cost_note}</p>
        </div>
      )}
    </Section>
  );
}

function CaseRow({
  agentId,
  testCase,
  liveVersion,
  canWrite,
}: {
  agentId: string;
  testCase: TestCase;
  liveVersion: number | null;
  canWrite: boolean;
}) {
  const session = useClientSession();
  const remove = useDeleteTestCase(session, agentId);
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
      {remove.error ? <ProblemNotice error={remove.error} /> : null}
      {canWrite ? (
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={remove.isPending}
          onClick={() => remove.mutate(testCase.id)}
        >
          {remove.isPending ? "Deleting…" : "Delete test"}
        </button>
      ) : null}
    </li>
  );
}
