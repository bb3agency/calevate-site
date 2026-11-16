/**
 * "MEET YOUR AGENT" (D-855), PIECE BY PIECE — what the first-run screen counts and where an
 * owner resumes.
 *
 * Every piece is RECOMPUTED from rows the server already holds: the first run (brief, its
 * first work), the agent itself, the line or campaign it was given and its calls (Phase 3b:
 * the agent is staff, the work holds the script). There is no stored game state, so an owner who
 * leaves half way, changes a piece on the agent's own page, or comes back next week lands
 * on a card that says where they really are.
 *
 * "Account created" is always done: the meter starts above zero on purpose (endowed
 * progress, Nunes & Drèze 2006), because the account is real work the owner has finished.
 */

import {
  BadgeCheck,
  ClipboardList,
  Inbox,
  ListChecks,
  Megaphone,
  MessagesSquare,
  NotebookPen,
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { formatCallCap } from "@/components/ui";
import { LANGUAGE_CHOICES } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import type { FirstRun, FirstRunDocument, FirstRunJob } from "@/lib/api/firstRun";
import { founderLine } from "@/lib/founderLines";
import { lookup } from "@/lib/lookup";

export type PieceId = "account" | "about" | "name" | "voice" | "work" | "script" | "call";

export interface Piece {
  id: PieceId;
  label: string;
  done: boolean;
}

/**
 * The first work "What first?" drafted (Phase 3b): an inbound line or a campaign, and whether
 * Pip has written its script yet. Read from the line or the campaign itself.
 */
export interface FirstWork {
  kind: "line" | "campaign";
  id: string;
  /** Its script is saved, so a test call has something to say. */
  ready: boolean;
  /** Pip is writing it now. */
  writing: boolean;
  /** Pip's last try did not finish; the owner writes it on the work's own page. */
  failed: boolean;
  /** What it says first, from its script, or null before it has one. */
  opening: string | null;
}

export interface FirstAgentState {
  run: FirstRun | undefined;
  agent: Agent | null;
  /** This agent's calls, newest first, or undefined while unread. */
  calls: readonly CallSummary[] | undefined;
  /** The work it was given, or null before "What first?". */
  work?: FirstWork | null;
}

/** The four steps on the rail, in order (founder, 16 Nov 2026). */
export const STEPS = [
  { id: "about", label: "About your business" },
  { id: "agent", label: "Name and voice" },
  { id: "work", label: "What first?" },
  { id: "hear", label: "Hear it" },
] as const;
export type StepId = (typeof STEPS)[number]["id"];

/** Where the owner is inside the steps. `team` is past the rail: going live. */
export type Stage = "brief" | "questions" | "agent" | "work" | "hear" | "result" | "team";

export const STEP_OF_STAGE: Readonly<Record<Exclude<Stage, "team">, StepId>> = {
  brief: "about",
  questions: "about",
  agent: "agent",
  work: "work",
  hear: "hear",
  result: "hear",
};

/** The rail's index for a stage; going live is past every step, so all four are ticked. */
export function stepIndexOf(stage: Stage): number {
  return stage === "team" ? STEPS.length : STEPS.findIndex((entry) => entry.id === STEP_OF_STAGE[stage]);
}

/** The two works "What first?" offers, as `POST /v1/first-run/work` names them. */
export const FIRST_WORKS = ["answer_calls", "call_leads"] as const;
export type FirstWorkJob = (typeof FIRST_WORKS)[number];

/** One link of a job's three-link flow: what happens, with the icon that names it. */
export interface JobLink {
  icon: LucideIcon;
  label: string;
}

/** What each job does, in the owner's words. */
export interface JobCard {
  job: FirstRunJob;
  title: string;
  line: string;
  icon: LucideIcon;
  /** The job as three things that happen, in order: what starts it, what it does, what you get. */
  flow: readonly [JobLink, JobLink, JobLink];
  /** How the test call is introduced, with the business's name. */
  callIntro: (business: string) => string;
}

export const JOBS: readonly JobCard[] = [
  {
    job: "answer_calls",
    title: "Answer my calls",
    line: "Picks up when people ring your number, day or night.",
    icon: PhoneIncoming,
    flow: [
      { icon: Phone, label: "Someone rings" },
      { icon: MessagesSquare, label: "It answers" },
      { icon: NotebookPen, label: "Notes what they need" },
    ],
    callIntro: (business) => `It rings you and answers as if you had called ${business}.`,
  },
  {
    job: "call_new_leads",
    title: "Call new leads instantly",
    line: "Rings each new enquiry within minutes, while they are still interested.",
    icon: Zap,
    flow: [
      { icon: Inbox, label: "An enquiry comes in" },
      { icon: PhoneOutgoing, label: "It rings them" },
      { icon: BadgeCheck, label: "Finds the serious ones" },
    ],
    callIntro: () => "It rings you as if you had just sent an enquiry.",
  },
  {
    // `call_leads` is bulk calling: the agent works through a whole list as a campaign.
    job: "call_leads",
    title: "Call people",
    line: "Calls the people who asked to hear from you, one after another.",
    icon: Megaphone,
    flow: [
      { icon: ListChecks, label: "Your contact list" },
      { icon: PhoneOutgoing, label: "Calls each one" },
      { icon: ClipboardList, label: "Records every answer" },
    ],
    callIntro: () => "It rings you as if you were the first person on your list.",
  },
];

export function jobCard(job: FirstRunJob | null | undefined): JobCard | null {
  return JOBS.find((card) => card.job === job) ?? null;
}

/** Jobs in the cards' order, so the first is the one the test call plays (answering first). */
export function sortJobs(jobs: readonly FirstRunJob[]): FirstRunJob[] {
  return JOBS.map((card) => card.job).filter((job) => jobs.includes(job));
}

/** The agent's jobs as one line for its card: "Answer my calls + 1 more". */
export function jobsTitle(jobs: readonly FirstRunJob[]): string | null {
  const ordered = sortJobs(jobs);
  const first = jobCard(ordered[0]);
  if (!first) return null;
  return ordered.length > 1 ? `${first.title} + ${ordered.length - 1} more` : first.title;
}

/** How the test call is introduced when the agent has several jobs: answering comes first,
 *  because the test call plays the part of a caller ringing in. */
export function callIntroFor(jobs: readonly FirstRunJob[], business: string): string {
  return jobCard(sortJobs(jobs)[0])?.callIntro(business) ?? "It rings you and talks to you as it would to a caller.";
}

/** The languages a client may choose today, from the one table in `agentState`. */
export const LANGUAGES: readonly { tag: string; label: string }[] = LANGUAGE_CHOICES.map(({ value, label }) => ({
  tag: value,
  label,
}));

/** Each language's mark: the first letter of its own name in its own script, so an owner
 *  finds theirs by sight. The names are the founder's data (`founderLines.json`); English,
 *  whose name is not in another script, reads "En". */
export function languageGlyph(tag: string): string {
  if (tag.startsWith("en")) return "En";
  let name: string;
  try {
    name = founderLine(`language.endonym.${tag}`);
  } catch {
    return tag.slice(0, 2);
  }
  const first = new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(name)[Symbol.iterator]().next();
  return first.done ? tag.slice(0, 2) : first.value.segment;
}

/** The language's name without the region the picker does not need ("English (India)"). */
export function languageShortLabel(tag: string): string {
  return languageLabel(tag).replace(/\s*\(.*\)$/, "");
}

export function languageLabel(tag: string | null | undefined): string {
  return LANGUAGES.find((language) => language.tag === tag)?.label ?? "Telugu";
}

/** The main language a new agent starts in: the business profile's first one we sell, else
 *  Telugu (we are Telugu-first). */
export function defaultLanguage(profileLanguages: readonly string[] | undefined): string {
  return profileLanguages?.find((tag) => LANGUAGES.some((language) => language.tag === tag)) ?? "te-IN";
}

/** The agent this screen is building: the first run's own, else none. */
export function firstAgentOf(agents: readonly Agent[] | undefined, run: FirstRun | undefined): Agent | null {
  const id = run?.agent_id ?? null;
  if (id === null) return null;
  return (agents ?? []).find((agent) => agent.id === id && agent.status !== "archived") ?? null;
}

export function piecesOf({ run, agent, calls, work = null }: FirstAgentState): Piece[] {
  const has = agent !== null;
  return [
    { id: "account", label: "Account created", done: true },
    {
      id: "about",
      label: "What it knows about you",
      done: Boolean(run?.brief?.trim()) || (run?.documents ?? []).some((document) => document.state === "read"),
    },
    { id: "name", label: "Its name", done: has && agent.name.trim() !== "" },
    { id: "voice", label: "Its voice", done: has && Boolean(agent.engine_voice_id) },
    { id: "work", label: "Its first work", done: work !== null },
    { id: "script", label: "What it says", done: work?.ready === true },
    { id: "call", label: "Its first call", done: has && (calls?.length ?? 0) > 0 },
  ];
}

/** Where an owner resumes, from what the server holds. */
export function resumeStage({ run, agent, calls, work = null }: FirstAgentState): Stage {
  if (!run) return "brief";
  if (run.finished_at) return "team";
  // A saved brief, even an empty one, is the brief step done; files alone are not.
  if (agent === null) return run.brief === null ? "brief" : "questions";
  if (work === null || !work.ready) return run.line_id || run.campaign_id ? "work" : "agent";
  return (calls?.length ?? 0) > 0 ? "result" : "hear";
}

/** What the line or campaign read says about its script. */
type WorkRead = { script: { opening_line?: string | null } | null; proposal: { status: string } | null };

/** The first work the run drafted, from the line or campaign read; null before one exists. */
export function firstWorkOf(
  run: FirstRun | undefined,
  read: { line?: WorkRead | null; campaign?: WorkRead | null },
): FirstWork | null {
  const job = run?.jobs[0];
  const holder =
    job === "call_leads" && run?.campaign_id
      ? { kind: "campaign" as const, id: run.campaign_id, data: read.campaign }
      : run?.line_id
        ? { kind: "line" as const, id: run.line_id, data: read.line }
        : run?.campaign_id
          ? { kind: "campaign" as const, id: run.campaign_id, data: read.campaign }
          : null;
  if (holder === null) return null;
  const script = holder.data?.script ?? null;
  const status = holder.data?.proposal?.status ?? null;
  return {
    kind: holder.kind,
    id: holder.id,
    ready: script !== null,
    writing: status === "drafting",
    failed: status === "failed",
    opening: script?.opening_line?.trim() || null,
  };
}

/** The work's own page, where the owner changes what it says. */
export function workHref(slug: string, work: FirstWork): string {
  return work.kind === "line" ? `/c/${slug}/inbound/${work.id}` : `/c/${slug}/campaigns/${work.id}`;
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
export function callsLeft(
  minutesLeft: number | null | undefined,
  maxCallSeconds: number | null | undefined,
): number | null {
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
export function voicePickNote(
  fallback: string | null | undefined,
  notFemale: boolean | null | undefined,
): string | null {
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

/**
 * A brief-step file's state in a few words (D-918). Whether its words reach the agents on
 * calls is the server's answer per file (`reaches_agents`): a PDF's do not while its words
 * are kept for the script and for reading only.
 */
export function documentLine(document: FirstRunDocument): string {
  if (document.state === "reading") return "Reading it…";
  if (document.state === "failed") return "Couldn't read this file.";
  return document.reaches_agents ? "Read. Your agent uses it." : "Read. Not used on calls yet.";
}

/**
 * Why the brief's Continue must wait, or null when it need not. A file being read holds it
 * because the questions and the script are written from its words; a failed file does not,
 * and neither does a reading one forever, since its row's Remove lets the owner go on without
 * it (the server keeps no clock on a read).
 */
export function briefWaitingFor({
  documents,
  sending,
  hearing,
}: {
  documents: readonly FirstRunDocument[];
  /** A file is uploading, or one is being taken off. */
  sending: boolean;
  /** Spoken words are still being turned into text for the box. */
  hearing: boolean;
}): string | null {
  if (hearing) return "Waiting for your words to reach the box.";
  if (sending) return "Waiting for your file to finish sending.";
  const reading = documents.filter((document) => document.state === "reading").length;
  if (reading === 1) return "Waiting for your file to be read. Or remove it.";
  if (reading > 1) return "Waiting for your files to be read. Or remove them.";
  return null;
}

/** Pip's first line in an empty chat on this screen. */
export function introFor(agentName: string | null): string {
  return agentName
    ? `Tell me what ${agentName} should do first, or ask me about its voice.`
    : "Tell me about your business in your own words. I'll set up your first agent with you.";
}

/** One-tap answers for Pip on this screen. They are the person's words, sent as their message. */
export function quickRepliesFor(hasAgent: boolean): readonly string[] {
  return hasAgent ? ["Offer me two voices", "What should it do first?"] : ["Here's what we do", "What do you need from me?"];
}
