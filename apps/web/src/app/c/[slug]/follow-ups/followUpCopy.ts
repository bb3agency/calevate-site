/**
 * The words a client reads for a Follow-up's wire values, and the step tree the detail
 * screen draws. React-free so a test can drive it without a render.
 */

import type { NoticeTone } from "@/components/ui";
import type {
  FollowUpStarterNeed,
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
  booked: "Call booked",
  rebooked: "Call booked again",
  held_for_release: "Waiting for you to release it",
  not_placed: "Call not placed",
  waiting: "Waiting",
  waited: "Waited",
  started: "Started",
  assigned: "Given to a teammate",
  unchanged: "No change needed",
  end: "Finished",
  "blocked:dnc": "On do-not-call",
  "blocked:agent": "The agent is not on",
  // The account's calling hours have no opening to book the call into.
  "blocked:closed": "No calling hours open",
  // Why a run stopped (`follow_up_runs.end_reason`, also the stop event's result).
  do_not_call: "On do-not-call",
  replied: "They replied on WhatsApp",
  lead_won: "Lead marked won",
  lead_lost: "Lead marked lost",
  max_days: "Ran out of days",
  stopped_by_client: "Stopped by you",
  follow_up_off: "Follow-up turned off",
  lead_erased: "Lead erased",
  step_failed: "A step kept failing",
  // What started a run (the start event's result: the trigger, without its id).
  delivery: "Started: a new lead",
  manual: "Started by hand",
  call: "Started after a call",
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

/** The named exits of each kind that has them, in the order the screen draws them. */
const CALL_EXITS = ["answered", "not_reached"] as const;
const SEND_EXITS = ["sent", "not_sent"] as const;
const ACTION_EXITS = ["done", "failed"] as const;

/**
 * Where a step can go next, as labelled exits. A single `next` is unlabelled. An exit the
 * server left out is null: the lead stops there.
 */
function exitsOf(step: FollowUpStep): [string, string | null][] {
  switch (step.kind) {
    case "end":
      return [];
    case "decide":
      return [...Object.entries(step.on ?? {}), ["other", step.other ?? null]];
    case "call":
      return CALL_EXITS.map((key) => [key, step.next?.[key] ?? null]);
    case "whatsapp":
      return SEND_EXITS.map((key) => [key, step.next?.[key] ?? null]);
    case "action":
      return ACTION_EXITS.map((key) => [key, step.next?.[key] ?? null]);
    default:
      return [["next", step.next ?? null]];
  }
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

/**
 * The small edits a step offers, by kind (founder decision 4). A wait until a date on the
 * lead has no length to change, and the server refuses one (`follow_up_edit_invalid`).
 */
export function editsFor(step: FollowUpStep): { wait: boolean; template: boolean; agent: boolean } {
  const plainWait =
    step.kind === "wait" &&
    step.until_field == null &&
    (step.minutes != null || step.hours != null || step.days != null);
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
    // An exact wait carried over from the old plan wins over `wait_minutes`. The dialog
    // offers whole minutes, and saving any wait clears the seconds on the server.
    const minutes =
      step.wait_seconds != null ? Math.round(step.wait_seconds / 60) : step.wait_minutes;
    if (minutes > 0 && minutes % 60 === 0) return { amount: minutes / 60, unit: "hours" };
    return { amount: minutes, unit: "minutes" };
  }
  if (step.kind === "wait") {
    if (step.days != null) return { amount: step.days, unit: "days" };
    if (step.hours != null) return { amount: step.hours, unit: "hours" };
    return { amount: step.minutes ?? 0, unit: "minutes" };
  }
  return { amount: 0, unit: "minutes" };
}

/**
 * What a ready-made Follow-up needs that the account lacks (`needs`), as the button that
 * goes and fixes it. A team address is set on an agent's settings, so it opens Agents.
 */
export const NEED_FIXES: Record<FollowUpStarterNeed, { label: string; path: string }> = {
  outbound_agent: { label: "Set up an agent that calls", path: "agents/new" },
  whatsapp_template: { label: "Connect WhatsApp", path: "integrations" },
  team_address: { label: "Add who to tell", path: "agents" },
};
