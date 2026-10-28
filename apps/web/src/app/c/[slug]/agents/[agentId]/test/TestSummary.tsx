"use client";

/**
 * The top of the practice tests: one verdict card. An icon, the score in a few words
 * ("2 of 5 OK"), and ONE primary button for the next thing (`nextStepOf`). Everything else on
 * it is quieter: "Test again", new tests, and "How this works", which holds what used to be
 * explanation sentences on the screen (when it ran, what OK means, earlier runs).
 *
 * Why so few words: the owners are small-business people on phones, many reading English as
 * a second language, and lower-literacy readers read every line word by word instead of
 * scanning (docs/evidence/simple-ui-research-2026-10-28.md, rows 1-6). A line we do not show
 * costs them nothing; a sentence we do show costs them all of it. The wordiness guard in `agentTestSection.test.tsx`
 * holds every default line to about 60 characters.
 *
 * A "Test again" the server refuses because nothing changed is calm guidance in the server's
 * own words, not an error: the owner did nothing wrong.
 */

import Link from "next/link";
import { CircleAlert, CircleCheck, CircleMinus, CircleX, Info, type LucideIcon } from "lucide-react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { Popover } from "@/components/arc/popover";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { PipMark } from "@/components/illustration/pip";
import { ProgressBar } from "@/components/interior/progress-bar";
import { NoticeBox, PRIMARY_BUTTON, SECONDARY_BUTTON_SM, formatIST } from "@/components/ui";
import type { TestConversations, TestRun } from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import {
  SETTING_LINK,
  countsOf,
  fixGroups,
  headlineOf,
  nextStepOf,
  progressMoved,
  progressOf,
  ranLine,
  scoreOf,
  type Headline,
  type NextStep,
  type RunCounts,
} from "./testCopy";
import type { ResultLinks } from "./TestResults";

/** The verdict's mark: a shape per tone as well as a colour, so colour is never the only cue. */
const HEADLINE_MARK: Record<Headline["tone"], LucideIcon> = {
  ok: CircleCheck,
  warn: CircleAlert,
  stop: CircleX,
  neutral: CircleMinus,
};

const HEADLINE_INK: Record<Headline["tone"], string> = {
  ok: "text-brand-strong",
  warn: "text-warn",
  stop: "text-danger",
  neutral: "text-ink-faint",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * Full width on a phone, where it is the one thing a thumb should find; its own size above
 * that. The primary uses the regular size, not `_SM`: a primary call to action deserves the
 * larger target (research row 7).
 */
const PRIMARY_WIDE = `${PRIMARY_BUTTON} w-full justify-center sm:w-auto`;
const SECONDARY_WIDE = `${SECONDARY_BUTTON_SM} flex-1 justify-center whitespace-nowrap sm:flex-none`;

/**
 * "How this works": the explanation the screen no longer prints, one short line each, behind a
 * labelled control rather than an unlabelled (i), so a reader who wants it can find it.
 */
export function HowItWorks({ data, run }: { data: TestConversations; run?: TestRun | null }) {
  const trials = data.trials ?? 3;
  // Earlier runs of the same tests, only when the score moved between them: identical full
  // bars carry nothing.
  const all = run ? (progressOf(data.history, run) ?? []) : [];
  const points = progressMoved(all) ? all.filter((point) => point.judged > 0) : [];
  return (
    <Popover
      label="How this works"
      align="start"
      className="w-80"
      trigger={
        <button type="button" className={`${TEXT_ACTION_SM} -mx-2 text-ink-muted`}>
          <Info aria-hidden className="h-4 w-4" />
          How this works
        </button>
      }
    >
      <div className="space-y-2 text-[13px] text-ink-muted">
        <ul className="space-y-1">
          <li>We ask your agent what real callers ask.</li>
          <li>We also check the rules every agent keeps.</li>
          <li>Each test runs {trials} times.</li>
          <li>OK means right every time.</li>
          <li>Sometimes OK means right only some times.</li>
          <li>Test again asks the same tests.</li>
          <li>{ASSISTANT_NAME}&apos;s fixes change nothing until you keep one.</li>
          {data.cost_note && <li>{data.cost_note}</li>}
        </ul>
        {run && (
          <p className="border-t border-line pt-2">
            {ranLine(run)}
            {run.note && <span className="block">{run.note}</span>}
          </p>
        )}
        {points.length >= 2 && (
          <ol aria-label="These tests over time" className="space-y-0.5 border-t border-line pt-2">
            {points.map((point) => (
              <li key={point.id} className="flex justify-between gap-3 tabular-nums">
                <span>{point.latest ? "This test" : formatIST(point.created_at)}</span>
                <span className={point.latest ? "font-medium text-ink" : ""}>
                  {point.passed} of {point.judged} OK
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Popover>
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
      <h4 id="tests-first-heading" className="text-title text-ink">
        Check your agent before your callers do
      </h4>
      <p className="text-body text-ink-muted">Takes a few minutes. You can leave this page.</p>
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
          Callers ask prices. Your agent has none yet.
        </NoticeBox>
      )}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
        <ActionButton
          variant="primary"
          className="w-full sm:w-auto"
          status={status}
          pendingLabel="Starting…"
          successLabel="Started"
          disabled={!canRun && status !== "pending"}
          onClick={onRun}
        >
          Run the tests
        </ActionButton>
        <HowItWorks data={data} />
      </div>
    </section>
  );
}

export function Running({ run, trials }: { run: TestRun | null; trials: number }) {
  const total = run?.trials ?? trials;
  const doneTries = run?.trials_done ?? 0;
  return (
    <section
      aria-labelledby="tests-running-heading"
      className="space-y-3 rounded-card border border-line p-4"
      role="status"
      aria-live="polite"
    >
      <h4 id="tests-running-heading" className="text-heading text-ink">
        Testing your agent
      </h4>
      <ProgressBar
        value={run?.status === "running" ? doneTries : null}
        max={total}
        label={run?.status === "running" ? `Round ${Math.min(doneTries + 1, total)} of ${total}` : "Getting ready"}
        pendingLabel="Starting"
        completeLabel="Finishing"
      />
      <p className="text-meta text-ink-muted">Takes a few minutes. You can leave this page.</p>
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
      ? "It stopped answering, so we stopped it."
      : run.error_code === "engine_test_call_not_set_up"
        ? "This agent cannot take calls yet. Contact us to set it up."
        : "A problem on our side stopped it. Nothing was judged.";
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

/**
 * The score as a tiny wordless bar: one equal segment per test, so a short set reads as
 * countable blocks. Decorative (`aria-hidden`): the verdict above already says the number, and
 * each problem is its own card below. Drawn only for a mix; one colour says nothing.
 */
function ScoreBar({ counts }: { counts: RunCounts }) {
  const sizes: [number, string][] = [
    [scoreOf(counts).right, "bg-brand-strong"],
    [counts.unreliable, "bg-warn"],
    [counts.failing - counts.unreliable, "bg-danger"],
  ];
  if (sizes.filter(([n]) => n > 0).length < 2) return null;
  const segments = sizes.flatMap(([n, tone]) => Array.from({ length: n }, () => tone));
  return (
    <div aria-hidden data-score-bar className="flex h-1.5 w-full max-w-48 gap-0.5 overflow-hidden rounded-full">
      {segments.map((tone, index) => (
        <span key={index} className={`h-full flex-1 ${tone}`} />
      ))}
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
 * The verdict card: how the agent is doing and the ONE next step (`nextStepOf`, most urgent
 * first). While Pip works out fixes the actions give way to a progress bar. A suggestion round
 * that came back with nothing is said once: as the server's notice when no fixes wait, or as
 * one short line when earlier fixes still wait (they are still the thing to do).
 */
export function Verdict(props: NextStepProps) {
  const { run, data, canRun, fixable, improving, restoring, unchanged } = props;
  const headline = headlineOf(run);
  const Mark = HEADLINE_MARK[headline.tone];
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
  const stopNote = run.improve_note && !improving ? run.improve_note : null;
  const line = stepLine(step, run, props.showingReview, stopNote !== null && props.hasProposal);
  // "Test again" leads only when the script changed since this test; otherwise it is the
  // quiet companion of whatever leads.
  const retestLeads = step === "retest" && !unchanged;
  const fixLeads = step === "fix";

  return (
    <section aria-labelledby="tests-summary-heading" className="space-y-4 rounded-card border border-line bg-surface p-4 shadow-card sm:p-5">
      <div className="flex items-center gap-3">
        <Mark aria-hidden className={`size-9 shrink-0 ${HEADLINE_INK[headline.tone]}`} strokeWidth={2} />
        <div className="min-w-0">
          <h4 id="tests-summary-heading" className="text-figure text-ink">
            {headline.title}
          </h4>
          {headline.detail && <p className="text-meta text-ink-muted">{headline.detail}</p>}
        </div>
      </div>
      <ScoreBar counts={counts} />

      {improving ? (
        <WorkingOnFixes count={fixable} />
      ) : (
        <>
          {line && <p className="text-body font-medium text-ink">{line}</p>}
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            {step === "undo" && broke !== null && (
              <ActionButton
                variant="primary"
                className="w-full sm:w-auto"
                status={props.restoreStatus ?? (restoring ? "pending" : "idle")}
                pendingLabel="Undoing…"
                successLabel="Undone"
                onClick={() => props.onUndo(broke)}
              >
                Undo last change
              </ActionButton>
            )}
            {step === "review" && !props.showingReview && (
              <button type="button" className={PRIMARY_WIDE} onClick={props.onReopen}>
                See the fixes
              </button>
            )}
            {fixLeads && props.canWrite && (
              <button type="button" className={PRIMARY_WIDE} onClick={props.onFix}>
                <PipMark size={18} className="shrink-0" />
                Fix {fixable} with {ASSISTANT_NAME}
              </button>
            )}
            {step === "setting" && firstSetting && (
              <Link href={props.links[firstSetting.area]} className={PRIMARY_WIDE}>
                {SETTING_LINK[firstSetting.area].label}
              </Link>
            )}
            {retestLeads && (
              <ActionButton
                variant="primary"
                className="w-full sm:w-auto"
                status={props.runStatus ?? "idle"}
                pendingLabel="Starting…"
                successLabel="Started"
                disabled={!canRun && props.runStatus !== "pending"}
                onClick={props.onTestAgain}
              >
                Test again
              </ActionButton>
            )}
            <div className="flex flex-wrap gap-2">
              {/* A newly broken test makes Undo lead; the fixes for tests that were already
                  failing stay one tap away beside it rather than disappearing behind it. */}
              {fixable > 0 && props.canWrite && step === "undo" && (
                <button type="button" className={SECONDARY_WIDE} onClick={props.onFix}>
                  <PipMark size={16} className="shrink-0" />
                  Fix {fixable} with {ASSISTANT_NAME}
                </button>
              )}
              {!retestLeads && (
                <ActionButton
                  variant="secondary-sm"
                  className="flex-1 sm:flex-none"
                  status={props.runStatus ?? "idle"}
                  pendingLabel="Starting…"
                  successLabel="Started"
                  disabled={!canRun && props.runStatus !== "pending"}
                  onClick={props.onTestAgain}
                >
                  Test again
                </ActionButton>
              )}
              {waiting > 0 && (
                <button type="button" className={SECONDARY_WIDE} disabled={!canRun} onClick={() => props.onNewSet(false)}>
                  Add {waiting === 1 ? "1 new test" : `${waiting} new tests`}
                </button>
              )}
              {data.practice_offered && (
                <button type="button" className={SECONDARY_WIDE} disabled={!canRun} onClick={() => props.onNewSet(true)}>
                  Add practice callers
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {unchanged && (
        <div data-server-text>
          <NoticeBox tone="neutral" role="status" title={unchanged.said}>
            {unchanged.next}
          </NoticeBox>
        </div>
      )}
      {props.restored && (
        <NoticeBox
          tone="ok"
          title="Earlier script is in your draft"
          action={
            <Link href={props.links.script} className="text-meta font-medium text-ink underline underline-offset-2">
              Open the script
            </Link>
          }
        >
          <p className="text-meta text-ink-muted">Put it live, then test again.</p>
        </NoticeBox>
      )}
      {stopNote && !props.hasProposal && (
        <div data-server-text>
          <NoticeBox
            tone={run.improve_stop === "failed" || run.improve_stop === "budget" ? "warn" : "neutral"}
            title={stopNote}
          />
        </div>
      )}
      <HowItWorks data={data} run={run} />
    </section>
  );
}

/** Pip at work: a moving bar, named for what it does. The fixes arrive in place (the screen polls). */
function WorkingOnFixes({ count }: { count: number }) {
  return (
    <div role="status" aria-live="polite" className="flex items-start gap-3">
      <PipMark size={20} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-2">
        <ProgressBar
          value={null}
          label={`${ASSISTANT_NAME} is fixing ${plural(count, "test", "tests")}`}
          pendingLabel="About 2 min"
        />
        <p className="text-meta text-ink-muted">You can leave this page.</p>
      </div>
    </div>
  );
}

/** At most one short line above the buttons, only where the button alone would not say why. */
function stepLine(step: NextStep, run: TestRun, showingReview: boolean, earlierFixes: boolean): string | null {
  switch (step) {
    case "undo":
      return `Your last change broke ${plural(run.comparison?.broken ?? 1, "test", "tests")}.`;
    case "review":
      if (earlierFixes) return "These fixes are from before.";
      return showingReview ? `${ASSISTANT_NAME}'s fixes are below.` : null;
    case "retest":
      return "The script changed since this test.";
    case "hold":
      return "Mostly OK. Best left as it is.";
    case "fix":
    case "setting":
    case "done":
      return null;
  }
}
