/**
 * "MEET YOUR AGENT" (D-855), PIECE BY PIECE — what the first-run screen counts and where an
 * owner resumes.
 *
 * Every piece is RECOMPUTED from rows the server already holds: the first run (job, brief,
 * build), the agent itself and its calls. There is no stored game state, so an owner who
 * leaves half way, changes a piece on the agent's own page, or comes back next week lands
 * on a card that says where they really are.
 *
 * "Account created" is always done: the meter starts above zero on purpose (endowed
 * progress, Nunes & Drèze 2006), because the account is real work the owner has finished.
 */

import { formatCallCap } from "@/components/ui";
import { LANGUAGE_CHOICES } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import type { FirstRun, FirstRunJob } from "@/lib/api/firstRun";
import { lookup } from "@/lib/lookup";

/** The greeting the card counts as done: short, and ending on a question that hands the turn
 *  to the caller. Pinned to `apps/api/copilot/screen_guides.FIRST_GREETING_MAX_CHARS` and to
 *  `apps/workers/first_run.GREETING_MAX_CHARS`. */
export const GREETING_MAX_CHARS = 120;

export type PieceId =
  | "account"
  | "job"
  | "about"
  | "name"
  | "voice"
  | "greeting"
  | "notes"
  | "ready"
  | "call";

export interface Piece {
  id: PieceId;
  label: string;
  done: boolean;
}

export interface FirstAgentState {
  run: FirstRun | undefined;
  agent: Agent | null;
  /** This agent's calls, newest first, or undefined while unread. */
  calls: readonly CallSummary[] | undefined;
}

/** The four steps on the rail, in order. */
export const STEPS = [
  { id: "job", label: "Its job" },
  { id: "about", label: "Tell it about you" },
  { id: "hear", label: "Hear it" },
  { id: "yours", label: "Make it yours" },
] as const;
export type StepId = (typeof STEPS)[number]["id"];

/** Where the owner is inside the steps. */
export type Stage = "job" | "brief" | "questions" | "build" | "hear" | "result" | "team";

export const STEP_OF_STAGE: Readonly<Record<Stage, StepId>> = {
  job: "job",
  brief: "about",
  questions: "about",
  build: "about",
  hear: "hear",
  result: "hear",
  team: "yours",
};

/** What each job does, in the owner's words. */
export interface JobCard {
  job: FirstRunJob;
  title: string;
  line: string;
  /** How the test call is introduced, with the business's name. */
  callIntro: (business: string) => string;
}

export const JOBS: readonly JobCard[] = [
  {
    job: "answer_calls",
    title: "Answer my calls",
    line: "Picks up when customers ring your number, day or night.",
    callIntro: (business) => `It rings you and answers as if you had called ${business}.`,
  },
  {
    job: "call_new_leads",
    title: "Call new leads instantly",
    line: "Rings each new enquiry within minutes, while they are still interested.",
    callIntro: () => "It rings you as if you had just sent an enquiry.",
  },
  {
    job: "call_leads",
    title: "Run calling campaigns",
    line: "Works through a list of people who showed interest earlier.",
    callIntro: () => "It rings you as if you were the first person on your list.",
  },
];

export function jobCard(job: FirstRunJob | null | undefined): JobCard | null {
  return JOBS.find((card) => card.job === job) ?? null;
}

/** The languages a client may choose today, from the one table in `agentState`. */
export const LANGUAGES: readonly { tag: string; label: string }[] = LANGUAGE_CHOICES.map(({ value, label }) => ({
  tag: value,
  label,
}));

export function languageLabel(tag: string | null | undefined): string {
  return LANGUAGES.find((language) => language.tag === tag)?.label ?? "Telugu";
}

/** The main language a new agent starts in: the business profile's first one we sell, else
 *  Telugu (we are Telugu-first). */
export function defaultLanguage(profileLanguages: readonly string[] | undefined): string {
  return profileLanguages?.find((tag) => LANGUAGES.some((language) => language.tag === tag)) ?? "te-IN";
}

/** Characters as a person counts them: Telugu and emoji are not two units each. */
export function charCount(text: string): number {
  return Array.from(text).length;
}

export function greetingFits(line: string | null | undefined): boolean {
  const trimmed = (line ?? "").trim();
  return trimmed !== "" && charCount(trimmed) <= GREETING_MAX_CHARS && /[?？]$/.test(trimmed);
}

/** The agent this screen is building: the first run's own, else none. */
export function firstAgentOf(agents: readonly Agent[] | undefined, run: FirstRun | undefined): Agent | null {
  const id = run?.agent_id ?? null;
  if (id === null) return null;
  return (agents ?? []).find((agent) => agent.id === id && agent.status !== "archived") ?? null;
}

export function piecesOf({ run, agent, calls }: FirstAgentState): Piece[] {
  const has = agent !== null;
  return [
    { id: "account", label: "Account created", done: true },
    { id: "job", label: "Its job", done: (run?.jobs.length ?? 0) > 0 },
    { id: "about", label: "What it knows about you", done: Boolean(run?.brief?.trim()) },
    { id: "name", label: "Its name", done: has && agent.name.trim() !== "" },
    { id: "voice", label: "Its voice", done: has && Boolean(agent.engine_voice_id) },
    { id: "greeting", label: "How it greets", done: has && greetingFits(agent.script_opening_line) },
    { id: "notes", label: "What it notes down", done: has && agent.extraction_fields.length > 0 },
    { id: "ready", label: "Ready to try", done: has && agent.published },
    { id: "call", label: "Its first call", done: has && (calls?.length ?? 0) > 0 },
  ];
}

/** Where an owner resumes, from what the server holds. */
export function resumeStage({ run, agent, calls }: FirstAgentState): Stage {
  if (!run || run.jobs.length === 0) return "job";
  if (run.finished_at) return "team";
  if (run.build.status === "building" || run.build.status === "failed") return "build";
  if (agent === null) return run.brief === null ? "brief" : "questions";
  return (calls?.length ?? 0) > 0 ? "result" : "hear";
}

/** The job, in the owner's words, from the agent's direction (for an agent made elsewhere). */
export function jobOf(agent: Agent): string {
  if (agent.direction === "inbound") return "Answers your calls";
  if (agent.direction === "outbound") return "Calls your leads";
  return "Answers your calls and calls your leads";
}

/**
 * About how many more test calls the trial minutes allow, counting each call at its longest
 * (`max_call_seconds`), so the figure can only be an under-promise. Null when the trial has no
 * minutes cap or the longest call is unknown.
 */
export function callsLeft(minutesLeft: number | null | undefined, maxCallSeconds: number | null | undefined): number | null {
  if (minutesLeft === null || minutesLeft === undefined) return null;
  if (!maxCallSeconds || maxCallSeconds <= 0) return null;
  return Math.max(0, Math.floor((minutesLeft * 60) / maxCallSeconds));
}

/**
 * Why a Clear voice stands in for Studio, in one short line (D-855: Studio is picked first so a
 * new owner hears the best we have). No provider is named (D-679).
 */
const STUDIO_FALLBACK_WORDS: Readonly<Record<string, string>> = {
  studio_unavailable: "Studio voices aren't available right now, so it uses a Clear voice.",
  studio_minutes_used: "Your trial's Studio minutes are used, so it uses a Clear voice.",
  no_studio_voice: "No Studio voice speaks this language yet, so it uses a Clear voice.",
  no_female_studio_voice: "No Studio woman's voice speaks this language yet, so it uses a Clear voice.",
};

export function studioFallbackLine(fallback: string | null | undefined): string | null {
  return fallback ? (lookup(STUDIO_FALLBACK_WORDS, fallback) ?? null) : null;
}

/** Said when no woman's voice could be chosen for the new agent (founder, 23 Oct 2026: it is
 *  named Anjali, so its voice is a woman's whenever one speaks its language). */
export const NOT_FEMALE_LINE = "No woman's voice speaks this language yet, so it has the closest voice we have.";

/** The note under the chosen voice: why it is Clear, then why it is not a woman's. */
export function voicePickNote(fallback: string | null | undefined, notFemale: boolean | null | undefined): string | null {
  const lines = [studioFallbackLine(fallback), notFemale ? NOT_FEMALE_LINE : null].filter(Boolean);
  return lines.length ? lines.join(" ") : null;
}

/** What a test call costs the trial, in one sentence, from the server's own figures (never
 *  hardcoded: the trial's terms are an operator's console settings). */
export function trialMinutesLine(trial: {
  free_minutes?: number | null;
  minutes_left?: number | null;
  max_call_seconds: number;
  daily_cap: number;
  calls_today: number;
}): string {
  const parts: string[] = [];
  if (trial.free_minutes !== null && trial.free_minutes !== undefined) {
    const left = trial.minutes_left ?? 0;
    const calls = callsLeft(left, trial.max_call_seconds);
    parts.push(
      `Test calls use your ${trial.free_minutes} free trial minutes: ${left} left` +
        (calls !== null ? `, about ${calls} ${calls === 1 ? "call" : "calls"}.` : "."),
    );
  } else {
    parts.push("Test calls use your free trial.");
  }
  if (trial.max_call_seconds > 0) parts.push(`Each call stops at ${formatCallCap(trial.max_call_seconds)}.`);
  if (trial.daily_cap > 0) parts.push(`You can make ${trial.daily_cap} a day (${trial.calls_today} today).`);
  return parts.join(" ");
}

/** Pip's first line in an empty chat on this screen. */
export function introFor(agentName: string | null): string {
  return agentName
    ? `Tell me what to change about ${agentName}, in your own words.`
    : "Tell me about your business and what your agent should do. I'll build it with you.";
}

/** One-tap answers for Pip on this screen. They are the person's words, sent as their message. */
export function quickRepliesFor(hasAgent: boolean): readonly string[] {
  return hasAgent
    ? ["Make the greeting warmer", "What does it note down?"]
    : ["Answer my calls", "Call new leads instantly", "Run calling campaigns"];
}
