/**
 * HOW A CALL IS READ BACK TO ITS OWNER — the words and the arithmetic behind the call log
 * and one call's review screen, kept apart from the JSX so a test drives them without a
 * render (UX-DOCTRINE §6).
 *
 * The outcome vocabulary is the founder's (first-call review, decision 6): Needs you, Call
 * back booked, Answered, Transferred, Hung up early, Missed. The server derives the tag
 * (`crm/outcomes.derive_outcome`); the words and the one-line reason are this module's
 * job, and every wire string is read through `lookup` so an unknown one shows rather than
 * vanishing. Beside it each agent has outcomes of its own business (D-836), which the
 * server sends as a label (`business_outcome_label`) and `outcomeWords` places.
 */

import { formatPhone } from "@/components/ui";
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
    reason: "The agent couldn't finish this. Someone should follow up.",
  },
  call_back_booked: {
    label: "Call-back booked",
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
    reason: "The caller hung up before saying what they wanted.",
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

type OutcomeFields = Pick<CallSummary, "outcome_tag"> & { business_outcome_label?: string | null };

/**
 * The words a call is filed under (D-836). What happened on the call comes first — Needs
 * you, Call-back booked, Transferred, Hung up early, Missed — because those are facts the
 * owner acts on. Otherwise the agent's own outcome for the business ("Wants to buy"), and
 * only then the general "Answered". Null when nothing is known yet.
 */
export function outcomeWords(call: OutcomeFields): string | null {
  if (call.outcome_tag && call.outcome_tag !== "answered") return outcomeLabel(call.outcome_tag);
  return call.business_outcome_label?.trim() || outcomeLabel(call.outcome_tag);
}

/** The agent's own outcome when a fact heads the call, so the owner reads both; else null. */
export function businessOutcomeAside(call: OutcomeFields): string | null {
  const label = call.business_outcome_label?.trim();
  if (!label) return null;
  return outcomeWords(call) === label ? null : label;
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
 * A count's key in an owner's words, for reads that group calls by outcome: the outcome
 * tag, else the call's status (`COALESCE(outcome_tag, status)`), else nothing recorded
 * (`''`, `unread`, or a completed call that was never tagged). One mapping, so a chart
 * never prints `hung_up_early` where the call log says "Hung up early".
 */
export function endingLabel(key: string | null | undefined): string {
  if (!key || key === "unread" || key === "completed") return "Not recorded";
  const known = lookup(OUTCOME_WORDS, key)?.label ?? lookup(STATUS_WORDS, key);
  if (known) return known;
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Why the call reads the way it does, in one sentence. The caller asking for a call back
 * that nobody booked is said in those words, because it is the case an owner most needs
 * to notice and the general "needs you" sentence would hide it.
 */
export function outcomeReason(
  call: Pick<CallDetail, "outcome_tag" | "callback_requested" | "callback" | "summary_state" | "status"> & {
    business_outcome_label?: string | null;
    next_step?: string | null;
    next_step_by?: CallDetail["next_step_by"];
  },
): string {
  if (call.outcome_tag === "needs_you" && call.callback_requested && !call.callback) {
    return "They asked for a call back. None is booked.";
  }
  // A next step is the reason the call needs a person whenever it is the business's to
  // take (D-887). One that waits on the caller is not why the call needs you, and pointing
  // at it put "Needs you" beside "they will message you" (4 Nov 2026 call review).
  if (call.outcome_tag === "needs_you" && call.next_step?.trim() && businessActs(call.next_step_by)) {
    return "Something is left to do. See the next step below.";
  }
  // "The agent booked it" is the in-call booking; one made after the call, or by a person,
  // was not the agent's, and saying so is what tells the owner the time may be ours.
  if (call.outcome_tag === "call_back_booked" && call.callback?.booked_by === "after_call") {
    return "They asked to talk again later, so a call back is booked.";
  }
  if (call.outcome_tag === "call_back_booked" && call.callback?.booked_by === "person") {
    return "Someone on your team booked a call back.";
  }
  const words = lookup(OUTCOME_WORDS, call.outcome_tag);
  if (words) return words.reason;
  if (call.business_outcome_label?.trim()) return "Sorted by what the caller said on the call.";
  if (call.status === "in_progress") return "The call is still going.";
  if (call.status !== "completed") return "The call ended before anyone spoke.";
  if (call.summary_state === "pending") return "We are still reading this call.";
  return "We could not tell how this call ended.";
}

/**
 * Is the next step the business's to take? A call read before the reading named who acts
 * (`next_step_by` null) keeps the older rule that any written step is the business's.
 */
function businessActs(by: CallDetail["next_step_by"] | undefined): boolean {
  return by == null || by === "business";
}

/**
 * The next step with who takes it. The step itself is the reading's sentence and is shown
 * as written; what this adds is whose move it is, because "Wait for the caller to message
 * you" under "Needs you" read as a job for the owner (4 Nov 2026 call review). A step for
 * nobody is not shown: there is nothing to do.
 */
export function nextStepLine(
  call: Pick<CallDetail, "next_step_by"> & { next_step?: string | null },
): { who: string | null; text: string; note: string | null } | null {
  const text = call.next_step?.trim();
  if (!text || call.next_step_by === "nobody") return null;
  if (call.next_step_by === "caller") return { who: null, text, note: "Up to them. Nothing for you to do." };
  if (call.next_step_by === "business") return { who: "You", text, note: null };
  return { who: null, text, note: null };
}

type Goal = NonNullable<CallDetail["goal"]>;

/** How a call did against its campaign's goal, in the words every screen uses for it. */
export const GOAL_WORDS: Record<NonNullable<Goal["reached"]>, string> = {
  yes: "Goal reached",
  no: "Goal not reached",
  unclear: "Goal unclear",
};

/**
 * The campaign goal's verdict ("Goal reached: App installed successfully") and the
 * reading's one-line why. Null when the call was not judged against it (not answered, or
 * read before goals), because "Goal: …" with no verdict reads as a result.
 */
export function goalLine(goal: CallDetail["goal"]): { verdict: string; reason: string | null } | null {
  if (!goal?.reached) return null;
  const words = lookup(GOAL_WORDS, goal.reached) ?? "Goal";
  const name = goal.goal.trim();
  return {
    verdict: name ? `${words}: ${name}` : words,
    reason: goal.reason?.trim() || null,
  };
}

/**
 * What kind of ending a call had, for the coloured mark beside its outcome. One set for
 * every screen that lists calls, so a colour means the same thing wherever it appears, and
 * one colour per kind (founder, 27 Oct 2026: a "Ready to visit" and a "Considering options"
 * both read green, so the colour said nothing about which was which):
 *
 * - `hot`           the agent's own outcome moves the lead to hot ("Ready to visit")
 * - `interested`    it moves the lead to interested ("Considering options")
 * - `call_back`     a call back was booked
 * - `transferred`   the call was handed to a person
 * - `neutral`       the call was had and nothing about it is good or bad news
 * - `hung_up_early` it ended before anything was learned
 * - `said_no`       the caller said no (the starting set's `not_interested`)
 * - `not_connected` nobody spoke: missed, busy, voicemail, did not connect
 *
 * "Needs you" is not a kind: it is a request for a person, said beside the outcome by
 * `needsAttention` with its own icon.
 */
export type OutcomeKind =
  | "hot"
  | "interested"
  | "call_back"
  | "transferred"
  | "neutral"
  | "hung_up_early"
  | "said_no"
  | "not_connected";

/** The legend's words for each kind, in the order an owner reads them. */
export const OUTCOME_KIND_WORDS: Record<OutcomeKind, string> = {
  hot: "Ready to act",
  interested: "Interested",
  call_back: "Call-back booked",
  transferred: "Handed to your team",
  neutral: "Answered",
  hung_up_early: "Hung up early",
  said_no: "Said no",
  not_connected: "Did not connect",
};

/** The facts that head a row, and their kind; null for the two that say nothing of it. */
const FACT_KIND: Record<CallOutcome, OutcomeKind | null> = {
  call_back_booked: "call_back",
  transferred: "transferred",
  hung_up_early: "hung_up_early",
  missed: "not_connected",
  answered: null,
  needs_you: null,
};

/** How far the agent's own outcome moves the lead, and its kind (`contacted` says nothing). */
const LEAD_MOVE_KIND: Record<NonNullable<CallSummary["business_outcome_lead_status"]>, OutcomeKind> = {
  hot: "hot",
  interested: "interested",
  contacted: "neutral",
};

/** Statuses that ended the call before anyone spoke (`STATUS_WORDS` has their words). */
const NOT_CONNECTED = new Set(["no_answer", "busy", "voicemail", "failed"]);

/**
 * The starting set's refusal (`calevate_shared.business_outcomes.STARTING_OUTCOMES`). A
 * business outcome carries how far it moves a lead and nothing about bad news (`lost` is a
 * person's verdict, never a model's), so this key is the only "said no" the structure names.
 */
const SAID_NO_KEY = "not_interested";

type CallOutcomeFields = Pick<CallSummary, "status" | "outcome_tag"> & {
  summary_state?: CallSummary["summary_state"];
  business_outcome?: string | null;
  business_outcome_label?: string | null;
  business_outcome_lead_status?: CallSummary["business_outcome_lead_status"];
};

/**
 * The kind of ending one of the business's own outcomes files a call under, from its key and
 * how far it moves the lead. Shared by the call log and the outcomes editor, so the colour an
 * owner picks in the editor is the colour the log then draws.
 */
export function businessOutcomeKind(
  key: string | null | undefined,
  leadStatus: string | null | undefined,
): OutcomeKind {
  if (key === SAID_NO_KEY) return "said_no";
  return lookup(LEAD_MOVE_KIND, leadStatus) ?? "neutral";
}

/**
 * How a call ended, for a list row: the words and the kind of ending. "Needs you" is NOT an
 * outcome here — it is a request for a person, shown beside the outcome by `needsAttention`,
 * because filed under it a call that booked a site visit read the same as one where the
 * caller gave nothing. The facts that change what happens next (a booked call back, a
 * hand-over, an early hang-up, a missed call) head the row; otherwise the agent's own
 * outcome for the business; otherwise "Answered".
 */
export function callOutcome(call: CallOutcomeFields): { words: string; kind: OutcomeKind } {
  const known = lookup(STATUS_WORDS, call.status);
  // A status this build has never heard of is the one worth reading: it wins over any
  // outcome rather than being hidden behind one.
  if (call.status !== "completed" && known === undefined) {
    const unknown = call.status.replace(/_/g, " ");
    return { words: unknown.charAt(0).toUpperCase() + unknown.slice(1), kind: "neutral" };
  }
  if (call.status === "in_progress") return { words: "On the line", kind: "neutral" };
  const fact = lookup(FACT_KIND, call.outcome_tag);
  if (call.outcome_tag && fact) return { words: outcomeLabel(call.outcome_tag) ?? call.outcome_tag, kind: fact };
  const label = call.business_outcome_label?.trim();
  if (label) {
    return { words: label, kind: businessOutcomeKind(call.business_outcome, call.business_outcome_lead_status) };
  }
  if (call.status === "completed") {
    // `needs_you` reads as the conversation it was; the request is `needsAttention`'s to say.
    const tag = call.outcome_tag === "needs_you" ? null : call.outcome_tag;
    if (tag) return { words: outcomeLabel(tag) ?? tag, kind: "neutral" };
    // A completed call with no outcome was still a conversation: "No outcome" read as a fault.
    return { words: call.summary_state === "pending" ? "Being read" : "Answered", kind: "neutral" };
  }
  return { words: known ?? call.status, kind: NOT_CONNECTED.has(call.status) ? "not_connected" : "neutral" };
}

/**
 * A booked call back that is still waiting after the time it will be tried. That is
 * `next_try_at` when the server sends it: one the calling hours pushed to the morning is
 * waiting as it should, not late.
 */
export function callbackOverdue(callback: Callback | null | undefined, now: Date = new Date()): boolean {
  if (!callback || callback.status !== "scheduled") return false;
  const due = Date.parse(callback.next_try_at ?? callback.due_at);
  return Number.isFinite(due) && due < now.getTime();
}

const CALLBACK_WORDS: Record<Callback["status"], string> = {
  scheduled: "Booked for",
  dialing: "Calling them now",
  completed: "Called back",
  cancelled: "Cancelled",
  refused: "Not placed",
  missed: "Called back, no answer",
  failed: "Could not be placed",
};

/** Statuses whose line carries the time: when it is due, or when it was tried. */
const CALLBACK_TIMED = new Set<Callback["status"]>(["scheduled", "completed"]);

/**
 * An instant as a person reads an appointment: "Thu, 6 Nov, 7:00 pm", in IST (D-709). The
 * weekday is there because "tomorrow" is how an owner thinks about a call back.
 */
export function callbackWhen(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Who booked it, for a call back still to come; the reason an owner trusts the time. */
function callbackWhy(callback: Callback): string {
  if (callback.booked_by === "after_call") {
    return callback.time_from === "default"
      ? "They asked to talk later but didn't say when."
      : "They asked to be called at this time.";
  }
  if (callback.booked_by === "person") return "Booked by your team.";
  return "The agent booked it on the call.";
}

/**
 * The call back booked on this call, said as what will happen: "Booked for Thu, 6 Nov,
 * 7:00 pm", who booked it and why, and, while it waits on a rule (calling hours), the
 * server's sentence for that with when it will next be tried. A refusal's sentence is the
 * server's and is never reworded (trial accounts, do-not-call); the rule's own name never
 * shows.
 */
export function callbackLine(
  callback: Callback,
  now: Date = new Date(),
): { state: string; overdue: boolean; why: string | null; reason: string | null; nextTry: string | null } {
  const overdue = callbackOverdue(callback, now);
  const words = lookup(CALLBACK_WORDS, callback.status) ?? callback.status;
  const timed = CALLBACK_TIMED.has(callback.status) ? `${words} ${callbackWhen(callback.due_at)}` : words;
  const waiting = callback.status === "scheduled";
  // A later try than the booked time is the only news `next_try_at` carries: the hours or
  // the lines pushed it.
  const pushed =
    waiting && callback.next_try_at && Date.parse(callback.next_try_at) - Date.parse(callback.due_at) > 60_000
      ? callback.next_try_at
      : null;
  return {
    state: overdue ? `${timed} · Overdue` : timed,
    overdue,
    why: waiting ? callbackWhy(callback) : null,
    reason: callback.blocked_reason ?? null,
    nextTry: pushed ? `Next try ${callbackWhen(pushed)}` : null,
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

/** Was the call in English (`en`, `en-IN`)? Such a call needs no language switch. */
export function isEnglishCall(tag: string | null | undefined): boolean {
  return (tag ?? "").toLowerCase().split(/[-_]/)[0] === "en";
}
