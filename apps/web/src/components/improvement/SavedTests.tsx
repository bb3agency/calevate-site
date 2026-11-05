"use client";

import Link from "next/link";
import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import {
  useCreateTestCase,
  useDeleteTestCase,
  useTestCases,
  type TestCase,
} from "@/lib/api/teach";

/**
 * An agent's saved tests (made from a call with "Make this call a test", or written here).
 * They have no run of their own: every new set of the agent's tests asks them, judged like
 * the rest, so "Test your agent" has one run button and one result per test (D-970; Retell's
 * batch tests run saved cases as one suite with one pass rate, docs.retellai.com/test/
 * batch-test-simulation). This list is where they are made, read and deleted.
 */
export function SavedTests({
  agentId,
  slug,
  canWrite = true,
}: {
  agentId: string;
  /** The account, for the link to its calls, where a test is made from a call. */
  slug: string;
  canWrite?: boolean;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const cases = useTestCases(session, agentId);
  /* Deleting lives here, not in the row: the row is gone once it succeeds, so its own hook
     could not confirm it. */
  const remove = useDeleteTestCase(session, agentId);
  const removeFeedback = useActionFeedback(remove, {
    errorDisplay: "inline",
    successToast: "Test deleted",
  });
  const [deleting, setDeleting] = useState<TestCase | null>(null);

  const data = cases.data;
  const full = (data?.cases.length ?? 0) >= MAX_SAVED_TESTS;

  return (
    <section aria-labelledby={`saved-tests-${agentId}`} className="space-y-3">
      <h4 id={`saved-tests-${agentId}`} className="text-sm font-semibold text-ink">
        Your own tests
      </h4>
      {cases.isLoading ? (
        <Skeleton rows={2} label="Loading your own tests" />
      ) : cases.error || !data ? (
        <ProblemNotice
          error={cases.error ?? new Error("We could not load your own tests.")}
          onRetry={() => void cases.refetch()}
        />
      ) : data.cases.length === 0 ? (
        <p className="text-meta text-ink-muted">None yet. A test you add runs with the others.</p>
      ) : (
        <>
          <p className="text-meta text-ink-muted">Each new run asks these too.</p>
          <ul className="divide-y divide-line border-y border-line">
            {data.cases.map((testCase) => (
              <CaseRow
                key={testCase.id}
                testCase={testCase}
                canWrite={canWrite}
                onDelete={() => {
                  remove.reset();
                  setDeleting(testCase);
                }}
              />
            ))}
          </ul>
        </>
      )}
      {canWrite && data && !full ? (
        <div className="flex flex-wrap items-center gap-x-4">
          <WriteATest agentId={agentId} />
          <Link href={href(`/c/${slug}/calls`)} className={`${TEXT_ACTION_SM} -mx-2`}>
            Save a test from a call
          </Link>
        </div>
      ) : null}
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
    </section>
  );
}

/** `teach/test_cases.MAX_CASES_PER_AGENT`: the server refuses a test past it. */
const MAX_SAVED_TESTS = 20;
/** `teach/models.MAX_CASE_LINES`. */
const MAX_CALLER_LINES = 20;

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
      <button type="button" className={`${TEXT_ACTION_SM} -mx-2`} onClick={() => setOpen(true)}>
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
      className="w-full space-y-3"
      onSubmit={valid.onSubmit(() =>
        create.mutate(
          // No title: the server names the test from the first line, in six words (D-917).
          { title: "", caller_lines: lines.slice(0, MAX_CALLER_LINES), expected: expected.trim() },
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
        <span className={FIELD_HINT}>
          One line for each thing they say, up to {MAX_CALLER_LINES}. Enough to walk through a
          whole guided call.
        </span>
        {lines.length > MAX_CALLER_LINES ? (
          <p role="status" className="text-meta text-warn">
            Only the first {MAX_CALLER_LINES} lines are saved.
          </p>
        ) : null}
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

/** One saved test: its name, what it should do and what the caller says. How it did on the
 * last run is on that run's result, beside every other test. */
function CaseRow({
  testCase,
  canWrite,
  onDelete,
}: {
  testCase: TestCase;
  canWrite: boolean;
  onDelete: () => void;
}) {
  return (
    <li className="space-y-1.5 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h5 className="min-w-0 text-sm font-medium text-ink [overflow-wrap:anywhere]">
          {testCase.short_title}
        </h5>
        {canWrite ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            aria-label={`Delete test: ${testCase.short_title}`}
            onClick={onDelete}
          >
            Delete
          </button>
        ) : null}
      </div>
      <p className="text-meta text-ink-muted">Should: {testCase.expected}</p>
      <ol className="space-y-0.5 text-meta text-ink-muted">
        {testCase.caller_lines.map((line, index) => (
          <li key={index} className="[overflow-wrap:anywhere]">
            Caller: {line}
          </li>
        ))}
      </ol>
    </li>
  );
}
