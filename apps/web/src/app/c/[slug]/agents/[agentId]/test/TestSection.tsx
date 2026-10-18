"use client";

/**
 * PRACTICE TESTS — the agent callers hear now is asked the questions real callers asked, the
 * owner's saved tests and the four rules every agent keeps, each test tried several times
 * (D-724, rebuilt by D-823 and D-828). It sits behind the "Practice callers" disclosure at the
 * foot of the Training tab and declares its copilot surface only while open (`declare`).
 *
 * The screen answers three questions, in this order, with one primary action at a time:
 *
 * 1. How is my agent doing? One sentence: right every time on N of M tests, or, after "Test
 *    again", what changed on the same tests ("2 fixed, 1 newly broken").
 * 2. What do I do next? The one action that moves it: run the tests, let Pip suggest fixes,
 *    or undo a change that broke a test. "Test again" is always beside it, quieter.
 * 3. Which tests? A short list, the ones needing the owner first, each a plain verdict
 *    ("Right every time", "Not reliable yet", "Needs a fix") that opens to the
 *    conversation, try by try.
 *
 * What is ours to fix (a rule we keep for every agent, how replies sounded) is one quiet note,
 * outside the score: the owner cannot change it, so it never sinks their result (D-828).
 */

import Link from "next/link";
import { useState } from "react";

import { InfoTip } from "@/components/console/infoTip";
import { PipMark } from "@/components/illustration/pip";
import { ProgressBar } from "@/components/interior/progress-bar";
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
  useMarkTestWrong,
  useRestoreVersion,
  useRunTestConversations,
  useTestConversations,
  type RunTestsBody,
  type TestConversations,
  type TestResult,
  type TestRun,
  type TestTurn,
} from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { ImprovementReview } from "../script/ImprovementReview";
import { CALL_HANDLING_ANCHOR } from "../sections/settingsTab";
import {
  ACTION_LABEL,
  CHANGE,
  MOSTLY_RIGHT,
  SETTING_LINK,
  STANDING,
  WHAT_TO_DO,
  countsOf,
  headlineOf,
  isFixable,
  languageOf,
  oursNote,
  ownerOf,
  setLine,
  standingOf,
  triesLine,
  type Headline,
} from "./testCopy";

/** What Pip is asked for the fixes, in the words the owner sees in its ask box (D-820). */
export const FIX_ALL_REQUEST = "Suggest fixes for the tests this agent failed.";
export const fixOneRequest = (title: string) => `Suggest a fix for this agent's failed test “${title}”.`;

const TAG: Record<string, string> = {
  real: "From a real call",
  saved: "Your saved test",
  generated: "Practice caller",
};
const PROBE_TAG = "A rule every agent keeps";

const HEADLINE_DOT: Record<Headline["tone"], string> = {
  ok: "bg-brand-strong",
  warn: "bg-warn",
  stop: "bg-danger",
  neutral: "bg-ink-faint",
};

export function TestSection({
  agent,
  slug,
  declare = true,
}: {
  agent: Pick<Agent, "id">;
  slug: string;
  /** Whether this panel is on screen and so the one the assistant should see. */
  declare?: boolean;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const tests = useTestConversations(session, agent.id);
  const run = useRunTestConversations(session, agent.id);
  const markWrong = useMarkTestWrong(session, agent.id);
  const restore = useRestoreVersion(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "test and improve this agent");
  const [closed, setClosed] = useState<string | null>(null);

  const data = tests.data;
  const latest = data?.latest ?? null;
  const testing = latest?.status === "queued" || latest?.status === "running" || run.isPending;
  const done = latest?.status === "done" ? latest : null;
  const fixable = done ? done.results.filter(isFixable) : [];
  const counts = done ? countsOf(done.results) : null;
  const improving = done?.improving === true;
  const proposal = done?.improvement ?? null;
  const showReview = done !== null && proposal !== null && !improving && closed !== proposal.created_at;

  useCopilotSurface(
    declare
      ? {
          route: "/c/{slug}/agents/{id}",
          title: "Agent: practice tests",
          realm: "client",
          fields: [],
          facts: [
            { key: "agent_id", label: "Agent id", value: agent.id },
            {
              key: "state",
              label: "What is on screen",
              value: counts
                ? `the latest test: ${counts.passed} right every time, ${counts.failing} not yet (${counts.unreliable} of them right only sometimes), ${counts.unchecked} for the owner to read, ${counts.ours} on our side`
                : testing
                  ? "a test is running"
                  : "no finished test yet",
            },
            {
              key: "what_is_here",
              label: "What this section does",
              value:
                "each test is tried several times against the agent callers hear now; 'Test again' asks the same tests so before and after compare; failures the script or knowledge can fix become suggested fixes",
            },
            // Pip's `agent_tests_fix` names the failures to fix by these keys: only those the
            // script or the knowledge owns and that failed on most of their tries.
            ...(fixable.length > 0
              ? [
                  {
                    key: "failed_tests",
                    label: "Tests the script can fix (key: title)",
                    value: fixable.map((r) => `${r.key}: ${r.title}`).join("; "),
                  },
                ]
              : []),
          ],
          apply: noFill,
        }
      : null,
  );

  const start = (body: RunTestsBody) => run.mutate(body);
  const testAgain = () => done && start({ retest_of: done.id, auto_improve: done.auto_improve });
  const askForFixes = (key?: string) => {
    setClosed(null);
    const title = key ? fixable.find((r) => r.key === key)?.title : undefined;
    openAssistant({ prompt: title ? fixOneRequest(title) : FIX_ALL_REQUEST });
  };

  const links = {
    script: href(`/c/${slug}/agents/${agent.id}?section=script`),
    handover: href(`/c/${slug}/agents/${agent.id}?section=${SETTING_LINK.handover.section}#${CALL_HANDLING_ANCHOR}`),
    agreements: href(`/c/${slug}/agreements`),
  };
  const canRun = data?.available === true && write.allowed && !testing;

  return (
    <div className="max-w-3xl space-y-6">
      {data?.waiting_update && (
        <NoticeBox
          tone="warn"
          title={data.waiting_update}
          action={
            <Link href={links.agreements} className="text-meta font-medium text-ink underline underline-offset-2">
              Open agreements
            </Link>
          }
        />
      )}
      {data && !data.available && <p className="text-body text-ink-muted">{data.unavailable_reason}</p>}
      <RestrictionNote reason={write.reason} />

      {tests.isLoading && <Skeleton rows={4} />}
      {tests.error && <ProblemNotice error={tests.error} onRetry={() => void tests.refetch()} />}

      {data && (
        <>
          {testing ? (
            <Running run={latest} trials={data.trials ?? 3} />
          ) : latest?.status === "failed" ? (
            <Stopped
              run={latest}
              canRun={canRun}
              onRetry={() => start(latest.retest_of ? { retest_of: latest.retest_of } : {})}
            />
          ) : done ? (
            <Summary
              run={done}
              data={data}
              canRun={canRun}
              canWrite={write.allowed}
              fixable={fixable.length}
              improving={improving}
              hasProposal={proposal !== null}
              showingReview={showReview}
              restoring={restore.isPending}
              restored={restore.isSuccess}
              scriptHref={links.script}
              onTestAgain={testAgain}
              onNewSet={(practice) => start({ practice_callers: practice })}
              onFix={() => askForFixes()}
              onReopen={() => setClosed(null)}
              onUndo={(version) => restore.mutate(version)}
            />
          ) : (
            <FirstRun data={data} canRun={canRun} onRun={() => start({})} />
          )}
          {run.error && <ProblemNotice error={run.error} />}
          {restore.error && <ProblemNotice error={restore.error} />}
        </>
      )}

      {done && !testing && (
        <>
          {showReview && proposal && (
            <ImprovementReview
              agentId={agent.id}
              run={done}
              improvement={proposal}
              onClose={() => setClosed(proposal.created_at)}
              onTestAgain={testAgain}
            />
          )}
          {markWrong.error && <ProblemNotice error={markWrong.error} />}
          <Results
            run={done}
            actions={{
              canFix: write.allowed && !improving,
              onFix: (key) => askForFixes(key),
              canMarkWrong: write.allowed && !markWrong.isPending,
              onMarkWrong: (key) => markWrong.mutate({ runId: done.id, key }),
              links,
            }}
          />
        </>
      )}
    </div>
  );
}

// --- the top of the section: one state, one primary action ---------------------------------

function HowItWorks({ data }: { data: TestConversations }) {
  const trials = data.trials ?? 3;
  return (
    <InfoTip label="how testing works" align="start">
      <p>
        Your agent is asked the questions it struggled with on real calls, your saved tests, and four rules every
        agent keeps: saying it is an AI, whether the call is recorded, stopping calls when asked, and handing over to
        a person.
      </p>
      <p className="mt-2">
        Each test is tried {trials} times, because an agent does not answer the same caller the same way every time.
        A test counts as right only when it is right every time.
      </p>
      <p className="mt-2">
        “Test again” asks exactly the same tests, so you can see what your changes fixed. New saved tests join when you
        add them.
      </p>
      <p className="mt-2">{data.cost_note}</p>
    </InfoTip>
  );
}

function FirstRun({ data, canRun, onRun }: { data: TestConversations; canRun: boolean; onRun: () => void }) {
  if (!data.available) return null;
  return (
    <section aria-labelledby="tests-first-heading" className="space-y-3">
      <div className="flex items-start gap-2">
        <h4 id="tests-first-heading" className="text-title text-ink">
          Check your agent before your callers do
        </h4>
        <HowItWorks data={data} />
      </div>
      <p className="max-w-prose text-body text-ink-muted">
        It is asked what real callers ask, {data.trials ?? 3} times each, and you see which answers it gets right every
        time. It takes a few minutes; you can leave this page.
      </p>
      <button type="button" className={PRIMARY_BUTTON_SM} disabled={!canRun} onClick={onRun}>
        Run the tests
      </button>
    </section>
  );
}

function Running({ run, trials }: { run: TestRun | null; trials: number }) {
  const total = run?.trials ?? trials;
  const doneTries = run?.trials_done ?? 0;
  return (
    <section aria-labelledby="tests-running-heading" className="space-y-3" role="status" aria-live="polite">
      <h4 id="tests-running-heading" className="text-title text-ink">
        Testing your agent
      </h4>
      <ProgressBar
        value={run?.status === "running" ? doneTries : null}
        max={total}
        label={run?.status === "running" ? `Try ${Math.min(doneTries + 1, total)} of ${total}` : "Starting"}
        pendingLabel="Starting"
        completeLabel="Finishing"
      />
      <p className="text-meta text-ink-muted">
        Each try asks every test once. This takes a few minutes; you can leave this page and come back.
      </p>
    </section>
  );
}

function Stopped({ run, canRun, onRetry }: { run: TestRun; canRun: boolean; onRetry: () => void }) {
  const why =
    run.error_code === "stalled"
      ? "It stopped answering part-way, so we stopped it."
      : "Something on our side stopped it before it finished. Nothing about your agent was judged.";
  return (
    <NoticeBox
      tone="warn"
      title="The test did not finish"
      role="alert"
      action={
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canRun} onClick={onRetry}>
          Try again
        </button>
      }
    >
      <p className="text-meta text-ink-muted">{why}</p>
    </NoticeBox>
  );
}

function Summary({
  run,
  data,
  canRun,
  canWrite,
  fixable,
  improving,
  hasProposal,
  showingReview,
  restoring,
  restored,
  scriptHref,
  onTestAgain,
  onNewSet,
  onFix,
  onReopen,
  onUndo,
}: {
  run: TestRun;
  data: TestConversations;
  canRun: boolean;
  canWrite: boolean;
  /** Failures the script or knowledge can fix, failing on most tries. */
  fixable: number;
  improving: boolean;
  hasProposal: boolean;
  showingReview: boolean;
  restoring: boolean;
  restored: boolean;
  scriptHref: string;
  onTestAgain: () => void;
  onNewSet: (practice: boolean) => void;
  onFix: () => void;
  onReopen: () => void;
  onUndo: (version: number) => void;
}) {
  const headline = headlineOf(run);
  const counts = countsOf(run.results);
  const broke = run.comparison && run.comparison.broken > 0 ? run.comparison.with_version : null;
  // One primary action: undo a change that broke a test, else ask for fixes, else nothing
  // louder than "Test again".
  const primary: "undo" | "fix" | null =
    broke !== null && canWrite && !restored ? "undo" : fixable > 0 && canWrite && !hasProposal && !improving ? "fix" : null;
  const waiting = data.waiting_tests ?? 0;

  return (
    <section aria-labelledby="tests-summary-heading" className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-start gap-2.5">
          <span aria-hidden className={`mt-2.5 h-2 w-2 shrink-0 rounded-full ${HEADLINE_DOT[headline.tone]}`} />
          <h4 id="tests-summary-heading" className="text-title text-ink [text-wrap:pretty]">
            {headline.title}
          </h4>
          <HowItWorks data={data} />
        </div>
        {headline.detail && <p className="pl-[18px] text-body text-ink">{headline.detail}</p>}
        <p className="pl-[18px] text-meta text-ink-muted">
          {setLine(run)}
          {!run.is_current && " The script has changed since, so test again to check what callers hear now."}
        </p>
      </div>

      <ScoreStrip counts={counts} />

      {improving ? (
        <p role="status" aria-live="polite" className="text-body text-ink">
          <span className="text-shimmer">
            Working out fixes for {fixable === 1 ? "1 test" : `${fixable} tests`}…
          </span>{" "}
          <span className="text-meta text-ink-muted">Up to two minutes. You can leave; they wait here.</span>
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {primary === "undo" && broke !== null && (
            <button type="button" className={PRIMARY_BUTTON_SM} disabled={restoring} onClick={() => onUndo(broke)}>
              {restoring ? "Undoing…" : "Undo the last change"}
            </button>
          )}
          {primary === "fix" && (
            <button type="button" className={PRIMARY_BUTTON_SM} onClick={onFix}>
              <PipMark size={16} className="shrink-0" />
              Let {ASSISTANT_NAME} suggest fixes
            </button>
          )}
          <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canRun} onClick={onTestAgain}>
            Test again
          </button>
          {hasProposal && !showingReview && (
            <button type="button" className={TEXT_ACTION} onClick={onReopen}>
              Open the suggested fixes
            </button>
          )}
          {waiting > 0 && (
            <button type="button" className={TEXT_ACTION} disabled={!canRun} onClick={() => onNewSet(false)}>
              Add {waiting === 1 ? "1 new test" : `${waiting} new tests`}
            </button>
          )}
          {data.practice_offered && (
            <button type="button" className={TEXT_ACTION} disabled={!canRun} onClick={() => onNewSet(true)}>
              Add practice callers
            </button>
          )}
        </div>
      )}

      {primary === "undo" && (
        <p className="text-meta text-ink-muted">
          A change since the last test broke{" "}
          {run.comparison?.broken === 1 ? "a test that was right" : "tests that were right"}.
          Undo puts the earlier script in your draft; callers keep the current one until you put it live.
        </p>
      )}
      {restored && (
        <NoticeBox
          tone="ok"
          title="The earlier script is in your draft"
          action={
            <Link href={scriptHref} className="text-meta font-medium text-ink underline underline-offset-2">
              Open the script
            </Link>
          }
        >
          <p className="text-meta text-ink-muted">Put it live from the Script tab, then test again.</p>
        </NoticeBox>
      )}
      {run.improve_note && !improving && <NoticeBox tone="warn" title={run.improve_note} />}
      {run.note && <p className="text-meta text-ink-muted">{run.note}</p>}
    </section>
  );
}

const TEXT_ACTION =
  "touch:min-h-11 text-meta font-medium text-ink underline underline-offset-2 disabled:cursor-not-allowed disabled:text-ink-faint";

/**
 * The owner's score as one bar: right every time, right sometimes, not right. Each test is one
 * equal segment, so a short set reads as countable blocks rather than a percentage; the words
 * under it carry the same numbers, and colour is never the only cue.
 */
function ScoreStrip({ counts }: { counts: ReturnType<typeof countsOf> }) {
  const notRight = counts.failing - counts.unreliable;
  const segments = [
    ...Array.from({ length: counts.passed }, () => "bg-brand-strong"),
    ...Array.from({ length: counts.unreliable }, () => "bg-warn"),
    ...Array.from({ length: notRight }, () => "bg-danger"),
  ];
  if (segments.length === 0) return null;
  return (
    <div className="space-y-1.5 pl-[18px]">
      <div aria-hidden className="flex h-2 gap-0.5 overflow-hidden rounded-full">
        {segments.map((tone, index) => (
          <span key={index} className={`h-full flex-1 ${tone}`} />
        ))}
      </div>
      <p className="text-meta text-ink-muted">
        {[
          `${counts.passed} right every time`,
          counts.unreliable > 0 ? `${counts.unreliable} not reliable yet` : null,
          notRight > 0 ? `${notRight} need a fix` : null,
        ]
          .filter(Boolean)
          .join(", ")}
      </p>
    </div>
  );
}

// --- the tests -------------------------------------------------------------------------

interface ResultLinks {
  script: string;
  handover: string;
  agreements: string;
}

interface RowActions {
  canFix: boolean;
  onFix: (key: string) => void;
  canMarkWrong: boolean;
  onMarkWrong: (key: string) => void;
  links: ResultLinks;
}

function Results({ run, actions }: { run: TestRun; actions: RowActions }) {
  const by = (places: readonly string[]) => run.results.filter((r) => places.includes(standingOf(r)));
  const attention = by(["broken", "unreliable", "setting"]);
  const read = by(["check"]);
  const works = by(["works"]);
  const ours = by(["ours"]);
  const wrong = by(["wrong"]);
  const quiet = { ...actions, canFix: false, canMarkWrong: false };
  const note = oursNote(run);
  return (
    <div className="space-y-6">
      {attention.length > 0 && (
        <ResultGroup id="tests-attention" title="Needs your attention" rows={attention} actions={actions} />
      )}
      {read.length > 0 && <ResultGroup id="tests-read" title="Read these yourself" rows={read} actions={quiet} />}
      {works.length > 0 && <FoldedGroup title="Right every time" rows={works} actions={quiet} open={attention.length === 0} />}
      {note && (
        <section aria-labelledby="tests-ours-heading" className="rounded-card bg-surface-muted px-4 py-3">
          <h5 id="tests-ours-heading" className="text-meta font-semibold text-ink">
            On our side
          </h5>
          <p className="mt-1 max-w-prose text-meta text-ink-muted">{note}</p>
          {ours.length > 0 && (
            <details className="group/fold mt-1">
              <summary className="flex touch:min-h-11 cursor-pointer list-none items-center gap-1.5 text-meta font-medium text-ink [&::-webkit-details-marker]:hidden">
                <Chevron className="group-open/fold:rotate-90" />
                See {ours.length === 1 ? "the test" : `the ${ours.length} tests`}
              </summary>
              <ul className="mt-2 divide-y divide-line border-y border-line">
                {ours.map((r) => (
                  <ResultRow key={r.key} result={r} actions={quiet} />
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
      {wrong.length > 0 && <FoldedGroup title="Marked wrong" rows={wrong} actions={quiet} open={false} />}
    </div>
  );
}

function ResultGroup({ id, title, rows, actions }: { id: string; title: string; rows: TestResult[]; actions: RowActions }) {
  return (
    <section aria-labelledby={`${id}-heading`}>
      <h5 id={`${id}-heading`} className="text-heading text-ink">
        {title} <span className="font-normal text-ink-muted">{rows.length}</span>
      </h5>
      <ul className="mt-2 divide-y divide-line border-y border-line">
        {rows.map((r) => (
          <ResultRow key={r.key} result={r} actions={actions} />
        ))}
      </ul>
    </section>
  );
}

function FoldedGroup({ title, rows, actions, open }: { title: string; rows: TestResult[]; actions: RowActions; open: boolean }) {
  return (
    <details open={open} className="group/fold">
      <summary className="flex touch:min-h-11 cursor-pointer list-none items-center gap-2 text-heading text-ink [&::-webkit-details-marker]:hidden">
        <Chevron className="group-open/fold:rotate-90" />
        {title} <span className="font-normal text-ink-muted">{rows.length}</span>
      </summary>
      <ul className="mt-2 divide-y divide-line border-y border-line">
        {rows.map((r) => (
          <ResultRow key={r.key} result={r} actions={actions} />
        ))}
      </ul>
    </details>
  );
}

function Chevron({ className = "" }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className={`h-3.5 w-3.5 shrink-0 text-ink-muted transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none ${className}`}
    >
      <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const LINK_CLASS = "touch:min-h-11 text-meta font-medium text-ink underline underline-offset-2";

/**
 * One test: a single line closed (what it is, its verdict, what changed), the conversation
 * and what to do on open. Native `details`, so it opens by keyboard and needs no script.
 */
function ResultRow({ result, actions }: { result: TestResult; actions: RowActions }) {
  const place = standingOf(result);
  const look = STANDING[place];
  const change = result.change ? CHANGE[result.change] : null;
  const owner = ownerOf(result);
  const tag = result.probe ? PROBE_TAG : (lookup(TAG, result.source) ?? null);
  const attention = place === "broken" || place === "unreliable" || place === "setting";
  const todo =
    place === "unreliable" && !isFixable(result)
      ? MOSTLY_RIGHT
      : owner && place !== "works" && place !== "check"
        ? WHAT_TO_DO[owner]
        : undefined;
  const setting = owner === "setting" ? result.setting : null;
  const tries = result.tries && result.tries.length > 0 ? result.tries : [{ verdict: result.verdict, reason: result.reason, turns: result.turns }];
  const firstFailing = Math.max(0, tries.findIndex((t) => t.verdict === "failed" || t.verdict === "needs_fix"));
  const [shown, setShown] = useState(firstFailing);
  const current = tries[Math.min(shown, tries.length - 1)];
  const triesText = triesLine(result);

  return (
    <li>
      <details className="group/row">
        <summary className="flex touch:min-h-11 cursor-pointer list-none items-start gap-3 py-3 [&::-webkit-details-marker]:hidden">
          <span aria-hidden className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${look.dot}`} />
          <span className="min-w-0 flex-1">
            <span className="block text-body font-medium text-ink [overflow-wrap:anywhere]">{result.title}</span>
            {tag && <span className="block text-meta text-ink-muted">{tag}</span>}
          </span>
          <span className="flex shrink-0 flex-col items-end gap-0.5 text-right">
            <span className={`text-meta font-medium ${look.tone}`}>{look.label}</span>
            {change && (
              <span
                className={`text-meta ${result.change === "broken" ? "font-medium text-danger" : result.change === "fixed" ? "font-medium text-brand-strong" : "text-ink-muted"}`}
              >
                {change}
              </span>
            )}
          </span>
          <Chevron className="mt-1 group-open/row:rotate-90" />
        </summary>

        <div className="space-y-3 pb-4 pl-5">
          {tries.length > 1 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-meta text-ink-muted">{triesText}</span>
              <div role="group" aria-label="Tries" className="flex gap-1">
                {tries.map((t, index) => {
                  const right = t.verdict === "passed";
                  const selected = index === shown;
                  return (
                    <button
                      key={index}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => setShown(index)}
                      className={`touch:min-h-11 inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-meta ${selected ? "border-ink text-ink" : "border-line text-ink-muted"}`}
                    >
                      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${right ? "bg-brand-strong" : t.verdict === "unjudged" ? "bg-ink-faint" : "bg-danger"}`} />
                      <span>
                        Try {index + 1}
                        <span className="sr-only">
                          {right ? ", right" : t.verdict === "unjudged" ? ", not judged" : ", not right"}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <Conversation turns={current.turns} />

          {(current.reason || todo) && (
            <div className="space-y-1">
              {current.reason && (
                <p className="flex flex-wrap items-center gap-x-1.5 text-body text-ink">
                  <span>{current.reason}</span>
                  {result.limit && (
                    <InfoTip label="what a test cannot show">
                      <p>{result.limit}</p>
                    </InfoTip>
                  )}
                </p>
              )}
              {todo && <p className="text-meta text-ink-muted">{todo}</p>}
              {setting && setting.reason !== current.reason && <p className="text-meta text-ink">{setting.reason}</p>}
            </div>
          )}

          {(setting || (attention && isFixable(result) && actions.canFix) || (attention && actions.canMarkWrong)) && (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {setting && (
                <Link href={actions.links[setting.area]} className={LINK_CLASS}>
                  {SETTING_LINK[setting.area].label}
                </Link>
              )}
              {attention && isFixable(result) && actions.canFix && (
                <button type="button" className={LINK_CLASS} onClick={() => actions.onFix(result.key)}>
                  Let {ASSISTANT_NAME} suggest a fix
                </button>
              )}
              {attention && result.fix === "script_step" && (
                <Link href={actions.links.script} className={LINK_CLASS}>
                  Open the script
                </Link>
              )}
              {attention && actions.canMarkWrong && (
                <button type="button" className={LINK_CLASS} onClick={() => actions.onMarkWrong(result.key)}>
                  This test is wrong
                </button>
              )}
            </div>
          )}
        </div>
      </details>
    </li>
  );
}

/** One try as the chat it was: the caller on the right, the agent on the left. */
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
          {language && <span>, {language}</span>}
        </p>
        <p
          className={`whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-body ${
            right ? "bg-ink/[0.05] text-ink" : "border border-line bg-surface text-ink"
          }`}
        >
          {text || <span className="text-ink-muted">(said nothing)</span>}
        </p>
        {actions.length > 0 && (
          <p className="px-1 text-meta text-ink-muted">
            {actions.map((a) => lookup(ACTION_LABEL, a) ?? ACTION_LABEL.other).join(", ")}
          </p>
        )}
      </div>
    </div>
  );
}
