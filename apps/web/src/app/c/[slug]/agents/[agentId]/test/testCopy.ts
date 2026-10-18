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

import { formatIST } from "@/components/ui";
import type {
  FixKind,
  SoundKind,
  TestAction,
  TestChange,
  TestOwner,
  TestResult,
  TestRun,
  TestSetting,
  TestStanding,
} from "@/lib/api/script";
import { lookup } from "@/lib/lookup";

/** How each place a test can sit reads to the owner, with its colour role. */
export const STANDING: Record<TestStanding, { label: string; tone: string; dot: string }> = {
  works: { label: "Right every time", tone: "text-brand-strong", dot: "bg-brand-strong" },
  unreliable: { label: "Not reliable yet", tone: "text-warn", dot: "bg-warn" },
  broken: { label: "Needs a fix", tone: "text-danger", dot: "bg-danger" },
  setting: { label: "Needs a setting", tone: "text-warn", dot: "bg-warn" },
  check: { label: "Read it yourself", tone: "text-ink-muted", dot: "bg-ink-faint" },
  ours: { label: "On our side", tone: "text-ink-muted", dot: "bg-ink-faint" },
  wrong: { label: "Marked wrong", tone: "text-ink-muted", dot: "bg-ink-faint" },
};

/** Before against after on the same test. `same` says nothing: nothing moved. */
export const CHANGE: Record<TestChange, string | null> = {
  fixed: "Fixed",
  broken: "Newly broken",
  still: "Still not right",
  same: null,
  new: "New test",
};

/** What the owner does about a test, by who can fix it (D-823), in one line. */
export const WHAT_TO_DO: Record<TestOwner, string> = {
  script: "Change the script, or let Pip suggest the change.",
  knowledge: "Teach the right answer above, or let Pip suggest it.",
  setting: "Change the setting below. Nothing in the script fixes this.",
  platform: "This is ours to fix and we have been told. It does not count against your agent.",
  test: "You marked this test wrong, so it is left out of the score and the fixes.",
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
  knowledge: "Looked it up in knowledge",
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
  const out: RunCounts = { passed: 0, failing: 0, unreliable: 0, unchecked: 0, ours: 0, total: results.length };
  for (const result of results) {
    const place = standingOf(result);
    const scored = result.counted ?? !result.probe;
    if (place === "works" && scored) out.passed += 1;
    else if (place === "broken" || place === "setting") out.failing += 1;
    else if (place === "unreliable") {
      out.failing += 1;
      out.unreliable += 1;
    } else if (place === "check") out.unchecked += 1;
    else if (place === "ours") out.ours += 1;
  }
  return out;
}

/** "Right 2 of 3 times", or null for a test with one try or none judged. */
export function triesLine(result: Pick<TestResult, "passes" | "judged_tries">): string | null {
  const judged = result.judged_tries ?? 0;
  if (judged < 2) return null;
  const passes = result.passes ?? 0;
  if (passes === judged) return `Right all ${judged} times`;
  if (passes === 0) return `Wrong all ${judged} times`;
  return `Right ${passes} of ${judged} times`;
}

export interface Headline {
  title: string;
  detail: string | null;
  tone: "ok" | "warn" | "stop" | "neutral";
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * The one sentence at the top of a finished run. A "Test again" leads with what changed on
 * the same tests; a new set leads with the score.
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
    if (moved.length === 0) {
      return {
        title: "No change on the same tests.",
        detail: `${plural(counts.passed, "test is", "tests are")} right every time, as before.${same}`,
        tone: counts.failing > 0 ? "warn" : "ok",
      };
    }
    return {
      title: `${moved.join(", ")}.`,
      detail: `On the same tests as before. ${counts.passed} of ${counts.passed + counts.failing} now right every time.${same}`,
      tone: compared.broken > 0 ? "stop" : "ok",
    };
  }
  const scored = counts.passed + counts.failing;
  if (scored === 0) {
    return {
      title: "Nothing here for your script to fix.",
      detail: counts.unchecked > 0 ? "Read the answers below yourself." : null,
      tone: "neutral",
    };
  }
  if (counts.failing === 0) {
    return {
      title: scored === 1 ? "Right every time on your one test." : `Right every time on all ${scored} of your tests.`,
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

/** The line under the headline that says which tests these are and when they ran. */
export function setLine(run: Pick<TestRun, "set_version" | "trials" | "created_at" | "prompt_version">): string {
  const tries = run.trials && run.trials > 1 ? `, each tried ${run.trials} times` : "";
  const version = run.prompt_version ? ` on script version ${run.prompt_version}` : "";
  return `Ran ${formatIST(run.created_at)}${version}${tries}.`;
}

/** The note for everything ours: rules we failed and how replies sounded. Null when none. */
export function oursNote(run: Pick<TestRun, "results" | "sounds">): string | null {
  const counts = countsOf(run.results);
  const sounds = (run.sounds ?? []).slice(0, 3).map((s) => `${SOUND[s.kind]} (${plural(s.tests, "test", "tests")})`);
  if (counts.ours === 0 && sounds.length === 0) return null;
  const parts = [
    counts.ours > 0 ? `${plural(counts.ours, "test", "tests")} failed on a rule we keep for every agent` : null,
    sounds.length > 0 ? `some answers ${sounds.join(", ")}` : null,
  ].filter((part): part is string => part !== null);
  const said = parts.join(", and ");
  return `${said.charAt(0).toUpperCase()}${said.slice(1)}. We are fixing these, and they do not count against your agent.`;
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
