/**
 * The Test section's words and the small facts it derives from a run (D-748). Pure, so the
 * summary, the trend and the language labels are tested without rendering.
 */

import { formatIST } from "@/components/ui";
import type {
  FixKind,
  TestAction,
  TestHistoryEntry,
  TestOwner,
  TestResult,
  TestRun,
  TestSetting,
  TestVerdict,
} from "@/lib/api/script";
import { lookup } from "@/lib/lookup";

export const VERDICT: Record<TestVerdict, { label: string; tone: string; dot: string }> = {
  passed: { label: "Passed", tone: "text-brand-strong", dot: "bg-brand-strong" },
  needs_fix: { label: "Needs a fix", tone: "text-warn", dot: "bg-warn" },
  failed: { label: "Failed", tone: "text-danger", dot: "bg-danger" },
  unjudged: { label: "Not checked", tone: "text-ink-muted", dot: "bg-ink-faint" },
};

/** What the owner does about a failure, by who can fix it (D-823), in one line. */
export const WHAT_TO_DO: Record<TestOwner, string> = {
  script: "Change the script, or let Pip suggest the change.",
  knowledge: "Add or correct the fact in Knowledge, or let Pip suggest it.",
  setting: "Change the setting below. Nothing in the script fixes this.",
  platform: "We're fixing this. It is on our side, and nothing in your script changes it.",
  test: "You marked this test wrong, so it is left out of the score and the fixes.",
};

/** Who fixes a result stored before D-823, which carries only the kind of fix. */
const OWNER_OF_FIX: Record<FixKind, TestOwner> = {
  script_step: "script",
  objection: "script",
  style: "script",
  knowledge: "knowledge",
  settings: "setting",
  platform: "platform",
};

export function ownerOf(result: Pick<TestResult, "owner" | "fix" | "marked_wrong" | "verdict">): TestOwner | null {
  if (result.marked_wrong) return "test";
  if (result.owner) return result.owner;
  if (result.verdict === "passed") return null;
  return lookup(OWNER_OF_FIX, result.fix) ?? (isFailing(result) ? "script" : null);
}

/** Where each setting a result can point to lives, relative to the agent's page. */
export const SETTING_LINK: Record<TestSetting["area"], { label: string; section: string | null }> = {
  handover: { label: "Open call handling", section: "calls" },
  agreements: { label: "Open agreements", section: null },
};

export const ACTION_LABEL: Record<TestAction, string> = {
  knowledge: "Looked it up in knowledge",
  do_not_call: "Used its step that removes a number",
  call_back: "Used its call-back step",
  other: "Used one of its actions",
};

/** A test that did not pass and that the owner has not marked wrong. */
export function isFailing(result: Pick<TestResult, "verdict" | "marked_wrong">): boolean {
  return !result.marked_wrong && (result.verdict === "failed" || result.verdict === "needs_fix");
}

/** A failure the script or the knowledge can fix: the ones Pip suggests fixes for. */
export function isFixable(result: Pick<TestResult, "verdict" | "marked_wrong" | "owner" | "fix">): boolean {
  if (!isFailing(result)) return false;
  const owner = ownerOf(result);
  return owner === "script" || owner === "knowledge";
}

export interface RunCounts {
  passed: number;
  failing: number;
  unchecked: number;
  total: number;
}

/** Tests marked wrong are counted in none of the three, as the score leaves them out. */
export function countsOf(results: readonly Pick<TestResult, "verdict" | "marked_wrong">[]): RunCounts {
  let passed = 0;
  let failing = 0;
  let unchecked = 0;
  for (const result of results) {
    if (result.marked_wrong) continue;
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
