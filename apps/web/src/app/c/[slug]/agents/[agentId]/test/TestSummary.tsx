"use client";

/**
 * The top of the practice tests: the state the agent is in and the one thing to do next.
 *
 * A finished run answers, in order: how is my agent doing (one headline, the score as a bar
 * of countable blocks, and how the same tests went on earlier runs), then what do I do next
 * (one sentence and one primary button, chosen by `nextStepOf`). "Test again" is always
 * beside it, quieter. A "Test again" the server refuses because nothing changed is calm
 * guidance in the server's own words, not an error: the owner did nothing wrong.
 */

import Link from "next/link";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { PipMark } from "@/components/illustration/pip";
import { ProgressBar } from "@/components/interior/progress-bar";
import { NoticeBox, PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM, formatIST } from "@/components/ui";
import type { TestConversations, TestRun } from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import {
  SETTING_LINK,
  countsOf,
  fixGroups,
  headlineOf,
  nextStepOf,
  progressOf,
  scoreOf,
  setLine,
  type Headline,
  type NextStep,
  type RunCounts,
  type RunPoint,
} from "./testCopy";
import type { ResultLinks } from "./TestResults";

const HEADLINE_DOT: Record<Headline["tone"], string> = {
  ok: "bg-brand-strong",
  warn: "bg-warn",
  stop: "bg-danger",
  neutral: "bg-ink-faint",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function HowItWorks({ data }: { data: TestConversations }) {
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

export function FirstRun({
  data,
  canRun,
  status = "idle",
  onRun,
  pricesHref,
}: {
  data: TestConversations;
  canRun: boolean;
  /** The run request's state, for the button. */
  status?: FeedbackStatus;
  onRun: () => void;
  /** Opens the Questions to answer list on the prices question. */
  pricesHref: string;
}) {
  if (!data.available) return null;
  const noPrices = data.missing_facts?.includes("prices") ?? false;
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
      {noPrices && (
        <NoticeBox
          tone="neutral"
          title="Add your prices first"
          action={
            <Link href={pricesHref} className="text-meta font-medium text-ink underline underline-offset-2">
              Add prices
            </Link>
          }
        >
          Callers ask what things cost, and nothing your agent knows has a price yet. Until you add them, it tells
          callers the team will confirm the price.
        </NoticeBox>
      )}
      <ActionButton
        variant="primary-sm"
        status={status}
        pendingLabel="Starting…"
        successLabel="Started"
        disabled={!canRun && status !== "pending"}
        onClick={onRun}
      >
        Run the tests
      </ActionButton>
    </section>
  );
}

export function Running({ run, trials }: { run: TestRun | null; trials: number }) {
  const total = run?.trials ?? trials;
  const doneTries = run?.trials_done ?? 0;
  return (
    <section aria-labelledby="tests-running-heading" className="space-y-3" role="status" aria-live="polite">
      <h4 id="tests-running-heading" className="text-sm font-semibold text-ink">
        Testing your agent
      </h4>
      <ProgressBar
        value={run?.status === "running" ? doneTries : null}
        max={total}
        label={run?.status === "running" ? `Try ${Math.min(doneTries + 1, total)} of ${total}` : "Getting the callers ready"}
        pendingLabel="Starting"
        completeLabel="Finishing"
      />
      <p className="text-meta text-ink-muted">
        Each try asks every test once. This takes a few minutes; you can leave this page and come back.
      </p>
    </section>
  );
}

export function Stopped({
  run,
  canRun,
  status = "idle",
  onRetry,
}: {
  run: TestRun;
  canRun: boolean;
  status?: FeedbackStatus;
  onRetry: () => void;
}) {
  const why =
    run.error_code === "stalled"
      ? "It stopped answering part-way, so we stopped it."
      : run.error_code === "engine_test_call_not_set_up"
        ? "Tests run as a phone call, and this agent is not set up to take calls yet. Contact us to set up calling for it, then test again."
        : "Something on our side stopped it before it finished. Nothing about your agent was judged.";
  return (
    <NoticeBox
      tone="warn"
      title="The test did not finish"
      role="alert"
      action={
        <ActionButton
          variant="secondary-sm"
          status={status}
          pendingLabel="Starting…"
          successLabel="Started"
          disabled={!canRun && status !== "pending"}
          onClick={onRetry}
        >
          Try again
        </ActionButton>
      }
    >
      <p className="text-meta text-ink-muted">{why}</p>
    </NoticeBox>
  );
}

/** How the agent is doing on the latest finished run. */
export function Standing({ run, data }: { run: TestRun; data: TestConversations }) {
  const headline = headlineOf(run);
  const counts = countsOf(run.results);
  const points = progressOf(data.history, run);
  return (
    <section aria-labelledby="tests-summary-heading" className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-start gap-2.5">
          <span aria-hidden className={`mt-2 h-2 w-2 shrink-0 rounded-full ${HEADLINE_DOT[headline.tone]}`} />
          <h4 id="tests-summary-heading" className="min-w-0 text-heading text-ink [text-wrap:pretty]">
            {headline.title}
          </h4>
          <HowItWorks data={data} />
        </div>
        {headline.detail && <p className="pl-[18px] text-body text-ink">{headline.detail}</p>}
        {/* Which tests these are: when they ran, and (in the run's own words) where they came from. */}
        <p className="pl-[18px] text-meta text-ink-muted">
          {setLine(run)}
          {run.note ? ` ${run.note}` : ""}
        </p>
      </div>
      <ScoreStrip counts={counts} />
      {points && <RunProgress points={points} />}
    </section>
  );
}

const SCORE_PARTS = [
  { key: "passed", tone: "bg-brand-strong", one: "right every time", many: "right every time" },
  { key: "unreliable", tone: "bg-warn", one: "not reliable yet", many: "not reliable yet" },
  { key: "notRight", tone: "bg-danger", one: "needs a fix", many: "need a fix" },
] as const;

/**
 * The owner's score as one bar: right every time, right sometimes, not right. Each test is
 * one equal segment, so a short set reads as countable blocks rather than a percentage; the
 * legend under it names each colour with its count, so colour is never the only cue.
 */
function ScoreStrip({ counts }: { counts: RunCounts }) {
  const sizes = {
    passed: scoreOf(counts).right,
    unreliable: counts.unreliable,
    notRight: counts.failing - counts.unreliable,
  };
  const segments = SCORE_PARTS.flatMap((part) => Array.from({ length: sizes[part.key] }, () => part.tone));
  if (segments.length === 0) return null;
  return (
    <div className="space-y-2 pl-[18px]">
      <div aria-hidden className="flex h-2.5 gap-0.5 overflow-hidden rounded-full">
        {segments.map((tone, index) => (
          <span key={index} className={`h-full flex-1 ${tone}`} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-meta text-ink" aria-label="Your score">
        {SCORE_PARTS.filter((part) => part.key === "passed" || sizes[part.key] > 0).map((part) => (
          <li key={part.key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className={`size-2 rounded-sm ${part.tone}`} />
            <span>
              <span className="font-medium">{sizes[part.key]}</span> {sizes[part.key] === 1 ? part.one : part.many}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The same tests on earlier runs, oldest first, so progress reads down the list. A run that
 * scored nothing of the owner's (every test a rule we keep, or ours) has no bar to draw and
 * is left out rather than shown as "0 of 0".
 */
function RunProgress({ points: all }: { points: RunPoint[] }) {
  const points = all.filter((point) => point.judged > 0);
  if (points.length < 2) return null;
  return (
    <div className="space-y-1.5 pl-[18px]">
      <p className="text-meta font-medium text-ink">These tests over time</p>
      <ol className="space-y-1" aria-label="These tests over time">
        {points.map((point) => {
          const share = point.judged > 0 ? Math.round((point.passed / point.judged) * 100) : 0;
          return (
            <li key={point.id} className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3 text-meta">
              <span className={point.latest ? "font-medium text-ink" : "text-ink-muted"}>
                {point.latest ? "This test" : formatIST(point.created_at)}
              </span>
              <span aria-hidden className="h-1.5 overflow-hidden rounded-full bg-ink/[0.08]">
                <span className="block h-full rounded-full bg-brand-strong" style={{ width: `${share}%` }} />
              </span>
              <span className={`tabular-nums ${point.latest ? "font-medium text-ink" : "text-ink-muted"}`}>
                {point.passed} of {point.judged}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export interface NextStepProps {
  run: TestRun;
  data: TestConversations;
  canRun: boolean;
  canWrite: boolean;
  fixable: number;
  improving: boolean;
  hasProposal: boolean;
  showingReview: boolean;
  restoring: boolean;
  /** Undo's state, for its button; `restoring` is its pending half. */
  restoreStatus?: FeedbackStatus;
  /** The "Test again" request's state, for its button. */
  runStatus?: FeedbackStatus;
  restored: boolean;
  links: ResultLinks;
  /** The server's words when "Test again" was refused because nothing changed. */
  unchanged: { said: string; next: string | null } | null;
  onTestAgain: () => void;
  onNewSet: (practice: boolean) => void;
  onFix: () => void;
  onReopen: () => void;
  onUndo: (version: number) => void;
}

/**
 * What to do next: ONE state, the latest. The sentence and its primary action come from
 * `nextStepOf`; "Test again" is always beside it, quieter. While Pip works out fixes the
 * block is a progress state and nothing else. A suggestion round that came back with nothing
 * says so once: as the block's notice when no fixes wait, or as one quiet line under the
 * waiting ones (they are from an earlier round, and they are still the thing to do).
 */
export function NextStepBlock(props: NextStepProps) {
  const { run, data, canRun, fixable, improving, restoring, unchanged } = props;
  const counts = countsOf(run.results);
  const settings = fixGroups(run.results).find((g) => g.group === "setting")?.rows ?? [];
  const broke = run.comparison && run.comparison.broken > 0 ? run.comparison.with_version : null;
  const step = nextStepOf({
    canWrite: props.canWrite,
    broke: broke !== null,
    restored: props.restored,
    hasProposal: props.hasProposal,
    isCurrent: run.is_current,
    fixable,
    settings: settings.length,
    failing: counts.failing,
  });
  const firstSetting = settings[0]?.setting ?? null;
  const waiting = data.waiting_tests ?? 0;
  const retestPrimary = step === "retest";
  const stopNote = run.improve_note && !improving ? run.improve_note : null;
  const earlierFixes = stopNote !== null && props.hasProposal;

  return (
    <section aria-labelledby="tests-next-heading" className="space-y-3 border-t border-line pt-5">
      <h4 id="tests-next-heading" className="text-heading text-ink">
        What to do next
      </h4>
      {improving ? (
        <WorkingOnFixes count={fixable} />
      ) : (
        <>
          <div className="space-y-1">
            <p className="max-w-prose text-body text-ink [text-wrap:pretty]">
              {sentenceOf(step, run, fixable, settings.length, props.showingReview)}
            </p>
            {earlierFixes && (
              <p className="max-w-prose text-meta text-ink-muted">
                {ASSISTANT_NAME} could not suggest new fixes on the last try, so these are from before.
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {step === "undo" && broke !== null && (
              <ActionButton
                variant="primary-sm"
                status={props.restoreStatus ?? (restoring ? "pending" : "idle")}
                pendingLabel="Undoing…"
                successLabel="Undone"
                onClick={() => props.onUndo(broke)}
              >
                Undo the last change
              </ActionButton>
            )}
            {step === "review" && !props.showingReview && (
              <button type="button" className={PRIMARY_BUTTON_SM} onClick={props.onReopen}>
                Review the fixes
              </button>
            )}
            {/* Offered whenever a test can be fixed, not only when fixing is the next step:
                a newly broken test makes Undo the lead action, and the fixes for the
                tests that were already failing must not disappear behind it. */}
            {fixable > 0 && props.canWrite && step !== "review" && step !== "retest" && (
              <button
                type="button"
                className={step === "fix" ? PRIMARY_BUTTON_SM : SECONDARY_BUTTON_SM}
                onClick={props.onFix}
              >
                <PipMark size={16} className="shrink-0" />
                Let {ASSISTANT_NAME} suggest fixes
              </button>
            )}
            {step === "setting" && firstSetting && (
              <Link href={props.links[firstSetting.area]} className={PRIMARY_BUTTON_SM}>
                {SETTING_LINK[firstSetting.area].label}
              </Link>
            )}
            <ActionButton
              variant={retestPrimary && !unchanged ? "primary-sm" : "secondary-sm"}
              status={props.runStatus ?? "idle"}
              pendingLabel="Starting…"
              successLabel="Started"
              disabled={!canRun && props.runStatus !== "pending"}
              onClick={props.onTestAgain}
            >
              Test again
            </ActionButton>
            {waiting > 0 && (
              <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canRun} onClick={() => props.onNewSet(false)}>
                Add {waiting === 1 ? "1 new test" : `${waiting} new tests`}
              </button>
            )}
            {data.practice_offered && (
              <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canRun} onClick={() => props.onNewSet(true)}>
                Add practice callers
              </button>
            )}
          </div>
        </>
      )}
      {unchanged && (
        <NoticeBox tone="neutral" role="status" title={unchanged.said}>
          {unchanged.next}
        </NoticeBox>
      )}
      {props.restored && (
        <NoticeBox
          tone="ok"
          title="The earlier script is in your draft"
          action={
            <Link href={props.links.script} className="text-meta font-medium text-ink underline underline-offset-2">
              Open the script
            </Link>
          }
        >
          <p className="text-meta text-ink-muted">Put it live from the Script tab, then test again.</p>
        </NoticeBox>
      )}
      {stopNote && !props.hasProposal && (
        <NoticeBox
          tone={run.improve_stop === "failed" || run.improve_stop === "budget" ? "warn" : "neutral"}
          title={stopNote}
        />
      )}
    </section>
  );
}

/**
 * Pip at work: a moving bar rather than a sentence, so it reads as in progress at a glance.
 * The fixes arrive in place (the screen polls), so the line under it says the person need
 * not wait here.
 */
function WorkingOnFixes({ count }: { count: number }) {
  return (
    <div role="status" aria-live="polite" className="flex items-start gap-3 rounded-card border border-line p-4">
      <PipMark size={20} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-2">
        <ProgressBar
          value={null}
          label={`Working out ${count === 1 ? "a fix" : "fixes"} for ${plural(count, "test", "tests")}`}
          pendingLabel="About 2 min"
        />
        <p className="text-meta text-ink-muted">You can leave this page. The fixes wait here for you.</p>
      </div>
    </div>
  );
}

function sentenceOf(step: NextStep, run: TestRun, fixable: number, settings: number, showingReview: boolean): string {
  switch (step) {
    case "undo":
      return `A change since the last test broke ${
        run.comparison?.broken === 1 ? "a test that was right" : "tests that were right"
      }. Undo puts the earlier script in your draft.`;
    case "review":
      return showingReview
        ? "Fixes are ready below. Keep the ones you want, then test again."
        : "Fixes are ready. Keep the ones you want, then test again.";
    case "retest":
      return "The script changed since this test. Test again to see what callers hear now.";
    case "fix":
      return `${ASSISTANT_NAME} can suggest fixes for ${plural(fixable, "test", "tests")}. Nothing changes until you keep one.`;
    case "setting":
      return `${plural(settings, "test waits", "tests wait")} on a setting. Change it, then test again.`;
    case "hold":
      return "What is left is right most of the time, so the script is best left alone. Test again after your next change.";
    case "done":
      return "Nothing to fix. Test again after you change the script or teach it something new.";
  }
}

