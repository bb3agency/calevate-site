"use client";

/**
 * TEST — practice callers talk to the agent callers hear now, and the failures become fixes
 * the owner reviews (D-724, given its own section by D-748).
 *
 * Order on the screen is the order of the job: what happened (the summary and the trend),
 * what to do next (run again, or get suggested fixes and see each change before keeping it),
 * then every test as the conversation it was, failures first. Explanations sit behind ⓘ;
 * notices are one quiet line each.
 *
 * Kept script changes go to the draft (or live, when the owner presses "Keep and put live"
 * with no other draft waiting); the builder is one link away.
 */

import Link from "next/link";
import { useState } from "react";

import { InfoTip } from "@/components/console/infoTip";
import { SavedTests } from "@/components/improvement/SavedTests";
import {
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useImproveFromTests,
  useRunTestConversations,
  useTestConversations,
  type TestResult,
  type TestRun,
  type TestTurn,
} from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { ImprovementReview } from "../script/ImprovementReview";
import {
  ACTION_LABEL,
  VERDICT,
  WHAT_TO_DO,
  countsOf,
  isFailing,
  languageOf,
  trendLine,
} from "./testCopy";

const PROBE_TAG = "Must answer right";

export function TestSection({ agent, slug }: { agent: Pick<Agent, "id">; slug: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const tests = useTestConversations(session, agent.id);
  const run = useRunTestConversations(session, agent.id);
  const improve = useImproveFromTests(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "test and improve this agent");
  const [auto, setAuto] = useState(false);
  const [closed, setClosed] = useState<string | null>(null);

  const data = tests.data;
  const latest = data?.latest ?? null;
  const testing = latest?.status === "queued" || latest?.status === "running" || run.isPending;
  const done = latest?.status === "done" ? latest : null;
  const failing = done ? done.results.filter(isFailing) : [];
  const counts = done ? countsOf(done.results) : null;
  const improving = done?.improving === true || improve.isPending;
  const proposal = done?.improvement ?? null;
  const showReview = done !== null && proposal !== null && !improving && closed !== proposal.created_at;

  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: "Agent: test",
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      {
        key: "state",
        label: "What is on screen",
        value: counts
          ? `the latest test: ${counts.passed} passed, ${counts.failing} need a fix, ${counts.unchecked} not checked`
          : testing
            ? "a test is running"
            : "no finished test yet",
      },
      { key: "what_is_here", label: "What this section does", value: "practice callers talk to the agent callers hear now; failures become suggested fixes" },
    ],
    apply: noFill,
  });

  const start = () =>
    run.mutate(
      done && failing.length > 0 ? { retest_of: done.id, auto_improve: auto || done.auto_improve } : { auto_improve: auto },
    );
  const askForFixes = (keys?: string[]) => {
    if (!done) return;
    setClosed(null);
    improve.mutate({ runId: done.id, keys });
  };

  const canRun = data?.available === true && write.allowed && !testing;
  // One filled button per view: once a test fails, the next step is fixing it.
  const nextIsFixing = failing.length > 0;

  return (
    <div className="max-w-3xl space-y-8">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="max-w-prose text-body text-ink-muted">
            Practice callers talk to the agent callers hear now, and every answer is checked.
          </p>
          <InfoTip label="how testing works">
            <p>
              Each run, new practice callers are written for your business, and the four questions every
              agent must answer right are always asked: is this a person, is the call recorded, stop
              calling me, and let me talk to someone.
            </p>
            <p className="mt-2">Tests talk to what callers hear now, not to changes still waiting in your draft.</p>
            {data?.cost_note && <p className="mt-2">{data.cost_note}</p>}
          </InfoTip>
        </div>

        {data?.waiting_update && (
          <NoticeBox
            tone="warn"
            title={data.waiting_update}
            action={
              <Link href={href(`/c/${slug}/agreements`)} className="text-meta font-medium text-ink underline underline-offset-2">
                Open agreements
              </Link>
            }
          />
        )}

        {data && !data.available && <p className="text-body text-ink-muted">{data.unavailable_reason}</p>}
        <RestrictionNote reason={write.reason} />

        {data?.available && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <button
              type="button"
              className={nextIsFixing ? SECONDARY_BUTTON_SM : PRIMARY_BUTTON_SM}
              disabled={!canRun}
              title={write.reason ?? undefined}
              onClick={start}
            >
              {testing ? "Testing…" : latest ? "Test again" : "Run the tests"}
            </button>
            <label className="flex min-h-11 items-center gap-2 text-meta text-ink-muted">
              <input
                type="checkbox"
                checked={auto}
                disabled={!write.allowed || testing}
                onChange={(e) => setAuto(e.target.checked)}
              />
              Suggest fixes when a test fails
            </label>
          </div>
        )}
        {run.error && <ProblemNotice error={run.error} />}
      </div>

      {tests.isLoading && <Skeleton rows={4} />}
      {tests.error && <ProblemNotice error={tests.error} onRetry={() => void tests.refetch()} />}

      {testing && (
        <div role="status" aria-live="polite" className="space-y-2">
          <p className="text-body text-ink-muted">
            <span className="text-shimmer">Writing practice callers and talking to your agent.</span> This takes a
            minute or two.
          </p>
          <Skeleton rows={3} />
        </div>
      )}
      {latest?.status === "failed" && !testing && (
        <NoticeBox tone="warn" title="The tests could not finish this time.">
          <p className="text-meta text-ink-muted">Test again in a minute. If it keeps happening, contact us.</p>
        </NoticeBox>
      )}

      {done && counts && !testing && (
        <>
          <Summary run={done} counts={counts} history={data?.history ?? []} />

          {failing.length > 0 && (
            <FixPanel
              count={failing.length}
              canWrite={write.allowed}
              improving={improving}
              note={done.improve_note ?? null}
              hasProposal={proposal !== null}
              showReview={showReview}
              onImprove={() => askForFixes()}
              onReopen={() => setClosed(null)}
            />
          )}
          {improve.error && <ProblemNotice error={improve.error} />}

          {showReview && proposal && (
            <ImprovementReview
              agentId={agent.id}
              run={done}
              improvement={proposal}
              onClose={() => setClosed(proposal.created_at)}
              onTestAgain={start}
            />
          )}

          <Results
            results={done.results}
            canFix={write.allowed && !improving}
            onFix={(key) => askForFixes([key])}
            scriptHref={href(`/c/${slug}/agents/${agent.id}/script`)}
          />
        </>
      )}

      <section aria-labelledby="saved-tests-heading" className="space-y-2 border-t border-line pt-6">
        <h3 id="saved-tests-heading" className="text-heading text-ink">
          Your saved tests
        </h3>
        <SavedTests agentId={agent.id} canWrite={write.allowed} />
      </section>
    </div>
  );
}

function Summary({
  run,
  counts,
  history,
}: {
  run: TestRun;
  counts: ReturnType<typeof countsOf>;
  history: Parameters<typeof trendLine>[1];
}) {
  const trend = trendLine(run, history);
  const tiles: { label: string; value: number; tone: string }[] = [
    { label: "Passed", value: counts.passed, tone: "text-brand-strong" },
    { label: "Need a fix", value: counts.failing, tone: counts.failing > 0 ? "text-danger" : "text-ink" },
    { label: "Not checked", value: counts.unchecked, tone: "text-ink" },
  ];
  return (
    <section aria-labelledby="test-summary-heading" className="space-y-3">
      <h3 id="test-summary-heading" className="sr-only">
        Latest test
      </h3>
      <dl className="grid grid-cols-3 divide-x divide-line border-y border-line">
        {tiles.map((tile) => (
          <div key={tile.label} className="px-3 py-3 first:pl-0">
            <dt className="text-meta text-ink-muted">{tile.label}</dt>
            <dd className={`text-2xl font-semibold tabular-nums ${tile.tone}`}>{tile.value}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-1 text-meta text-ink-muted">
        {trend && <p>{trend}</p>}
        {run.round > 1 && <p>This run asked last time&apos;s failures again, beside new callers.</p>}
        {!run.is_current && <p className="text-ink">The script has changed since this run. Test again to check what callers hear now.</p>}
        {run.note && <p>{run.note}</p>}
      </div>
    </section>
  );
}

function FixPanel({
  count,
  canWrite,
  improving,
  note,
  hasProposal,
  showReview,
  onImprove,
  onReopen,
}: {
  count: number;
  canWrite: boolean;
  improving: boolean;
  note: string | null;
  hasProposal: boolean;
  showReview: boolean;
  onImprove: () => void;
  onReopen: () => void;
}) {
  if (improving) {
    return (
      <div role="status" aria-live="polite" className="space-y-2">
        <p className="text-body text-ink">
          <span className="text-shimmer">Working out fixes for {count === 1 ? "1 test" : `${count} tests`}…</span>
        </p>
        <p className="text-meta text-ink-muted">This takes up to two minutes. You can leave this screen; the fixes wait here.</p>
      </div>
    );
  }
  if (showReview) return null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-body text-ink">
          {count === 1 ? "1 test needs a fix." : `${count} tests need a fix.`} Get suggested changes and keep the ones you want.
        </p>
        {canWrite && (
          <button type="button" className={PRIMARY_BUTTON_SM} onClick={onImprove}>
            Improve my agent
          </button>
        )}
        {hasProposal && (
          <button type="button" className="text-meta font-medium text-ink underline underline-offset-2" onClick={onReopen}>
            Open the last suggestions
          </button>
        )}
      </div>
      {note && <NoticeBox tone="warn" title={note} />}
    </div>
  );
}

function Results({
  results,
  canFix,
  onFix,
  scriptHref,
}: {
  results: TestResult[];
  canFix: boolean;
  onFix: (key: string) => void;
  scriptHref: string;
}) {
  const failing = results.filter(isFailing);
  const unchecked = results.filter((r) => r.verdict === "unjudged");
  const passed = results.filter((r) => r.verdict === "passed");
  return (
    <div className="space-y-8">
      {failing.length > 0 && (
        <ResultGroup id="needs-fix" title="Needs a fix" results={failing} canFix={canFix} onFix={onFix} scriptHref={scriptHref} />
      )}
      {unchecked.length > 0 && (
        <ResultGroup id="read-yourself" title="Read these yourself" results={unchecked} canFix={false} onFix={onFix} scriptHref={scriptHref} />
      )}
      {passed.length > 0 && (
        <details className="group">
          <summary className="flex min-h-11 cursor-pointer items-center text-body font-medium text-ink">
            Passed ({passed.length})
          </summary>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {passed.map((result) => (
              <ResultRow key={result.key} result={result} canFix={false} onFix={onFix} scriptHref={scriptHref} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ResultGroup({
  id,
  title,
  results,
  canFix,
  onFix,
  scriptHref,
}: {
  id: string;
  title: string;
  results: TestResult[];
  canFix: boolean;
  onFix: (key: string) => void;
  scriptHref: string;
}) {
  return (
    <section aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`} className="text-heading text-ink">
        {title} <span className="font-normal text-ink-muted">({results.length})</span>
      </h3>
      <ul className="mt-2 divide-y divide-line border-y border-line">
        {results.map((result) => (
          <ResultRow key={result.key} result={result} canFix={canFix} onFix={onFix} scriptHref={scriptHref} />
        ))}
      </ul>
    </section>
  );
}

function ResultRow({
  result,
  canFix,
  onFix,
  scriptHref,
}: {
  result: TestResult;
  canFix: boolean;
  onFix: (key: string) => void;
  scriptHref: string;
}) {
  const verdict = VERDICT[result.verdict];
  const before = result.before ? VERDICT[result.before] : null;
  const todo = isFailing(result) ? lookup(WHAT_TO_DO, result.fix) : undefined;
  const tags = [
    result.probe ? PROBE_TAG : null,
    result.source === "saved" ? "Saved test" : null,
    result.source === "retest" ? "Asked again" : null,
  ].filter((tag): tag is string => tag !== null);
  return (
    <li className="space-y-3 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-body font-medium text-ink">{result.title}</p>
          {tags.length > 0 && <p className="text-meta text-ink-muted">{tags.join(" · ")}</p>}
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1.5 text-meta font-medium ${verdict.tone}`}>
          {before && before.label !== verdict.label && <span className="font-normal text-ink-muted">{before.label} →</span>}
          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${verdict.dot}`} />
          {verdict.label}
        </span>
      </div>

      <Conversation turns={result.turns} />

      {(result.reason || todo) && (
        <div className="space-y-1">
          {result.reason && (
            <p className="flex flex-wrap items-center gap-x-1.5 text-body text-ink">
              <span>{result.reason}</span>
              {result.limit && (
                <InfoTip label="what a test cannot show">
                  <p>{result.limit}</p>
                </InfoTip>
              )}
            </p>
          )}
          {result.formal_words.length > 0 && (
            <p className="text-meta text-ink-muted">Textbook words it used: {result.formal_words.join(", ")}</p>
          )}
          {todo && <p className="text-meta text-ink-muted">What to do: {todo}</p>}
          {isFailing(result) && (canFix || result.fix === "script_step") && result.fix !== "platform" && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
              {canFix && (
                <button
                  type="button"
                  className="min-h-11 text-meta font-medium text-ink underline underline-offset-2 sm:min-h-0"
                  onClick={() => onFix(result.key)}
                >
                  Suggest a fix for this
                </button>
              )}
              {result.fix === "script_step" && (
                <Link href={scriptHref} className="min-h-11 text-meta font-medium text-ink underline underline-offset-2 sm:min-h-0">
                  Open the script
                </Link>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/** One test as the chat it was: the caller on the right, the agent on the left. */
function Conversation({ turns }: { turns: TestTurn[] }) {
  return (
    <ol className="space-y-2" aria-label="The conversation">
      {turns.map((turn, index) => (
        <li key={index} className="space-y-2">
          <Bubble who="Caller" text={turn.said} side="right" />
          <Bubble who="Agent" text={turn.reply} side="left" actions={turn.actions ?? []} />
        </li>
      ))}
    </ol>
  );
}

function Bubble({
  who,
  text,
  side,
  actions = [],
}: {
  who: "Caller" | "Agent";
  text: string;
  side: "left" | "right";
  actions?: NonNullable<TestTurn["actions"]>;
}) {
  const language = text ? languageOf(text) : null;
  const right = side === "right";
  return (
    <div className={`flex ${right ? "justify-end" : "justify-start"}`}>
      <div className={`flex min-w-0 max-w-[85%] flex-col gap-1 sm:max-w-[75%] ${right ? "items-end" : "items-start"}`}>
        <p className="px-1 text-meta text-ink-muted">
          <span className="font-medium">{who}</span>
          {language && <span> · {language}</span>}
        </p>
        <p
          className={`whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-body ${
            right ? "bg-ink/[0.05] text-ink" : "border border-line bg-surface text-ink"
          }`}
        >
          {text || <span className="text-ink-muted">(said nothing)</span>}
        </p>
        {actions.length > 0 && (
          <p className="px-1 text-meta text-ink-muted">{actions.map((a) => lookup(ACTION_LABEL, a) ?? ACTION_LABEL.other).join(" · ")}</p>
        )}
      </div>
    </div>
  );
}
