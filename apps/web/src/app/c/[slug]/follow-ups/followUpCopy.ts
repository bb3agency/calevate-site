/**
 * The words a client reads for a Follow-up's wire values, and the step tree the detail
 * screen draws. React-free so a test can drive it without a render.
 */

import type { NoticeTone } from "@/components/ui";
import type {
  FollowUpStatus,
  FollowUpStep,
  FollowUpTrigger,
} from "@/lib/api/followUps";
import { lookup } from "@/lib/lookup";

export const STATUS_WORDS: Record<FollowUpStatus, string> = {
  draft: "Not published",
  live: "On",
  paused: "Paused",
  off: "Off",
};

export const STATUS_TONES: Record<FollowUpStatus, NoticeTone> = {
  draft: "neutral",
  live: "ok",
  paused: "warn",
  off: "neutral",
};

const TRIGGER_WORDS: Record<FollowUpTrigger["kind"], string> = {
  new_lead: "A new lead arrives",
  call_ended: "A call ends",
  manual: "You start it for leads",
  lead_date: "A date on the lead",
};

const CALL_DIRECTION: Record<string, string> = {
  inbound: "An incoming call ends",
  outbound: "An outgoing call ends",
  both: "A call ends",
};

/** "What starts it", one short line. */
export function triggerWords(trigger: FollowUpTrigger): string {
  if (trigger.kind === "call_ended") {
    const base = lookup(CALL_DIRECTION, trigger.calls) ?? TRIGGER_WORDS.call_ended;
    return trigger.outcomes?.includes("missed") && trigger.outcomes.length === 1
      ? `${base}, missed`
      : base;
  }
  if (trigger.kind === "lead_date") {
    const field = trigger.field.replaceAll("_", " ");
    const offset = trigger.offset_days;
    const when =
      offset === 0
        ? "on"
        : `${Math.abs(offset)} ${Math.abs(offset) === 1 ? "day" : "days"} ${offset < 0 ? "before" : "after"}`;
    return `${when} the lead's ${field}`.replace(/^./, (c) => c.toUpperCase());
  }
  return lookup(TRIGGER_WORDS, trigger.kind) ?? trigger.kind;
}

const EXIT_WORDS: Record<string, string> = {
  answered: "Answered",
  not_reached: "Not reached",
  sent: "Sent",
  not_sent: "Not sent",
  done: "Done",
  failed: "Did not work",
  other: "Anything else",
  next: "Next",
};

/** An exit key or a business outcome key, as a label. Outcomes are the agent's own keys. */
export function exitWords(key: string): string {
  return lookup(EXIT_WORDS, key) ?? humanise(key);
}

const RESULT_WORDS: Record<string, string> = {
  answered: "Answered",
  no_answer: "No answer",
  busy: "Line busy",
  sent: "Message sent",
  done: "Done",
  failed: "Did not work",
  "blocked:dnc": "On do-not-call",
  "not_sent:no_consent": "Not sent: no consent",
  "not_sent:blocked": "Not sent: blocked",
  "not_sent:not_connected": "Not sent: WhatsApp not connected",
};

/** A run event's short result code, as words. `branch:interested` → "Went: Interested". */
export function resultWords(code: string | null): string {
  if (!code) return "Nothing yet";
  const known = lookup(RESULT_WORDS, code);
  if (known) return known;
  if (code.startsWith("branch:")) return `Went: ${exitWords(code.slice("branch:".length))}`;
  return humanise(code.replace(":", ": "));
}

const RUN_STATUS_WORDS: Record<string, string> = {
  running: "Going",
  waiting: "Waiting",
  done: "Finished",
  stopped: "Stopped",
};

export function runStatusWords(status: string): string {
  return lookup(RUN_STATUS_WORDS, status) ?? humanise(status);
}

function humanise(key: string): string {
  const words = key.replaceAll("_", " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

/** One line of the step tree: a step (or a pointer back to one already shown) at a depth. */
export type StepLine =
  | { type: "step"; step: FollowUpStep; depth: number; branch: string | null }
  | { type: "goto"; step: FollowUpStep; depth: number; branch: string | null }
  | { type: "end"; depth: number; branch: string };

/** Where a step can go next, as labelled exits. A single `next` is unlabelled. */
function exitsOf(step: FollowUpStep): [string, string | null][] {
  if (step.kind === "decide") {
    const named = Object.entries(step.on ?? {});
    return step.other !== undefined ? [...named, ["other", step.other]] : named;
  }
  if (step.exits) return Object.entries(step.exits);
  return step.next !== undefined ? [["next", step.next]] : [];
}

/**
 * The steps as the screen draws them: from the first step, a single next continues at
 * the same depth; a `decide` (or exits that part ways) indents each branch under its
 * label. A step reached twice is drawn once and pointed to after that. Steps nothing
 * reaches are appended at the top level, so the screen never hides one.
 */
export function stepLines(steps: FollowUpStep[]): StepLine[] {
  const byId = new Map(steps.map((step) => [step.id, step]));
  const seen = new Set<string>();
  const lines: StepLine[] = [];

  const walk = (id: string | null, depth: number, branch: string | null) => {
    let current: string | null = id;
    let label = branch;
    while (current) {
      const step = byId.get(current);
      if (!step) return;
      if (seen.has(step.id)) {
        lines.push({ type: "goto", step, depth, branch: label });
        return;
      }
      seen.add(step.id);
      lines.push({ type: "step", step, depth, branch: label });
      label = null;
      const exits = exitsOf(step);
      const targets = new Set(exits.map(([, target]) => target));
      if (exits.length === 0) return;
      if (targets.size === 1 && step.kind !== "decide") {
        current = exits[0][1];
        continue;
      }
      for (const [key, target] of exits) {
        if (target === null) lines.push({ type: "end", depth: depth + 1, branch: exitWords(key) });
        else walk(target, depth + 1, exitWords(key));
      }
      return;
    }
  };

  if (steps.length > 0) walk(steps[0].id, 0, null);
  for (const step of steps) if (!seen.has(step.id)) walk(step.id, 0, null);
  return lines;
}

/** The small edits a step offers, by kind (founder decision 4). */
export function editsFor(step: FollowUpStep): { wait: boolean; template: boolean; agent: boolean } {
  const plainWait =
    step.kind === "wait" &&
    step.until_field === undefined &&
    (step.minutes !== undefined || step.hours !== undefined || step.days !== undefined);
  return {
    wait: step.kind === "call" || plainWait,
    template: step.kind === "whatsapp",
    agent: step.kind === "call",
  };
}

export type WaitUnit = "minutes" | "hours" | "days";

/** A step's current wait as one number and unit, for the dialog's starting value. */
export function currentWait(step: FollowUpStep): { amount: number; unit: WaitUnit } {
  if (step.kind === "call") {
    const minutes = step.wait_minutes ?? 0;
    if (minutes > 0 && minutes % 60 === 0) return { amount: minutes / 60, unit: "hours" };
    return { amount: minutes, unit: "minutes" };
  }
  if (step.days !== undefined) return { amount: step.days, unit: "days" };
  if (step.hours !== undefined) return { amount: step.hours, unit: "hours" };
  return { amount: step.minutes ?? 0, unit: "minutes" };
}
