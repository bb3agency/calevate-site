/**
 * The Test section's words and the small facts it derives from a run (D-748). Pure, so the
 * summary, the trend and the language labels are tested without rendering.
 */

import { formatIST } from "@/components/ui";
import type { FixKind, TestAction, TestHistoryEntry, TestResult, TestRun, TestVerdict } from "@/lib/api/script";

export const VERDICT: Record<TestVerdict, { label: string; tone: string; dot: string }> = {
  passed: { label: "Passed", tone: "text-brand-strong", dot: "bg-brand-strong" },
  needs_fix: { label: "Needs a fix", tone: "text-warn", dot: "bg-warn" },
  failed: { label: "Failed", tone: "text-danger", dot: "bg-danger" },
  unjudged: { label: "Not checked", tone: "text-ink-muted", dot: "bg-ink-faint" },
};

/** What the owner does about a failure, by the kind of fix, in one line. */
export const WHAT_TO_DO: Record<FixKind, string> = {
  script_step: "Change the script step it names, or let Pip suggest the change.",
  knowledge: "Add or correct the fact in Knowledge, or let Pip suggest it.",
  objection: "Add a reply for this push-back to the script.",
  style: "Let Pip suggest better wording for the script.",
  settings: "Check this agent's settings.",
  platform: "Ours to fix, not yours: nothing in your script changes this. Contact us if it keeps happening.",
};

export const ACTION_LABEL: Record<TestAction, string> = {
  knowledge: "Looked it up in knowledge",
  do_not_call: "Used its step that removes a number",
  call_back: "Used its call-back step",
  other: "Used one of its actions",
};

export function isFailing(result: Pick<TestResult, "verdict">): boolean {
  return result.verdict === "failed" || result.verdict === "needs_fix";
}

export interface RunCounts {
  passed: number;
  failing: number;
  unchecked: number;
  total: number;
}

export function countsOf(results: readonly Pick<TestResult, "verdict">[]): RunCounts {
  let passed = 0;
  let failing = 0;
  let unchecked = 0;
  for (const result of results) {
    if (result.verdict === "passed") passed += 1;
    else if (isFailing(result)) failing += 1;
    else unchecked += 1;
  }
  return { passed, failing, unchecked, total: results.length };
}

/**
 * The trend against the run before this one, as a sentence, or null with nothing to compare.
 * Compared as a share of the tests that were checked, because two runs ask different numbers
 * of callers.
 */
export function trendLine(run: Pick<TestRun, "id" | "score">, history: readonly TestHistoryEntry[]): string | null {
  const previous = history.find((entry) => entry.id !== run.id && entry.score.judged > 0);
  if (!previous || run.score.judged === 0) return null;
  const now = run.score.passed / run.score.judged;
  const then = previous.score.passed / previous.score.judged;
  const was = `${previous.score.passed} of ${previous.score.judged} on ${formatIST(previous.created_at)}`;
  if (Math.abs(now - then) < 0.005) return `Same as last time (${was})`;
  return now > then ? `Better than last time (${was})` : `Worse than last time (${was})`;
}

const SCRIPTS: readonly { name: string; pattern: RegExp }[] = [
  { name: "Telugu", pattern: /[ఀ-౿]/g },
  { name: "Hindi", pattern: /[ऀ-ॿ]/g },
  { name: "Tamil", pattern: /[஀-௿]/g },
  { name: "Kannada", pattern: /[ಀ-೿]/g },
  { name: "Malayalam", pattern: /[ഀ-ൿ]/g },
];

/**
 * The language a line is written in, from its letters: an Indian script names its language,
 * Latin letters read as English. A code-mixed Telugu line ("ఈ call record అవుతుందా?") is
 * Telugu, because the Telugu letters are what an English line would never have. Empty or
 * symbol-only text names nothing.
 */
export function languageOf(text: string): string | null {
  for (const { name, pattern } of SCRIPTS) {
    if ((text.match(pattern) ?? []).length >= 2) return name;
  }
  return /[A-Za-z]{2,}/.test(text) ? "English" : null;
}
