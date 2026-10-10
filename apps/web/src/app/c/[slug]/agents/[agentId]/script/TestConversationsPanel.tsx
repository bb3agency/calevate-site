"use client";

/**
 * TRY IT BEFORE CALLERS DO — the pre-launch test conversations (founder decision 11:
 * advised, never required). Six short caller lines are sent to the agent as the calling
 * system holds it; each answer is shown with what to fix. Nothing here blocks Switch on.
 */

import { CheckCircle2, CircleAlert, Eye, XCircle } from "lucide-react";

import { ProblemNotice, RestrictionNote, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  useRunTestConversations,
  useTestConversations,
  type TestResult,
  type TestVerdict,
} from "@/lib/api/script";

const VERDICT: Record<TestVerdict, { label: string; icon: typeof CheckCircle2; tone: string }> = {
  passed: { label: "Looks right", icon: CheckCircle2, tone: "text-brand-strong" },
  read: { label: "Read this one", icon: Eye, tone: "text-ink-muted" },
  attention: { label: "Needs a fix", icon: CircleAlert, tone: "text-warn" },
  failed: { label: "Contact us", icon: XCircle, tone: "text-danger" },
};

export function TestConversationsPanel({ agentId }: { agentId: string }) {
  const session = useClientSession();
  const tests = useTestConversations(session, agentId);
  const run = useRunTestConversations(session, agentId);
  const write = useWriteAccess(session, "org:manage", "run test conversations");

  const latest = tests.data?.latest ?? null;
  const busy = latest?.status === "queued" || latest?.status === "running" || run.isPending;

  return (
    <section aria-labelledby="tests-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h3 id="tests-heading" className="text-heading text-ink">
            Test what callers hear
          </h3>
          <p className="mt-1 text-sm text-ink-muted">
            We play six short callers: a product question, &ldquo;are you an AI?&rdquo;,
            &ldquo;is this recorded?&rdquo;, &ldquo;stop calling me&rdquo;, a request for a
            person and a push-back, against the script callers hear now, not your draft. Put changes
            live first to test them. Advised, not required.
          </p>
        </div>
        {tests.data?.available && (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!write.allowed || busy}
            title={write.reason ?? undefined}
            onClick={() => run.mutate()}
          >
            {busy ? "Testing…" : latest ? "Test again" : "Run the tests"}
          </button>
        )}
      </div>
      <RestrictionNote reason={write.reason} />
      {tests.isLoading && <Skeleton rows={3} />}
      {tests.error && <ProblemNotice error={tests.error} onRetry={() => void tests.refetch()} />}
      {run.error && <ProblemNotice error={run.error} />}
      {tests.data && !tests.data.available && (
        <p className="text-sm text-ink-muted">{tests.data.unavailable_reason}</p>
      )}
      {tests.data?.available && <p className="text-xs text-ink-faint">{tests.data.cost_note}</p>}
      {busy && (
        <div role="status" aria-live="polite" className="space-y-2">
          <p className="text-sm text-ink-muted">Talking to your agent. This takes about half a minute.</p>
          <Skeleton rows={3} />
        </div>
      )}
      {latest?.status === "failed" && !busy && (
        <p className="text-sm text-ink">
          The tests could not finish this time. Try again in a minute; if it keeps failing,
          contact us.
        </p>
      )}
      {latest?.status === "done" && !busy && (
        <>
          {!latest.is_current && (
            <p className="text-sm text-ink">
              These results are from an earlier version of the script. Test again to check the
              version callers hear now.
            </p>
          )}
          <ul className="divide-y divide-line border-y border-line">
            {latest.results.map((result) => (
              <ResultRow key={result.key} result={result} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function ResultRow({ result }: { result: TestResult }) {
  const verdict = VERDICT[result.verdict];
  const Icon = verdict.icon;
  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-ink">{result.title}</p>
        <span className={`inline-flex shrink-0 items-center gap-1 text-xs font-medium ${verdict.tone}`}>
          <Icon aria-hidden className="h-3.5 w-3.5" />
          {verdict.label}
        </span>
      </div>
      <p className="mt-1 text-sm text-ink-muted">
        <span className="font-medium text-ink">Caller:</span> {result.said}
      </p>
      <p className="mt-0.5 text-sm text-ink-muted">
        <span className="font-medium text-ink">Agent:</span> {result.reply || "(said nothing)"}
      </p>
      {result.advice && <p className="mt-1 text-sm text-ink">{result.advice}</p>}
    </li>
  );
}
