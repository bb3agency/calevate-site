/**
 * THE CALL FLOW AS STEPS AND SCENARIOS (founder, 17 Nov 2026): each step is a column, and a
 * step holds one or more scenarios (2.1, 2.2, …), each a way that moment of the call can go.
 *
 * A scenario IS a script section (`ConversationStage`), so what the agent follows is what is
 * drawn and nothing compiles differently. `step` says which column it sits in; the list is
 * kept sorted by step, so the call order the engine reads is column by column. A scenario's
 * "next scenarios" are its branches: one per target, its condition the target's own name
 * (an owner picks where the call can go; the name says when). Pure functions, a script in and
 * a script out, like `scriptModel`.
 */

import type { CallScript } from "@/lib/api/script";

import {
  CALL_BACK,
  END,
  HAND_OVER,
  SPECIAL_TARGETS,
  addSection,
  removeSection,
  sectionsOf,
  updateSection,
  type Section,
} from "../agents/[agentId]/script/scriptModel";

/** What a way out to an end point says when it is picked as a next scenario. */
export const END_WHEN: Record<string, string> = {
  [END]: "The call is done",
  [HAND_OVER]: "They want to speak to a person",
  [CALL_BACK]: "They want a call back",
};

export const END_NAMES: Record<string, string> = {
  [END]: "End the call",
  [HAND_OVER]: "Hand to a person",
  [CALL_BACK]: "Offer a call back",
};

export const isEnd = (target: string) => (SPECIAL_TARGETS as readonly string[]).includes(target);

/**
 * Each section's step. A section with none (a script drawn before scenarios) is its own
 * step, the one after the section before it.
 */
export function stepsOf(sections: Section[]): number[] {
  const out: number[] = [];
  sections.forEach((s, i) => {
    out.push(s.step ?? (i === 0 ? 1 : out[i - 1] + 1));
  });
  return out;
}

export interface Placed {
  section: Section;
  index: number;
  step: number;
  /** Its place in its step, 1-based: the 2 of 3.2. */
  row: number;
  label: string;
}

/** The scenarios in steps, numbered "step.row" in call order. */
export function placed(sections: Section[]): Placed[] {
  const steps = stepsOf(sections);
  const seen = new Map<number, number>();
  return sections.map((section, index) => {
    const step = steps[index];
    const row = (seen.get(step) ?? 0) + 1;
    seen.set(step, row);
    return { section, index, step, row, label: `${step}.${row}` };
  });
}

/** Every section with its step written out, sorted by step (stable), steps numbered 1..n. */
function settle(script: CallScript, steps: number[]): CallScript {
  const sections = sectionsOf(script);
  const order = sections.map((s, i) => ({ s, step: steps[i], i })).sort((a, b) => a.step - b.step || a.i - b.i);
  const used = [...new Set(order.map((o) => o.step))];
  const renumber = new Map(used.map((step, i) => [step, i + 1]));
  return { ...script, stages: order.map(({ s, step }) => ({ ...s, step: renumber.get(step) ?? step })) };
}

/** The script with every section's step stored and the list in step order. */
export function normalise(script: CallScript): CallScript {
  return settle(script, stepsOf(sectionsOf(script)));
}

/**
 * A new scenario in `step`, after `after` when given (else at the end of the step). A step
 * past the last makes a new column; `newStep` puts it in a new column right after `step - 1`.
 */
export function addScenario(
  script: CallScript,
  step: number,
  opts: { after?: string; newStep?: boolean } = {},
): { script: CallScript; id: string } {
  const base = normalise(script);
  const sections = sectionsOf(base);
  let steps = stepsOf(sections);
  if (opts.newStep) steps = steps.map((n) => (n >= step ? n + 1 : n));
  const afterAt = opts.after ? sections.findIndex((s) => s.id === opts.after) : -1;
  const lastInStep = steps.reduce((at, n, i) => (n === step ? i : at), -1);
  const firstAfter = steps.findIndex((n) => n > step);
  const at = afterAt >= 0 ? afterAt + 1 : lastInStep >= 0 ? lastInStep + 1 : firstAfter >= 0 ? firstAfter : sections.length;
  const shifted = { ...base, stages: sections.map((s, i) => ({ ...s, step: steps[i] })) };
  const made = addSection(shifted, { name: freeName(sections), step }, at);
  return { script: normalise(made.script), id: made.id };
}

function freeName(sections: Section[]): string {
  const taken = new Set(sections.map((s) => s.name.trim().toLowerCase()));
  let n = 1;
  while (taken.has(`new scenario ${n}`)) n += 1;
  return `New scenario ${n}`;
}

/** Delete a scenario and every way into it; an emptied step closes up. */
export function deleteScenario(script: CallScript, id: string): CallScript {
  return normalise(removeSection(normalise(script), id));
}

/** Move a scenario to another step (at its end), or a new step after the last. */
export function moveToStep(script: CallScript, id: string, step: number): CallScript {
  const base = normalise(script);
  const sections = sectionsOf(base);
  const from = sections.findIndex((s) => s.id === id);
  if (from < 0) return script;
  const steps = stepsOf(sections);
  const rest = sections.filter((_, i) => i !== from);
  const restSteps = steps.filter((_, i) => i !== from);
  const lastInStep = restSteps.reduce((at, n, i) => (n <= step ? i : at), -1);
  rest.splice(lastInStep + 1, 0, { ...sections[from], step });
  restSteps.splice(lastInStep + 1, 0, step);
  return settle({ ...base, stages: rest }, restSteps);
}

/** Up or down within its step. */
export function shiftInStep(script: CallScript, id: string, by: -1 | 1): CallScript {
  const base = normalise(script);
  const sections = sectionsOf(base);
  const at = sections.findIndex((s) => s.id === id);
  const to = at + by;
  if (at < 0 || to < 0 || to >= sections.length || sections[to].step !== sections[at].step) return script;
  const next = [...sections];
  [next[at], next[to]] = [next[to], next[at]];
  return { ...base, stages: next };
}

/** The condition a way out to `target` says: the target scenario's name, or the end's words. */
function whenFor(sections: Section[], target: string): string {
  if (isEnd(target)) return END_WHEN[target];
  return sections.find((s) => s.id === target)?.name.trim() || "They go on";
}

/**
 * Where a scenario can go next: one way out per target, in the order given. A target it
 * already had keeps its words; a new one says the target's name.
 */
export function setNext(script: CallScript, id: string, targets: string[]): CallScript {
  const sections = sectionsOf(script);
  const source = sections.find((s) => s.id === id);
  if (!source) return script;
  const kept = new Map(source.branches.map((b) => [b.target, b]));
  const branches = [...new Set(targets)]
    .filter((t) => t !== id)
    .map((t) => kept.get(t) ?? { when: whenFor(sections, t), target: t });
  return updateSection(script, id, { branches });
}

/**
 * Rename a scenario, and the ways into it that still say its old name, so a link's words
 * follow the scenario they point at.
 */
export function renameScenario(script: CallScript, id: string, name: string): CallScript {
  const sections = sectionsOf(script);
  const old = sections.find((s) => s.id === id)?.name.trim();
  const renamed = updateSection(script, id, { name });
  if (!old) return renamed;
  return {
    ...renamed,
    stages: sectionsOf(renamed).map((s) => ({
      ...s,
      branches: s.branches.map((b) => (b.target === id && b.when.trim() === old ? { ...b, when: name.trim() || b.when } : b)),
    })),
  };
}
