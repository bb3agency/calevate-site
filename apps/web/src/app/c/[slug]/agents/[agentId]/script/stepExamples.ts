import type { CallScript, StepExamples } from "@/lib/api/script";

/**
 * A STEP'S EXAMPLES (script rebuild §2.3, §3.2): per call language, 3 to 5 ways the agent
 * says the step, and one line for each hard moment. They replace the single `sounds_like`
 * line, which a step written before them still carries and the editor shows read-only.
 *
 * Pure functions, like `scriptModel`: a value in, a value out.
 */

/** The fewest and most turns a language's examples hold (§3.2: "3 to 5 normal turns"). */
export const TURNS_MIN = 3;
export const TURNS_MAX = 5;
/** Letters in one example line. The server's figure belongs in `ScriptContext.limits`; until
 * it is sent, the old example line's limit (`sounds_like_max`) is the one used. */
export const EXAMPLE_LINE_MAX = 200;

export type Moment = "confused" | "stuck" | "busy";

/** The moments a step shows: "busy" belongs to the first step only (§2.3). */
export function momentsFor(first: boolean): Moment[] {
  return first ? ["confused", "stuck", "busy"] : ["confused", "stuck"];
}

export const MOMENT_LABEL: Record<Moment, string> = {
  confused: "If they're confused",
  stuck: "If they're stuck",
  busy: "If they're busy",
};

/** Says which moment it is, in place of a sample line (the line is in the call's language). */
export const MOMENT_PLACEHOLDER: Record<Moment, string> = {
  confused: "When they ask “after what?”",
  stuck: "When they can't do it",
  busy: "When now is not a good time",
};

export const EMPTY_EXAMPLES: StepExamples = { turns: [], confused: "", stuck: "", busy: "" };

/** A language's examples with every field present, or null when it has none. */
export function examplesIn(all: Record<string, StepExamples> | undefined, tag: string): StepExamples | null {
  const held = all?.[tag];
  if (!held) return null;
  return {
    turns: [...(held.turns ?? [])],
    confused: held.confused ?? "",
    stuck: held.stuck ?? "",
    busy: held.busy ?? "",
  };
}

/** Nothing written in it: an entry the owner opened and left blank. */
export function isBlank(examples: StepExamples): boolean {
  return examples.turns.every((t) => !t.trim()) && !examples.confused.trim() && !examples.stuck.trim() && !examples.busy.trim();
}

/** Has the step any examples written, in any language. */
export function hasExamples(all: Record<string, StepExamples> | undefined): boolean {
  return exampleLanguages(all).length > 0;
}

/** The languages a step has examples in, in the order given first, then any others. */
export function exampleLanguages(all: Record<string, StepExamples> | undefined, order: readonly string[] = []): string[] {
  const written = Object.keys(all ?? {}).filter((tag) => !isBlank(examplesIn(all, tag) ?? EMPTY_EXAMPLES));
  return [...new Set([...order.filter((t) => written.includes(t)), ...written])];
}

/**
 * Fresh examples to write by hand: three empty turns, the first holding the step's old
 * example line when there is one (§3.2: "an old sounds_like is migrated into the first
 * example").
 */
export function startExamples(legacy = ""): StepExamples {
  const first = legacy.trim();
  return { ...EMPTY_EXAMPLES, turns: [first, "", ""] };
}

export function withExamples(
  all: Record<string, StepExamples> | undefined,
  tag: string,
  next: StepExamples,
): Record<string, StepExamples> {
  return { ...(all ?? {}), [tag]: next };
}

export function addTurn(examples: StepExamples): StepExamples {
  if (examples.turns.length >= TURNS_MAX) return examples;
  return { ...examples, turns: [...examples.turns, ""] };
}

export function removeTurn(examples: StepExamples, at: number): StepExamples {
  if (examples.turns.length <= TURNS_MIN || at < 0 || at >= examples.turns.length) return examples;
  return { ...examples, turns: examples.turns.filter((_, i) => i !== at) };
}

export function setTurn(examples: StepExamples, at: number, text: string): StepExamples {
  return { ...examples, turns: examples.turns.map((t, i) => (i === at ? text : t)) };
}

// --- the problems the builder holds a save for ------------------------------------------

/** The issue field for a language's whole list, one turn, or one moment. */
export const exampleField = {
  list: (tag: string) => `examples-${tag}`,
  turn: (tag: string, i: number) => `examples-${tag}-turn-${i}`,
  moment: (tag: string, m: Moment) => `examples-${tag}-${m}`,
};

export function isExampleField(field: string): boolean {
  return field.startsWith("examples-");
}

const length = (text: string) => [...text].length;

/**
 * What the server would refuse in one step's examples, by field. A language left blank is
 * no examples rather than a problem: it is dropped on save (`pruneExamples`).
 */
export function exampleProblems(
  all: Record<string, StepExamples> | undefined,
  max = EXAMPLE_LINE_MAX,
): { field: string; message: string }[] {
  const out: { field: string; message: string }[] = [];
  for (const tag of Object.keys(all ?? {})) {
    const ex = examplesIn(all, tag);
    if (!ex || isBlank(ex)) continue;
    if (ex.turns.length < TURNS_MIN) out.push({ field: exampleField.list(tag), message: `Give at least ${TURNS_MIN} ways.` });
    if (ex.turns.length > TURNS_MAX) out.push({ field: exampleField.list(tag), message: `At most ${TURNS_MAX} ways.` });
    ex.turns.forEach((turn, i) => {
      if (!turn.trim()) out.push({ field: exampleField.turn(tag, i), message: "Write this one, or remove it." });
      else if (length(turn) > max) out.push({ field: exampleField.turn(tag, i), message: `Keep it under ${max} letters.` });
    });
    for (const m of ["confused", "stuck", "busy"] as const) {
      if (length(ex[m]) > max) out.push({ field: exampleField.moment(tag, m), message: `Keep it under ${max} letters.` });
    }
  }
  return out;
}

/** The script with every language the owner left blank taken out, so none is saved empty. */
export function pruneExamples(script: CallScript): CallScript {
  if (!(script.stages ?? []).some((s) => s.examples)) return script;
  return {
    ...script,
    stages: script.stages.map((s) => {
      if (!s.examples) return s;
      const kept = Object.fromEntries(
        Object.entries(s.examples).filter(([tag]) => !isBlank(examplesIn(s.examples, tag) ?? EMPTY_EXAMPLES)),
      );
      return { ...s, examples: kept };
    }),
  };
}

// --- warnings from the checks, on the line they belong to -------------------------------

/**
 * A check's warning about one line. `path` names the line the way the server's left-out
 * parts do (`stages.<id>` for a step), extended to the line:
 * `stages.<id>.examples.<lang>.turns.<i>` or `stages.<id>.examples.<lang>.<moment>`.
 * `text`, when sent, is the line the warning was about: an edit that changes it settles it.
 */
export interface LineWarning {
  path: string;
  message: string;
  detail?: string | null;
  text?: string | null;
}

/** Where on a step a warning sits: a turn, a moment, or the language's examples as a whole. */
export type WarningSlot = { turn: number } | { moment: Moment } | null;

const EXAMPLES_PATH = /^stages\.([^.]+)\.examples\.([^.]+)(?:\.(turns)\.(\d+)|\.(confused|stuck|busy))?$/;

/** A path that belongs to a line of a step's examples. */
export function isExamplePath(path: string): boolean {
  return EXAMPLES_PATH.test(path);
}

const said = (text: string) => text.replace(/\s+/g, " ").trim();

/** The warnings on one slot of one step's examples in one language, still about its text. */
export function warningsAt(
  warnings: readonly LineWarning[],
  stageId: string,
  tag: string,
  slot: WarningSlot,
  current: string | null = null,
): LineWarning[] {
  return warnings.filter((w) => {
    const m = EXAMPLES_PATH.exec(w.path);
    if (!m || m[1] !== stageId || m[2] !== tag) return false;
    const turn = m[3] ? Number(m[4]) : null;
    const moment = (m[5] as Moment | undefined) ?? null;
    const matches =
      slot === null
        ? turn === null && moment === null
        : "turn" in slot
          ? turn === slot.turn
          : moment === slot.moment;
    if (!matches) return false;
    return w.text == null || current === null || said(w.text) === said(current);
  });
}

/** What Pip is asked when the owner presses "Let Pip write examples" on a step. */
export function examplesAsk(first: boolean): string {
  const moments = first ? "confused, stuck or busy" : "confused or stuck";
  return (
    `Write this step's examples: ${TURNS_MIN} to ${TURNS_MAX} different ways the agent says it, ` +
    `each one action, and one line each for when the caller is ${moments}. Keep the step as it is.`
  );
}
