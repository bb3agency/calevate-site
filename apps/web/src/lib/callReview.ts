/**
 * HOW A CALL IS READ BACK TO ITS OWNER — the words and the arithmetic behind the call log
 * and one call's review screen, kept apart from the JSX so a test drives them without a
 * render (UX-DOCTRINE §6).
 *
 * The outcome vocabulary is the founder's (first-call review, decision 6): Needs you, Call
 * back booked, Answered, Transferred, Hung up early, Missed. The server derives the tag
 * (`crm/outcomes.derive_outcome`); the words and the one-line reason are this module's
 * job, and every wire string is read through `lookup` so an unknown one shows rather than
 * vanishing.
 */

import { formatIST, formatPhone } from "@/components/ui";
import type { CallDetail, CallSummary } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

export type CallOutcome = NonNullable<CallSummary["outcome_tag"]>;
type Callback = NonNullable<CallSummary["callback"]>;
type Turn = NonNullable<CallDetail["transcript"]>[number];

/**
 * The outcomes in the order an owner works them: what needs a person first. The call
 * log's chips follow this order.
 */
export const OUTCOME_ORDER: readonly CallOutcome[] = [
  "needs_you",
  "call_back_booked",
  "answered",
  "transferred",
  "hung_up_early",
  "missed",
];

const OUTCOME_WORDS: Record<CallOutcome, { label: string; reason: string }> = {
  needs_you: {
    label: "Needs you",
    reason: "The caller wanted something the agent could not finish. Someone from your team should follow up.",
  },
  call_back_booked: {
    label: "Call back booked",
    reason: "The caller asked to be called back, and the agent booked it.",
  },
  answered: {
    label: "Answered",
    reason: "The agent handled the call. Nothing more was asked of you.",
  },
  transferred: {
    label: "Transferred",
    reason: "The agent passed the call to someone on your team.",
  },
  hung_up_early: {
    label: "Hung up early",
    reason: "The caller hung up in the first few seconds, before saying what they wanted.",
  },
  missed: {
    label: "Missed",
    reason: "The call did not connect, so nobody spoke.",
  },
};

/** The outcome in plain words; an unknown tag is printed as it came rather than dropped. */
export function outcomeLabel(tag: string | null | undefined): string | null {
  if (!tag) return null;
  const unknown = tag.replace(/_/g, " ");
  return lookup(OUTCOME_WORDS, tag)?.label ?? unknown.charAt(0).toUpperCase() + unknown.slice(1);
}

/** Statuses that end a call with no conversation, in an owner's words. */
const STATUS_WORDS: Record<string, string> = {
  no_answer: "No answer",
  busy: "Busy",
  voicemail: "Voicemail",
  failed: "Did not connect",
  in_progress: "On the line",
  queued: "Dialling",
  ringing: "Ringing",
};

/**
 * Why the call reads the way it does, in one sentence. The caller asking for a call back
 * that nobody booked is said in those words, because it is the case an owner most needs
 * to notice and the general "needs you" sentence would hide it.
 */
export function outcomeReason(
  call: Pick<CallDetail, "outcome_tag" | "callback_requested" | "callback" | "summary_state" | "status">,
): string {
  if (call.outcome_tag === "needs_you" && call.callback_requested && !call.callback) {
    return "The caller asked to be called back, and no call back was booked.";
  }
  const words = lookup(OUTCOME_WORDS, call.outcome_tag);
  if (words) return words.reason;
  if (call.status === "in_progress") return "The call is still going.";
  if (call.status !== "completed") return "The call ended before anyone spoke.";
  if (call.summary_state === "pending") return "We are still reading this call.";
  return "We could not tell how this call ended.";
}

/**
 * The words for how a call ended in a list row: the outcome when there is one, otherwise
 * the status that says why there is none.
 */
export function callResultWords(
  call: Pick<CallSummary, "status" | "outcome_tag"> & { summary_state?: CallSummary["summary_state"] },
): string {
  // A status this build has never heard of is the one worth reading: it wins over any
  // outcome rather than being hidden behind one.
  const known = lookup(STATUS_WORDS, call.status);
  if (call.status !== "completed" && known === undefined) {
    const unknown = call.status.replace(/_/g, " ");
    return unknown.charAt(0).toUpperCase() + unknown.slice(1);
  }
  if (call.status === "in_progress") return "On the line";
  const outcome = outcomeLabel(call.outcome_tag);
  if (outcome) return outcome;
  if (call.status === "completed") return call.summary_state === "pending" ? "Being read" : "No outcome";
  return known ?? call.status;
}

/** A booked call back that is still waiting after the time it was promised for. */
export function callbackOverdue(callback: Callback | null | undefined, now: Date = new Date()): boolean {
  if (!callback || callback.status !== "scheduled") return false;
  const due = Date.parse(callback.due_at);
  return Number.isFinite(due) && due < now.getTime();
}

const CALLBACK_WORDS: Record<Callback["status"], string> = {
  scheduled: "Waiting",
  dialing: "Calling now",
  completed: "Called back",
  cancelled: "Cancelled",
  refused: "Not placed",
  missed: "Not answered",
  failed: "Could not be placed",
};

/**
 * The booked call back in one line ("10 Oct, 06:03 pm · Waiting") and, when a rule
 * stopped it, the server's own sentence for why. The sentence is never reworded: it is
 * the server's (trial accounts, do-not-call, calling hours).
 */
export function callbackLine(
  callback: Callback,
  now: Date = new Date(),
): { when: string; state: string; overdue: boolean; reason: string | null } {
  const overdue = callbackOverdue(callback, now);
  return {
    when: formatIST(callback.due_at),
    state: overdue ? "Overdue" : (lookup(CALLBACK_WORDS, callback.status) ?? callback.status),
    overdue,
    reason: callback.blocked_reason ?? null,
  };
}

/**
 * Does this row ask the owner to act? Only two things do: the outcome says so, or a
 * promised call back is late. Everything else stays in the calm ink tone.
 */
export function needsAttention(
  call: Pick<CallSummary, "outcome_tag" | "callback">,
  now: Date = new Date(),
): boolean {
  return call.outcome_tag === "needs_you" || callbackOverdue(call.callback, now);
}

/** Who the call was with: the lead's name when there is one, the number otherwise. */
export function callTitle(call: Pick<CallSummary, "lead_name" | "caller_e164">): string {
  const name = call.lead_name?.trim();
  if (name) return name;
  return call.caller_e164 ? formatPhone(call.caller_e164) : "Unknown number";
}

/**
 * The second line of a call row. The headline when the server wrote one; while the
 * summary is still being written, a sentence that says so; never the last thing said.
 */
export function callRowLine(
  call: Pick<CallSummary, "headline" | "summary" | "summary_state" | "status">,
): { text: string; pending: boolean } {
  if (call.status === "in_progress") return { text: "On the line now", pending: false };
  if (call.headline) return { text: call.headline, pending: false };
  if (call.summary) return { text: call.summary, pending: false };
  if (call.status !== "completed") return { text: "No conversation", pending: false };
  if (call.summary_state === "pending") return { text: "Summary on its way", pending: true };
  if (call.summary_state === "empty") return { text: "Nothing was said on this call", pending: false };
  return { text: "No summary for this call", pending: false };
}

/** Statuses that promise no transcript and so never get a summary (`workers/pipeline.py`). */
const ENDED_WITHOUT_A_CONVERSATION = new Set(["failed", "no_answer", "busy", "voicemail"]);

/**
 * Can the pipeline still add to this call? A call is re-read while it is live, while its
 * summary is being written, and while its turns are being put into English.
 */
export function callStillFillingIn(call: CallDetail | undefined): boolean {
  if (call === undefined) return true;
  if (call.status === "in_progress") return true;
  if (ENDED_WITHOUT_A_CONVERSATION.has(call.status)) return false;
  return call.summary_state === "pending" || call.translation_state === "pending";
}

const LANGUAGE_NAMES: Record<string, string> = {
  te: "Telugu",
  hi: "Hindi",
  en: "English",
  ta: "Tamil",
  kn: "Kannada",
  ml: "Malayalam",
  mr: "Marathi",
  bn: "Bengali",
  gu: "Gujarati",
  pa: "Punjabi",
  ur: "Urdu",
  or: "Odia",
};

/** "te-IN" → "Telugu". An unknown tag is shown as the tag rather than guessed at. */
export function languageName(tag: string | null | undefined): string | null {
  if (!tag) return null;
  const base = tag.split(/[-_]/)[0]?.toLowerCase() ?? "";
  return lookup(LANGUAGE_NAMES, base) ?? tag;
}

/** The `lang` attribute for a BCP-47 tag, so the browser picks the right script font. */
export function langAttr(tag: string | null | undefined): string | undefined {
  if (!tag) return undefined;
  return tag.replace("_", "-");
}

/** One run of turns by the same speaker: the speaker word is printed once per run. */
export interface TurnGroup {
  speaker: string;
  turns: Turn[];
}

/** Consecutive turns by one speaker, grouped, in order. */
export function groupTurns(turns: readonly Turn[]): TurnGroup[] {
  const groups: TurnGroup[] = [];
  for (const turn of turns) {
    const last = groups.at(-1);
    if (last && last.speaker === turn.speaker) last.turns.push(turn);
    else groups.push({ speaker: turn.speaker, turns: [turn] });
  }
  return groups;
}

/**
 * The turn being spoken at `playheadMs`: the last turn that has started. The NEXT turn's
 * start bounds it rather than this turn's own end, which is nullable on its own and would
 * leave gaps unhighlighted between turns that are adjacent. `null` before the first turn
 * or when no turn carries a time.
 */
export function activeTurnIdx(turns: readonly Turn[], playheadMs: number | null): number | null {
  if (playheadMs === null) return null;
  let active: number | null = null;
  for (const turn of turns) {
    const at = turn.start_ms;
    if (at === null || at === undefined) continue;
    if (at <= playheadMs) active = turn.idx;
    else break;
  }
  return active;
}
