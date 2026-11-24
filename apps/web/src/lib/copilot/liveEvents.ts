/**
 * Pip's live working view: the frames the copilot stream adds for it, and the state they build.
 *
 * The shapes are typed by hand against the shared contract (`run`, `thought`, `draft`,
 * `stopped`, and `step.results`) because the backend routes are being built beside this
 * module; once `pnpm gen:api` carries them, each interface below is replaced by its
 * generated twin and nothing else here changes.
 *
 * The reducer is pure so its ordering rules are tested without React or a stream
 * (`tests/pipLive.test.tsx`).
 */

import { apiRequest, type Session } from "@/lib/api/client";

import type { CopilotStep } from "./types";

/** `event: run`, the first frame of every run. */
export interface RunFrame {
  run_id: string;
  started_at: string;
}

/** `event: thought`: a fragment of the model's thought summary for the current model turn. */
export interface ThoughtFrame {
  delta: string;
}

/** `event: draft`: this run started a script draft, followed on its own draft stream. */
export interface DraftFrame {
  holder_kind: "campaign" | "inbound_line";
  holder_id: string;
  proposal_id: string;
}

/** `event: stopped`: the last frame after a Stop; no `done` follows it. */
export interface StoppedFrame {
  reason: string;
}

/** One row a read tool listed (`step.results.items`). */
export interface StepResultItem {
  title: string;
  subtitle: string | null;
  href: string | null;
}

/** `step.results`: what a read tool found, at most 8 items of `total`. */
export interface StepResults {
  kind: "list";
  items: StepResultItem[];
  total: number;
}

export function isRunFrame(value: Record<string, unknown> | null): value is Record<string, unknown> & RunFrame {
  return typeof value?.run_id === "string" && value.run_id !== "" && typeof value.started_at === "string";
}

export function isDraftFrame(value: Record<string, unknown> | null): value is Record<string, unknown> & DraftFrame {
  return (
    (value?.holder_kind === "campaign" || value?.holder_kind === "inbound_line") &&
    typeof value.holder_id === "string" &&
    value.holder_id !== "" &&
    typeof value.proposal_id === "string" &&
    value.proposal_id !== ""
  );
}

/** The step's results, when they are a list this browser can draw; otherwise null. */
export function stepResults(step: CopilotStep): StepResults | null {
  const results: unknown = step.results;
  if (typeof results !== "object" || results === null) return null;
  const { kind, items, total } = results as Partial<StepResults>;
  if (kind !== "list" || !Array.isArray(items)) return null;
  const drawn = items.filter(
    (item): item is StepResultItem => typeof item === "object" && item !== null && typeof item.title === "string",
  );
  return { kind, items: drawn, total: typeof total === "number" && total >= drawn.length ? total : drawn.length };
}

/**
 * A result's link, only when it is a path inside this console. The server builds `href`,
 * but a string that reaches `<a href>` is checked here anyway: `//host` and `javascript:`
 * would otherwise be one bad tool result away from a link that leaves the console.
 */
export function consoleHref(href: string | null | undefined): string | null {
  if (typeof href !== "string" || !href.startsWith("/") || href.startsWith("//") || href.includes("\\")) return null;
  return href;
}

// ── The run's state ──────────────────────────────────────────────────────────────────

/** One model turn's thinking. `endedAt` is set when the turn moved on to a step or the answer. */
export interface ThoughtEntry {
  kind: "thought";
  id: string;
  text: string;
  startedAt: number;
  endedAt: number | null;
}

/** A tool call, by the id `steps` keys it under; `startedAt` times it while it runs. */
export interface StepEntry {
  kind: "step";
  id: string;
  startedAt: number;
}

export type TimelineEntry = ThoughtEntry | StepEntry;

/** A draft this run started, and how far its own stream has got. */
export interface DraftRef extends DraftFrame {
  phase: string | null;
  settled: boolean;
}

export type RunPhase = "idle" | "working" | "stopping" | "stopped" | "finished";

export interface LiveRun {
  runId: string | null;
  /** Epoch ms the header counts from. */
  startedAt: number | null;
  phase: RunPhase;
  entries: TimelineEntry[];
  drafts: DraftRef[];
}

export const IDLE_RUN: LiveRun = { runId: null, startedAt: null, phase: "idle", entries: [], drafts: [] };

export type LiveAction =
  | { type: "ask" }
  | { type: "run"; frame: RunFrame; now: number }
  | { type: "thought"; delta: string; now: number }
  | { type: "step"; id: string; now: number }
  | { type: "text"; now: number }
  | { type: "draft"; frame: DraftFrame }
  | { type: "draftPhase"; proposalId: string; phase: string; settled: boolean }
  | { type: "stopping" }
  | { type: "end"; stopped: boolean; now: number }
  | { type: "reset" };

/**
 * How far a server's `started_at` may sit from this browser's clock and still be believed.
 * A run is opened the instant it starts, so a larger gap is a wrong clock on one side, and a
 * header that opens on "Working 7m" is worse than one counted from when the frame arrived.
 */
export const CLOCK_SKEW_LIMIT_MS = 60_000;

export function runClockStart(startedAt: string, receivedAt: number): number {
  const parsed = Date.parse(startedAt);
  if (Number.isNaN(parsed) || parsed > receivedAt || receivedAt - parsed > CLOCK_SKEW_LIMIT_MS) return receivedAt;
  return parsed;
}

/** The latest thought row, closed at `now` if it is still open. */
function closeThought(entries: TimelineEntry[], now: number): TimelineEntry[] {
  const last = entries[entries.length - 1];
  if (last?.kind !== "thought" || last.endedAt !== null) return entries;
  return [...entries.slice(0, -1), { ...last, endedAt: now }];
}

/**
 * Ordering rules, each pinned by a test:
 * - a thought fragment extends the open thought row; after a step or answer text it starts a
 *   new row, because the next model turn is thinking about something else;
 * - a step's first frame opens its row and closes the thought before it; its later frames
 *   change the step in `steps`, never the order;
 * - drafts are kept by proposal id, first frame wins, and survive the next question until
 *   they are settled: a draft outlives the answer that started it.
 */
export function liveRunReducer(state: LiveRun, action: LiveAction): LiveRun {
  switch (action.type) {
    case "ask":
      return { ...IDLE_RUN, phase: "working", drafts: state.drafts.filter((draft) => !draft.settled) };
    case "run":
      return { ...state, runId: action.frame.run_id, startedAt: runClockStart(action.frame.started_at, action.now) };
    case "thought": {
      if (action.delta === "") return state;
      const last = state.entries[state.entries.length - 1];
      if (last?.kind === "thought" && last.endedAt === null) {
        return { ...state, entries: [...state.entries.slice(0, -1), { ...last, text: last.text + action.delta }] };
      }
      const entry: ThoughtEntry = {
        kind: "thought",
        id: `thought-${state.entries.length}`,
        text: action.delta,
        startedAt: action.now,
        endedAt: null,
      };
      return { ...state, entries: [...state.entries, entry] };
    }
    case "step": {
      if (state.entries.some((entry) => entry.kind === "step" && entry.id === action.id)) return state;
      const entries = closeThought(state.entries, action.now);
      return { ...state, entries: [...entries, { kind: "step", id: action.id, startedAt: action.now }] };
    }
    case "text": {
      const entries = closeThought(state.entries, action.now);
      return entries === state.entries ? state : { ...state, entries };
    }
    case "draft":
      if (state.drafts.some((draft) => draft.proposal_id === action.frame.proposal_id)) return state;
      return { ...state, drafts: [...state.drafts, { ...action.frame, phase: null, settled: false }] };
    case "draftPhase":
      // Told again on every render of the draft's view; an unchanged report changes nothing.
      if (
        !state.drafts.some(
          (draft) =>
            draft.proposal_id === action.proposalId && (draft.phase !== action.phase || draft.settled !== action.settled),
        )
      ) {
        return state;
      }
      return {
        ...state,
        drafts: state.drafts.map((draft) =>
          draft.proposal_id === action.proposalId ? { ...draft, phase: action.phase, settled: action.settled } : draft,
        ),
      };
    case "stopping":
      return state.phase === "working" ? { ...state, phase: "stopping" } : state;
    case "end":
      return {
        ...state,
        phase: action.stopped ? "stopped" : "finished",
        entries: closeThought(state.entries, action.now),
      };
    case "reset":
      return IDLE_RUN;
  }
}

/** True while a draft from this conversation is written and waits for Keep or Discard. */
export function draftWaiting(drafts: readonly DraftRef[]): boolean {
  return drafts.some((draft) => draft.phase === "ready" && !draft.settled);
}

/**
 * "9s", "1m 4s", "1h 2m": how long something has been going, short enough to sit after a
 * verb ("Thought for 3s"). Not `formatClock`, whose "0:09" reads as a recording's position.
 */
export function formatWorkTime(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return seconds % 60 === 0 ? `${minutes}m` : `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** A finished step's own timing, rounded up so a quick read never says "0s". */
export function stepDuration(elapsedMs: number | null | undefined): string | null {
  if (elapsedMs == null || elapsedMs < 0) return null;
  return elapsedMs < 1000 ? "<1s" : formatWorkTime(elapsedMs);
}

// ── Stop ────────────────────────────────────────────────────────────────────────────

export function stopRunPath(realm: "client" | "admin", runId: string): string {
  const id = encodeURIComponent(runId);
  return realm === "admin" ? `/v1/admin/copilot/runs/${id}/stop` : `/v1/copilot/runs/${id}/stop`;
}

/**
 * Ask the server to stop this run. It answers 202 at once; the stream then ends with
 * `stopped`, which is what the Stop button waits for. Stopping on the server rather than
 * only closing the connection is what ends the model call and cancels the run's drafts.
 */
export function requestStop(session: Session, realm: "client" | "admin", runId: string): Promise<unknown> {
  return apiRequest<unknown>(session, stopRunPath(realm, runId), { method: "POST" });
}

/**
 * How long Stop waits for `stopped` before closing the connection itself. The server checks
 * between model frames and tool calls, so a slow tool can hold it; past this the person is
 * owed a panel they can use, and the server still finishes the stop it was asked for.
 */
export const STOP_GRACE_MS = 8_000;
