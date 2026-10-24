"use client";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { StatusPill } from "@/components/console/statusPill";
import { NoticeBox, ProblemNotice, formatIST } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { testRunning, useLineTests, useRunTest, type ForwardedLine } from "@/lib/api/forwarding";

import { CALLER_ID_COPY, CONCURRENCY_COPY, OUTCOME_COPY, SELF_CHECKS } from "./copy";

/**
 * THE VERIFICATION CALL for one number: run it, watch it, read what it found.
 *
 * We ring the business's own number from our side; through its forward it should reach the
 * business's Calevate number. It records whether it arrived, whose number the network
 * showed, and (when two can be placed) whether two calls at once both got through. The
 * call is ours to pay for. The button is full width on a phone.
 */
export function TestPanel({
  session,
  line,
  allowed,
  available,
  primary = false,
}: {
  session: Session;
  line: ForwardedLine;
  allowed: boolean;
  available: boolean;
  /** The screen's one primary action (the guide's last step), or a secondary one. */
  primary?: boolean;
}) {
  const tests = useLineTests(session, line.id);
  const run = useRunTest(session, line.id);
  // A refusal is said above the button; the result is the panel's own status line.
  const runFeedback = useActionFeedback(run, { errorDisplay: "inline" });
  const latest = tests.data?.[0];
  const running = testRunning(latest) || run.isPending;
  const outcome = latest?.outcome ? OUTCOME_COPY[latest.outcome] : null;

  return (
    <div className="space-y-3">
      <p className="text-body text-ink-muted">
        We ring your number from our side. It should reach your agent. Don&apos;t answer it.
      </p>
      {!available && (
        <NoticeBox tone="neutral" title="Test calls are not available yet." role="status">
          Set the forward up now; you can test it later.
        </NoticeBox>
      )}
      {run.error != null && <ProblemNotice error={run.error} />}
      {tests.error != null && <ProblemNotice error={tests.error} onRetry={() => void tests.refetch()} />}
      {running && (
        <p role="status" className="text-body text-ink">
          Testing. This takes about two minutes.
        </p>
      )}
      {!running && latest && outcome && (
        <div role="status" className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone={outcome.tone}>{latest.outcome === "arrived" ? "Working" : "Not working"}</StatusPill>
            <span className="text-meta text-ink-muted">{formatIST(latest.settled_at ?? latest.created_at)}</span>
          </div>
          <p className="text-body text-ink">{outcome.text}</p>
          {latest.caller_id_finding && <p className="text-body text-ink-muted">{CALLER_ID_COPY[latest.caller_id_finding]}</p>}
          {latest.concurrency_finding && latest.outcome === "arrived" && (
            <p className="text-body text-ink-muted">{CONCURRENCY_COPY[latest.concurrency_finding]}</p>
          )}
        </div>
      )}
      <details className="text-body">
        <summary className="cursor-pointer text-body font-medium text-ink touch:min-h-11">Things to try with the test</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-muted">
          {SELF_CHECKS.map((check) => (
            <li key={check}>{check}</li>
          ))}
        </ul>
      </details>
      {/* Busy for the whole test, not only the request that starts it: the call takes
          about two minutes and a second press would ring the number twice. */}
      <ActionButton
        variant={primary ? "primary" : "secondary"}
        className="w-full sm:w-auto"
        status={running ? "pending" : runFeedback.status}
        pendingLabel="Testing…"
        successLabel="Started"
        disabled={!allowed || !available}
        onClick={() => runFeedback.run()}
      >
        {latest ? "Test again" : "Test it now"}
      </ActionButton>
    </div>
  );
}
