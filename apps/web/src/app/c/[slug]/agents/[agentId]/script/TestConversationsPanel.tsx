"use client";

/**
 * TEST YOUR AGENT, THEN IMPROVE IT (D-724; advised before going live, never required).
 *
 * Each run, the AI writes new test callers for this agent (its business, steps, facts,
 * language and where it struggled), always including the four compliance checks, and plays
 * them against the agent callers hear now. Every answer is judged with a one-line reason.
 * "Improve my agent" turns the failures into changes the owner keeps one by one; "Test
 * again" asks the failures again beside fresh callers and shows before and after.
 *
 * Rendered in the agent header's "Try it" drawer and below the script builder. In the
 * builder, kept script changes go into the editor (`current` / `onKeepScript`); in the
 * drawer they are saved to the draft, or put live when the owner presses that.
 */

import { useState } from "react";

import {
  FIELD_HINT,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { lookup } from "@/lib/lookup";
import { useClientSession } from "@/lib/api/session";
import {
  useImproveFromTests,
  useRunTestConversations,
  useTestConversations,
  type CallScript,
  type FixKind,
  type TestHistoryEntry,
  type TestResult,
  type TestRun,
  type TestVerdict,
} from "@/lib/api/script";

import { ImprovementReview } from "./ImprovementReview";

const VERDICT: Record<TestVerdict, { label: string; tone: string; dot: string }> = {
  passed: { label: "Passed", tone: "text-brand-strong", dot: "bg-brand-strong" },
  needs_fix: { label: "Needs a fix", tone: "text-warn", dot: "bg-warn" },
  failed: { label: "Failed", tone: "text-danger", dot: "bg-danger" },
  unjudged: { label: "Not checked", tone: "text-ink-muted", dot: "bg-ink-faint" },
};

export const FIX_LABEL: Record<FixKind, string> = {
  script_step: "Fix in: a script step",
  knowledge: "Fix in: knowledge or a pinned fact",
  objection: "Fix in: handling push-back",
  style: "Fix in: how it speaks",
  settings: "Fix in: settings",
  platform: "Fix on our side: contact us if it keeps happening",
};

const PROBE_NOTE: Record<string, string> = {
  ai: "Compliance check",
  recording: "Compliance check",
  stop_calling: "Compliance check",
  person: "Compliance check",
};

function scoreLine(score: { passed: number; judged: number; total: number }): string {
  if (score.total === 0) return "No tests ran";
  const unchecked = score.total - score.judged;
  const base = `${score.passed} of ${score.judged} passed`;
  return unchecked > 0 ? `${base}, ${unchecked} not checked` : base;
}

export function TestConversationsPanel({
  agentId,
  current,
  onKeepScript,
}: {
  agentId: string;
  /** The builder's working copy, when rendered in the builder. */
  current?: CallScript;
  /** Puts kept script changes into the builder's editor. Without it they are saved. */
  onKeepScript?: (next: CallScript) => void;
}) {
  const session = useClientSession();
  const tests = useTestConversations(session, agentId);
  const run = useRunTestConversations(session, agentId);
  const improve = useImproveFromTests(session, agentId);
  const write = useWriteAccess(session, "org:manage", "test and improve this agent");
  const [auto, setAuto] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [closed, setClosed] = useState<string | null>(null);

  const data = tests.data;
  const latest = data?.latest ?? null;
  const busy = latest?.status === "queued" || latest?.status === "running" || run.isPending;
  const failing = latest?.status === "done" ? latest.results.filter(isFailing) : [];

  const start = () =>
    run.mutate(
      latest?.status === "done" && failing.length > 0
        ? { retest_of: latest.id, auto_improve: auto || latest.auto_improve }
        : { auto_improve: auto },
      { onSuccess: () => setReviewing(false) },
    );
  const askForFixes = (keys?: string[]) => {
    if (!latest) return;
    improve.mutate({ runId: latest.id, keys }, { onSuccess: () => { setClosed(null); setReviewing(true); } });
  };

  const proposal = latest?.improvement ?? null;
  const showReview =
    latest?.status === "done" &&
    proposal !== null &&
    closed !== proposal.created_at &&
    (reviewing || latest.auto_improve);

  return (
    <section aria-labelledby="tests-heading" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id="tests-heading" className="text-heading text-ink">
            Test your agent
          </h3>
          <p className="mt-1 max-w-prose text-meta text-ink-muted">
            New test callers are written for your business each time, and the four questions
            every agent must answer right are always asked. Tests talk to the agent callers hear
            now, not your draft. Advised, not required.
          </p>
        </div>
        {data?.available && (
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={!write.allowed || busy}
              title={write.reason ?? undefined}
              onClick={start}
            >
              {busy ? "Testing…" : latest ? "Test again" : "Run the tests"}
            </button>
            <label className="flex items-center gap-2 text-meta text-ink-muted">
              <input
                type="checkbox"
                checked={auto}
                disabled={!write.allowed || busy}
                onChange={(e) => setAuto(e.target.checked)}
              />
              Suggest fixes when a test fails
            </label>
          </div>
        )}
      </div>

      <RestrictionNote reason={write.reason} />
      {tests.isLoading && <Skeleton rows={3} />}
      {tests.error && <ProblemNotice error={tests.error} onRetry={() => void tests.refetch()} />}
      {run.error && <ProblemNotice error={run.error} />}
      {data && !data.available && <p className="text-meta text-ink-muted">{data.unavailable_reason}</p>}
      {data?.available && <p className={FIELD_HINT}>{data.cost_note}</p>}

      {busy && (
        <div role="status" aria-live="polite" className="space-y-2">
          <p className="text-meta text-ink-muted">
            Writing test callers and talking to your agent. This takes a minute or two.
          </p>
          <Skeleton rows={3} />
        </div>
      )}
      {latest?.status === "failed" && !busy && (
        <p className="text-meta text-ink">
          The tests could not finish this time. Try again in a minute; if it keeps failing, contact
          us.
        </p>
      )}

      {latest?.status === "done" && !busy && (
        <>
          <ScoreHeader run={latest} history={data?.history ?? []} />
          {!latest.is_current && (
            <p className="text-meta text-ink">
              These results are from an earlier version of the script. Test again to check what
              callers hear now.
            </p>
          )}
          {latest.note && <p className="text-meta text-ink-muted">{latest.note}</p>}

          {failing.length > 0 && write.allowed && !showReview && (
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={improve.isPending}
                onClick={() => askForFixes()}
              >
                {improve.isPending ? "Working out fixes…" : `Improve my agent (${failing.length})`}
              </button>
              {proposal && (
                <button type="button" className="text-meta text-ink underline underline-offset-2" onClick={() => { setClosed(null); setReviewing(true); }}>
                  Open the last suggestions
                </button>
              )}
            </div>
          )}
          {improve.error && <ProblemNotice error={improve.error} />}

          {showReview && proposal && (
            <ImprovementReview
              agentId={agentId}
              run={latest}
              improvement={proposal}
              current={current}
              onKeepScript={onKeepScript}
              onClose={() => {
                setClosed(proposal.created_at);
                setReviewing(false);
              }}
              onTestAgain={start}
            />
          )}

          <Results
            results={latest.results}
            canFix={write.allowed && !improve.isPending}
            onFix={(key) => askForFixes([key])}
          />
        </>
      )}
    </section>
  );
}

function isFailing(result: TestResult): boolean {
  return result.verdict === "failed" || result.verdict === "needs_fix";
}

function ScoreHeader({ run, history }: { run: TestRun; history: TestHistoryEntry[] }) {
  const earlier = history.filter((h) => h.id !== run.id).slice(0, 4);
  return (
    <div className="space-y-1">
      <p className="text-body font-semibold text-ink">
        {scoreLine(run.score)}
        {run.round > 1 && <span className="font-normal text-ink-muted"> · retest {run.round - 1}</span>}
      </p>
      {earlier.length > 0 && (
        <p className="text-meta text-ink-muted">
          Earlier:{" "}
          {earlier
            .map((h) => `${h.score.passed} of ${h.score.judged} on ${formatIST(h.created_at)}`)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}

function Results({
  results,
  canFix,
  onFix,
}: {
  results: TestResult[];
  canFix: boolean;
  onFix: (key: string) => void;
}) {
  const failing = results.filter(isFailing);
  const unchecked = results.filter((r) => r.verdict === "unjudged");
  const passed = results.filter((r) => r.verdict === "passed");
  return (
    <div className="space-y-5">
      {failing.length > 0 && (
        <ResultGroup title="Needs attention" results={failing} canFix={canFix} onFix={onFix} />
      )}
      {unchecked.length > 0 && (
        <ResultGroup title="Read these yourself" results={unchecked} canFix={false} onFix={onFix} />
      )}
      {passed.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-meta font-medium text-ink">
            Passed ({passed.length})
          </summary>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {passed.map((result) => (
              <ResultRow key={result.key} result={result} canFix={false} onFix={onFix} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ResultGroup({
  title,
  results,
  canFix,
  onFix,
}: {
  title: string;
  results: TestResult[];
  canFix: boolean;
  onFix: (key: string) => void;
}) {
  return (
    <div>
      <p className="text-meta font-medium text-ink">{title}</p>
      <ul className="mt-1 divide-y divide-line border-y border-line">
        {results.map((result) => (
          <ResultRow key={result.key} result={result} canFix={canFix} onFix={onFix} />
        ))}
      </ul>
    </div>
  );
}

function ResultRow({
  result,
  canFix,
  onFix,
}: {
  result: TestResult;
  canFix: boolean;
  onFix: (key: string) => void;
}) {
  const verdict = VERDICT[result.verdict];
  const before = result.before ? VERDICT[result.before] : null;
  const fix = lookup(FIX_LABEL, result.fix) ?? null;
  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 text-body font-medium text-ink">
          {result.title}
          {result.probe && (
            <span className="ml-2 text-meta font-normal text-ink-muted">{lookup(PROBE_NOTE, result.probe)}</span>
          )}
          {result.source === "saved" && <span className="ml-2 text-meta font-normal text-ink-muted">Saved test</span>}
        </p>
        <span className={`inline-flex shrink-0 items-center gap-1.5 text-meta font-medium ${verdict.tone}`}>
          {before && before.label !== verdict.label && (
            <span className="font-normal text-ink-muted">{before.label} →</span>
          )}
          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${verdict.dot}`} />
          {verdict.label}
        </span>
      </div>
      <div className="mt-1.5 space-y-0.5 text-meta">
        {result.turns.map((turn, index) => (
          <div key={index} className="space-y-0.5">
            <p className="break-words text-ink-muted">
              <span className="font-medium text-ink">Caller:</span> {turn.said}
            </p>
            <p className="break-words text-ink-muted">
              <span className="font-medium text-ink">Agent:</span> {turn.reply || "(said nothing)"}
            </p>
          </div>
        ))}
      </div>
      {result.reason && <p className="mt-1.5 text-meta text-ink">{result.reason}</p>}
      {result.formal_words.length > 0 && (
        <p className="mt-0.5 text-meta text-ink-muted">Textbook words: {result.formal_words.join(", ")}</p>
      )}
      {(fix || (canFix && isFailing(result))) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-3">
          {fix && <span className="text-meta text-ink-muted">{fix}</span>}
          {canFix && isFailing(result) && result.fix !== "platform" && (
            <button
              type="button"
              className="text-meta font-medium text-ink underline underline-offset-2"
              onClick={() => onFix(result.key)}
            >
              Fix this
            </button>
          )}
        </div>
      )}
    </li>
  );
}
