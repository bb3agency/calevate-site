"use client";

import { useId, useState, type ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Section, TEXT_ACTION_SM } from "@/components/console/section";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import {
  useCreateTestCase,
  useDeleteTestCase,
  useRunTestCases,
  useTestCases,
  type TestCase,
} from "@/lib/api/teach";

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
  framed = true,
}: {
  agentId: string;
  canWrite?: boolean;
  headingLevel?: 2 | 3;
  /** False inside a disclosure that already names it (the Training tab). */
  framed?: boolean;
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
  const Frame = framed ? Section : Unframed;
  const full = (data?.cases.length ?? 0) >= MAX_SAVED_TESTS;

  return (
    <Frame
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
          None yet. Make one from a call where the agent went wrong, or write one below.
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
      {canWrite && data && !full ? <WriteATest agentId={agentId} /> : null}
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
    </Frame>
  );
}

/** `teach/test_cases.MAX_CASES_PER_AGENT`: the server refuses a test past it. */
const MAX_SAVED_TESTS = 20;
/** `teach/models.MAX_CASE_LINES`. */
const MAX_CALLER_LINES = 6;

/** The list's own frame when a disclosure around it already carries the title. */
function Unframed({ action, children }: { action?: ReactNode; children?: ReactNode } & Record<string, unknown>) {
  return (
    <div className="space-y-3">
      {action ? <div className="flex justify-end">{action}</div> : null}
      {children}
    </div>
  );
}

/**
 * A test written by hand: what the caller says (a line per thing they say) and what the
 * agent should do. Closed until asked for, so the list stays the first thing read.
 */
function WriteATest({ agentId }: { agentId: string }) {
  const session = useClientSession();
  const create = useCreateTestCase(session, agentId);
  const feedback = useActionFeedback(create, { errorDisplay: "inline", successToast: "Test saved" });
  const [open, setOpen] = useState(false);
  const [said, setSaid] = useState("");
  const [expected, setExpected] = useState("");
  const saidId = useId();
  const expectedId = useId();
  const valid = useFormValidation();
  const saidField = valid.field("said", "Write what the caller says.");
  const expectedField = valid.field("expected", "Write what the agent should do.");

  if (!open) {
    return (
      <button type="button" className={`${TEXT_ACTION_SM} mt-3`} onClick={() => setOpen(true)}>
        Write a test
      </button>
    );
  }
  const lines = said
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  return (
    <form
      noValidate
      className="mt-4 space-y-3"
      onSubmit={valid.onSubmit(() =>
        create.mutate(
          { title: lines[0]?.slice(0, 120) ?? "", caller_lines: lines.slice(0, MAX_CALLER_LINES), expected: expected.trim() },
          {
            onSuccess: () => {
              setSaid("");
              setExpected("");
              setOpen(false);
            },
          },
        ),
      )}
    >
      <div>
        <label htmlFor={saidId} className={FIELD_LABEL}>
          What the caller says
        </label>
        <textarea
          {...saidField}
          required
          id={saidId}
          rows={2}
          maxLength={MAX_CALLER_LINES * 500}
          value={said}
          onChange={(event) => setSaid(event.target.value)}
          className={FIELD}
        />
        <span className={FIELD_HINT}>One line for each thing they say.</span>
        {valid.error("said")}
      </div>
      <div>
        <label htmlFor={expectedId} className={FIELD_LABEL}>
          What the agent should do
        </label>
        <input
          {...expectedField}
          required
          id={expectedId}
          maxLength={600}
          value={expected}
          onChange={(event) => setExpected(event.target.value)}
          className={FIELD}
        />
        {valid.error("expected")}
      </div>
      {create.error ? <ProblemNotice error={create.error} /> : null}
      <div className="flex flex-wrap gap-2">
        <ActionButton type="submit" variant="primary-sm" status={feedback.status} successLabel="Saved">
          Save test
        </ActionButton>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
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
