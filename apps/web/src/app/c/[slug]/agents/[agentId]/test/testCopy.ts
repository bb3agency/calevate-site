/**
 * The practice tests' words and the small facts derived from a run (D-748, rebuilt by D-828).
 * Pure, so the headline, the per-test verdicts and the language labels are tested without
 * rendering.
 *
 * D-828: every test is tried several times, "Test again" asks the same tests, and the owner's
 * score counts only what their script and facts decide. The words here follow that: a test
 * is right every time, not reliable yet, or needs a fix; anything ours is said once, plainly,
 * and never counted against the agent.
 */

import { formatIST, type NoticeTone } from "@/components/ui";
import type {
  FixKind,
  SoundKind,
  TestAction,
  TestChange,
  TestHistoryEntry,
  TestOwner,
  TestResult,
  TestRun,
  TestSetting,
  TestStanding,
} from "@/lib/api/script";
import { lookup } from "@/lib/lookup";

/** How each place a test can sit reads to the owner, with its status tone. */
export const STANDING: Record<TestStanding, { label: string; tone: NoticeTone }> = {
  works: { label: "Right every time", tone: "ok" },
  unreliable: { label: "Not reliable yet", tone: "warn" },
  broken: { label: "Needs a fix", tone: "stop" },
  setting: { label: "Needs a setting", tone: "warn" },
  check: { label: "Read it yourself", tone: "neutral" },
  ours: { label: "On our side", tone: "neutral" },
  wrong: { label: "Marked wrong", tone: "neutral" },
};

/** The problem code of a "Test again" refused because nothing it is tested with moved (D-823). */
export const NOTHING_CHANGED_CODE = "agent_tests_nothing_changed";

/** What fixes a failing test, which is how the failures are grouped for the owner. */
export type FixGroup = "script" | "knowledge" | "setting";

export const FIX_GROUP: Record<FixGroup, { title: string; hint: string }> = {
  script: {
    title: "Fix in the script",
    hint: "Pip can suggest the words. Nothing changes until you keep them.",
  },
  knowledge: {
    title: "Missing an answer",
    hint: "Teach the right answer, or let Pip suggest it.",
  },
  setting: {
    title: "Fix in a setting",
    hint: "The script cannot change these. Change the setting, then test again.",
  },
};

export const FIX_GROUP_ORDER: readonly FixGroup[] = ["script", "knowledge", "setting"];

/** Which group a failing test sits in: the setting it waits on, else who can fix it. */
export function groupOf(result: ResultFacts): FixGroup {
  if (standingOf(result) === "setting") return "setting";
  return ownerOf(result) === "knowledge" ? "knowledge" : "script";
}

/** The run's failing tests, by what fixes them, in `FIX_GROUP_ORDER`; empty groups left out. */
export function fixGroups<R extends ResultFacts>(results: readonly R[]): { group: FixGroup; rows: R[] }[] {
  const failing = results.filter(isFailing);
  return FIX_GROUP_ORDER.map((group) => ({ group, rows: failing.filter((r) => groupOf(r) === group) })).filter(
    (entry) => entry.rows.length > 0,
  );
}

/** One finished run on the same tests, for the progress list. */
export interface RunPoint {
  id: string;
  created_at: string;
  passed: number;
  judged: number;
  latest: boolean;
}

/**
 * The finished runs that asked the same set of tests as `run`, oldest first and at most
 * `limit`. A score is only comparable on the same tests, so another set is left out; null
 * when there is nothing to compare (one run, or a run from before test sets had versions).
 */
export function progressOf(
  history: readonly TestHistoryEntry[],
  run: Pick<TestRun, "id" | "set_version">,
  limit = 5,
): RunPoint[] | null {
  if (run.set_version === null || run.set_version === undefined) return null;
  const same = history
    .filter((entry) => entry.set_version === run.set_version)
    .slice(0, limit)
    .reverse()
    .map((entry) => ({
      id: entry.id,
      created_at: entry.created_at,
      passed: entry.score.passed,
      judged: entry.score.judged,
      latest: entry.id === run.id,
    }));
  return same.length >= 2 ? same : null;
}

/**
 * Whether the earlier runs say anything the headline does not: some run scored a different
 * share than another. Identical full bars ("4 of 4", then "3 of 3") carry no information.
 */
export function progressMoved(points: readonly RunPoint[]): boolean {
  const shares = points.filter((p) => p.judged > 0).map((p) => p.passed / p.judged);
  return shares.length >= 2 && shares.some((share) => share !== shares[0]);
}

/**
 * The one next step at the top of a finished run, most urgent first: undo a change that
 * broke a test, review fixes already waiting, test a script that changed since, ask Pip to
 * fix what the script or knowledge owns, change a setting, or nothing beyond "Test again".
 */
export type NextStep = "undo" | "review" | "retest" | "fix" | "setting" | "hold" | "done";

export function nextStepOf(facts: {
  canWrite: boolean;
  broke: boolean;
  restored: boolean;
  hasProposal: boolean;
  isCurrent: boolean;
  fixable: number;
  settings: number;
  failing: number;
}): NextStep {
  if (facts.broke && facts.canWrite && !facts.restored) return "undo";
  if (facts.hasProposal) return "review";
  if (!facts.isCurrent) return "retest";
  if (facts.fixable > 0) return "fix";
  if (facts.settings > 0) return "setting";
  return facts.failing > 0 ? "hold" : "done";
}

/** Before against after on the same test. `same` says nothing: nothing moved. */
export const CHANGE: Record<TestChange, string | null> = {
  fixed: "Fixed",
  broken: "Newly broken",
  still: "Still not right",
  same: null,
  new: "New test",
};

/** A test right on most tries: Pip leaves it alone, so a fix never breaks what works. */
export const MOSTLY_RIGHT =
  "It was right most of the time, so Pip leaves it alone rather than risk what works. Test again after your next change to see if it holds.";

/** How the replies sounded, in the owner's words: ours to fix, never their score. */
export const SOUND: Record<SoundKind, string> = {
  formal_words: "used textbook words",
  spoken_number: "said a price the wrong way",
  money_digits: "wrote a price or quantity in digits",
  symbols: "wrote a dash or symbol the voice reads out",
  brackets: "read out something in brackets",
  time: "said the time out loud",
  too_long: "said too much in one turn",
  several_questions: "asked several questions at once",
  repeated_question: "asked the same question twice",
  unmarked_question: "asked a question that sounds like a statement",
  wrong_language: "answered in another language than the caller's",
  third_person: "talked about the caller instead of to them",
  foreign_script: "wrote letters the voice cannot say",
  repeated_turn: "repeated itself word for word",
  opened_again: "greeted again or asked again if now suits, after its opening",
  memory_not_said: "said goodbye without saying it keeps a short note of the call",
};

/** Who fixes a result stored before D-823, which carries only the kind of fix. */
const OWNER_OF_FIX: Record<FixKind, TestOwner> = {
  script_step: "script",
  objection: "script",
  style: "platform",
  knowledge: "knowledge",
  settings: "setting",
  platform: "platform",
};

/** Where each setting a result can point to lives, relative to the agent's page. */
export const SETTING_LINK: Record<TestSetting["area"], { label: string; section: string | null }> = {
  handover: { label: "Open call handling", section: "settings" },
  agreements: { label: "Open agreements", section: null },
};

export const ACTION_LABEL: Record<TestAction, string> = {
  knowledge: "Found it in what you taught",
  do_not_call: "Used its step that removes a number",
  call_back: "Used its call-back step",
  other: "Used one of its actions",
};

type ResultFacts = Pick<TestResult, "verdict" | "marked_wrong" | "owner" | "fix" | "standing" | "probe" | "counted">;

export function ownerOf(result: Pick<TestResult, "owner" | "fix" | "marked_wrong" | "verdict">): TestOwner | null {
  if (result.marked_wrong) return "test";
  if (result.owner) return result.owner;
  if (result.verdict === "passed") return null;
  return lookup(OWNER_OF_FIX, result.fix) ?? (result.verdict === "unjudged" ? null : "script");
}

/** Where a result sits. Sent by the server since D-828; read from the verdict before it. */
export function standingOf(result: ResultFacts): TestStanding {
  if (result.marked_wrong) return "wrong";
  if (result.standing) return result.standing;
  if (result.verdict === "passed") return "works";
  const owner = ownerOf(result);
  if (owner === "setting") return "setting";
  if (result.verdict === "unjudged") return "check";
  return owner === "script" || owner === "knowledge" ? "broken" : "ours";
}

/** A test that did not pass, in the owner's score or a setting's: theirs to act on. */
export function isFailing(result: ResultFacts): boolean {
  const place = standingOf(result);
  return place === "broken" || place === "unreliable" || place === "setting";
}

/**
 * A test Pip suggests fixes for: the script's or the knowledge's, and failed on most of its
 * tries, so a fix never chases one unlucky answer (the server's `reliably_failing`).
 */
export function isFixable(result: ResultFacts & Pick<TestResult, "passes" | "judged_tries">): boolean {
  const place = standingOf(result);
  if (place === "broken") return true;
  if (place !== "unreliable") return false;
  return (result.passes ?? 0) * 2 < (result.judged_tries ?? 0);
}

export interface RunCounts {
  /** In the owner's score and right on every try. */
  passed: number;
  /** Right on every try, in the score or not: the rules every agent keeps count here too. */
  works: number;
  /** In the owner's score and not right every time, or waiting on a setting. */
  failing: number;
  /** Of `failing`, right on some tries. */
  unreliable: number;
  /** Nobody could judge: for the owner to read. */
  unchecked: number;
  /** Ours to fix, outside the score. */
  ours: number;
  total: number;
}

/** The owner's counts. Rule checks, our side and tests marked wrong are counted in none. */
export function countsOf(results: readonly ResultFacts[]): RunCounts {
  const out: RunCounts = {
    passed: 0,
    works: 0,
    failing: 0,
    unreliable: 0,
    unchecked: 0,
    ours: 0,
    total: results.length,
  };
  for (const result of results) {
    const place = standingOf(result);
    const scored = result.counted ?? !result.probe;
    if (place === "works") {
      out.works += 1;
      if (scored) out.passed += 1;
    } else if (place === "broken" || place === "setting") out.failing += 1;
    else if (place === "unreliable") {
      out.failing += 1;
      out.unreliable += 1;
    } else if (place === "check") out.unchecked += 1;
    else if (place === "ours") out.ours += 1;
  }
  return out;
}

/**
 * The score the owner reads: right every time, out of the tests their script decides. A run
 * that held none of those (every test a rule we keep, or ours to fix) scores every test that
 * was right, so a run that went well never reads "0 of 0".
 */
export function scoreOf(counts: RunCounts): { right: number; of: number } {
  const scored = counts.passed + counts.failing;
  return scored > 0 ? { right: counts.passed, of: scored } : { right: counts.works, of: counts.works };
}

/** The closed "Practice callers" row's line for a finished run. */
export function lastRunLine(counts: RunCounts, fixesWaiting: boolean): string {
  const { right, of } = scoreOf(counts);
  const score = of === 0 ? "nothing to score" : right === of ? `all ${of} right` : `${right} of ${of} right`;
  const extra = [
    counts.unchecked > 0 ? `${counts.unchecked} to read` : null,
    fixesWaiting ? "fixes waiting" : null,
  ].filter((part): part is string => part !== null);
  return `Last run: ${[score, ...extra].join(", ")}.`;
}

/**
 * "Right 2 of 3 times" for a test right on some tries and not others, else null. Right or
 * wrong on every try, the row's status already says it, and saying it twice was noise.
 */
export function triesLine(result: Pick<TestResult, "passes" | "judged_tries">): string | null {
  const judged = result.judged_tries ?? 0;
  const passes = result.passes ?? 0;
  return judged >= 2 && passes > 0 && passes < judged ? `Right ${passes} of ${judged} times` : null;
}

export interface Headline {
  title: string;
  detail: string | null;
  tone: "ok" | "warn" | "stop" | "neutral";
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * The one sentence at the top of a finished run, and at most one line under it. A "Test
 * again" that moved something leads with what moved; one that moved nothing leads with the
 * score, as a new set does, and says "no change" once underneath. A "No change" headline over
 * a line restating the score said the same thing twice.
 */
export function headlineOf(run: Pick<TestRun, "comparison" | "results" | "created_at">): Headline {
  const counts = countsOf(run.results);
  const compared = run.comparison ?? null;
  if (compared && compared.fixed + compared.broken + compared.still + compared.same > 0) {
    const moved = [
      compared.fixed > 0 ? `${compared.fixed} fixed` : null,
      compared.broken > 0 ? `${compared.broken} newly broken` : null,
    ].filter((part): part is string => part !== null);
    const same = compared.same_script ? " The script was the same in both runs." : "";
    if (moved.length === 0) return { ...scoreHeadline(counts), detail: `No change since the last test.${same}` };
    return {
      title: `${moved.join(", ")} since the last test.`,
      detail: `Now right every time on ${counts.passed} of ${counts.passed + counts.failing}.${same}`,
      tone: compared.broken > 0 ? "stop" : "ok",
    };
  }
  return scoreHeadline(counts);
}

function scoreHeadline(counts: RunCounts): Headline {
  const scored = counts.passed + counts.failing;
  if (scored === 0) {
    if (counts.works > 0) {
      return {
        title: counts.works === 1 ? "Right every time on its one test." : `Right every time on all ${counts.works} tests.`,
        detail: counts.unchecked > 0 ? "Read the answers we could not judge below." : null,
        tone: "ok",
      };
    }
    return {
      title: "Nothing here for your script to fix.",
      detail: counts.unchecked > 0 ? "Read the answers below yourself." : null,
      tone: "neutral",
    };
  }
  if (counts.failing === 0) {
    // Every right test, rule checks included, so the number matches the "Right every time"
    // list under it rather than the scored count.
    return {
      title: counts.works === 1 ? "Right every time on its one test." : `Right every time on all ${counts.works} tests.`,
      detail: null,
      tone: "ok",
    };
  }
  // The breakdown is the score strip's own legend, right under this line: not repeated here.
  return {
    title: `Right every time on ${counts.passed} of your ${scored} tests.`,
    detail: null,
    tone: counts.passed === 0 ? "stop" : "warn",
  };
}

/** When the run was and what it ran on, as short facts the screen sets on one quiet line. */
export function setLine(run: Pick<TestRun, "set_version" | "trials" | "created_at" | "prompt_version">): string[] {
  return [
    `Ran ${formatIST(run.created_at)}`,
    run.prompt_version ? `script version ${run.prompt_version}` : null,
    run.trials && run.trials > 1 ? `${run.trials} tries per test` : null,
  ].filter((part): part is string => part !== null);
}

/**
 * Everything ours, as one line and the details behind it: rules we failed and how replies
 * sounded. Null when there is none. The line says the one thing the owner needs (it is not
 * theirs to fix and does not count); the details wait behind a disclosure.
 */
export function oursNote(run: Pick<TestRun, "results" | "sounds">): { line: string; details: string[] } | null {
  const counts = countsOf(run.results);
  const sounds = (run.sounds ?? []).slice(0, 3);
  if (counts.ours === 0 && sounds.length === 0) return null;
  const line =
    counts.ours > 0
      ? `${counts.ours === 1 ? "This is" : "These are"} ours to fix and ${counts.ours === 1 ? "does" : "do"} not count against your agent.`
      : "Some answers did not sound right. That is ours to fix and does not count against your agent.";
  const details = [
    counts.ours > 0 ? `Failed a rule we keep for every agent: ${plural(counts.ours, "test", "tests")}` : null,
    ...sounds.map((sound) => {
      const said = SOUND[sound.kind];
      return `${said.charAt(0).toUpperCase()}${said.slice(1)}: ${plural(sound.tests, "test", "tests")}`;
    }),
  ].filter((part): part is string => part !== null);
  return { line, details };
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
