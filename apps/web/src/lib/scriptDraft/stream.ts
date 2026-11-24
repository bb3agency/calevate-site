"use client";

/**
 * A script draft while Pip writes it: one stream per holder (a campaign or an Inbound line),
 * read by the Pip panel and by the holder's own page through the same hook, so both show it
 * the same way.
 *
 * The `phase`, `line` and `diff` payloads are typed here because they travel only inside the
 * `text/event-stream` body, which OpenAPI describes in prose (the stream route's description)
 * and not as schemas; the routes' JSON answers (keep-live, cancel) use the generated types.
 *
 * ## Reconnecting
 *
 * The draft stream is a read, so unlike the copilot's metered ask it is safe to open again.
 * A dropped stream reopens after a full-jitter backoff (the rule `lib/live/liveConnection.ts`
 * uses), at most `MAX_RECONNECTS` times; a 4xx is an answer and is not retried. The contract
 * carries no event ids, so a reopened stream cannot resume where it stopped (`Last-Event-ID`
 * needs ids to name); the view clears the lines it holds and takes what the new stream sends.
 * The diff at `ready` is complete on its own, so nothing a person decides on is lost.
 */

import { useEffect, useReducer } from "react";

import { ApiProblem, openEventStream, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { SseEvent } from "@/lib/copilot/sse";

export type ScriptDraftHolderKind = components["schemas"]["CopilotDraftEvent"]["holder_kind"];

export interface ScriptDraftHolder {
  kind: ScriptDraftHolderKind;
  id: string;
}

export type DraftPhase = "reading" | "writing" | "checking" | "repairing" | "ready" | "failed" | "cancelled";

const PHASES: readonly DraftPhase[] = ["reading", "writing", "checking", "repairing", "ready", "failed", "cancelled"];

/** Phases after which the writer does nothing more. */
export function isTerminalPhase(phase: DraftPhase | null): boolean {
  return phase === "ready" || phase === "failed" || phase === "cancelled";
}

/** `event: line`: one script line as the writer produces it, by its path in the script. */
export interface DraftLine {
  path: string;
  label: string;
  text: string;
}

export type DraftChangeOp = "added" | "removed" | "changed" | "same";

export interface DraftChange {
  path: string;
  label: string;
  op: DraftChangeOp;
  before: string | null;
  after: string | null;
}

/** `event: diff`: the saved script against the draft, in script order, once at `ready`. */
export interface DraftDiff {
  changes: DraftChange[];
  proposal_id: string;
}

export interface DraftStreamState {
  phase: DraftPhase | null;
  /** The server's sentence about the phase (why it failed, what it is fixing). */
  detail: string | null;
  lines: DraftLine[];
  diff: DraftDiff | null;
  /** Each phase once, with when it began here, so a finished phase can say how long it took. */
  history: { phase: DraftPhase; at: number }[];
  /** The stream could not be read: the page shows its own review instead. */
  unavailable: boolean;
}

export const EMPTY_DRAFT_STREAM: DraftStreamState = {
  phase: null,
  detail: null,
  lines: [],
  diff: null,
  history: [],
  unavailable: false,
};

export type DraftStreamAction =
  | { type: "phase"; phase: DraftPhase; detail: string | null; at?: number }
  | { type: "line"; line: DraftLine }
  | { type: "diff"; diff: DraftDiff }
  | { type: "reopen" }
  | { type: "unavailable" };

/**
 * A line for a path already shown replaces it in place (the writer may send a growing
 * line more than once); a new path joins the end, which is script order.
 */
export function draftStreamReducer(state: DraftStreamState, action: DraftStreamAction): DraftStreamState {
  switch (action.type) {
    case "phase": {
      // A reopened stream says the current phase again; it is not a new one.
      const repeated = state.history[state.history.length - 1]?.phase === action.phase;
      const history = repeated ? state.history : [...state.history, { phase: action.phase, at: action.at ?? 0 }];
      return { ...state, phase: action.phase, detail: action.detail, history };
    }
    case "line": {
      const at = state.lines.findIndex((line) => line.path === action.line.path);
      if (at === -1) return { ...state, lines: [...state.lines, action.line] };
      const lines = [...state.lines];
      lines[at] = action.line;
      return { ...state, lines };
    }
    case "diff":
      return { ...state, diff: action.diff };
    case "reopen":
      return { ...state, lines: [] };
    case "unavailable":
      return { ...state, unavailable: true };
  }
}

function base(holder: ScriptDraftHolder): string {
  const id = encodeURIComponent(holder.id);
  return holder.kind === "campaign" ? `/v1/campaigns/${id}/script-draft` : `/v1/inbound-lines/${id}/script-draft`;
}

export const draftStreamPath = (holder: ScriptDraftHolder) => `${base(holder)}/stream`;
export const keepLivePath = (holder: ScriptDraftHolder, proposalId: string) =>
  `${base(holder)}/${encodeURIComponent(proposalId)}/keep-live`;
export const cancelDraftPath = (holder: ScriptDraftHolder, proposalId: string) =>
  `${base(holder)}/${encodeURIComponent(proposalId)}/cancel`;

function json(data: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(data);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);

function isOp(value: unknown): value is DraftChangeOp {
  return value === "added" || value === "removed" || value === "changed" || value === "same";
}

/** One SSE record as a reducer action, or null for a frame this browser cannot use. */
export function draftAction(event: SseEvent): DraftStreamAction | null {
  const payload = json(event.data);
  if (payload === null) return null;
  if (event.event === "phase") {
    const phase = PHASES.find((known) => known === payload.phase);
    return phase ? { type: "phase", phase, detail: text(payload.detail) } : null;
  }
  if (event.event === "line") {
    const path = text(payload.path);
    if (!path) return null;
    return { type: "line", line: { path, label: text(payload.label) ?? "", text: text(payload.text) ?? "" } };
  }
  if (event.event === "diff") {
    const proposalId = text(payload.proposal_id);
    if (!proposalId || !Array.isArray(payload.changes)) return null;
    const changes: DraftChange[] = [];
    for (const raw of payload.changes as unknown[]) {
      if (typeof raw !== "object" || raw === null) continue;
      const change = raw as Record<string, unknown>;
      const path = text(change.path);
      if (!path || !isOp(change.op)) continue;
      changes.push({
        path,
        label: text(change.label) ?? "",
        op: change.op,
        before: text(change.before),
        after: text(change.after),
      });
    }
    return { type: "diff", diff: { changes, proposal_id: proposalId } };
  }
  return null;
}

export const MAX_RECONNECTS = 4;
export const RECONNECT_BASE_MS = 1_000;
export const RECONNECT_MAX_MS = 15_000;

/**
 * Follow one holder's draft while `enabled`. The stream closes when the component unmounts
 * or `enabled` turns false, and is not reopened once the writer has finished.
 */
export function useScriptDraftStream(
  session: Session,
  holder: ScriptDraftHolder,
  enabled = true,
): DraftStreamState {
  const [state, dispatch] = useReducer(draftStreamReducer, EMPTY_DRAFT_STREAM);
  const { kind, id } = holder;

  useEffect(() => {
    if (!enabled) return undefined;
    const target: ScriptDraftHolder = { kind, id };
    let closed = false;
    let abort: AbortController | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let last: DraftPhase | null = null;
    let sawDiff = false;

    const open = () => {
      if (closed) return;
      abort = new AbortController();
      const signal = abort.signal;
      if (attempt > 0) dispatch({ type: "reopen" });
      void openEventStream(session, draftStreamPath(target), {
        signal,
        onEvent: (event) => {
          const action = draftAction(event);
          if (action === null) return;
          if (action.type === "diff") sawDiff = true;
          if (action.type === "phase") {
            last = action.phase;
            dispatch({ ...action, at: Date.now() });
            return;
          }
          dispatch(action);
        },
      }).then(
        () => ended(signal, null),
        (error: unknown) => ended(signal, error),
      );
    };

    const ended = (signal: AbortSignal, error: unknown) => {
      if (closed || signal.aborted) return;
      if (isTerminalPhase(last)) {
        // A ready draft whose changes never came cannot be decided on from this view.
        if (last === "ready" && !sawDiff) dispatch({ type: "unavailable" });
        return;
      }
      const refused = error instanceof ApiProblem && error.status >= 400 && error.status < 500;
      if (refused || attempt >= MAX_RECONNECTS) {
        dispatch({ type: "unavailable" });
        return;
      }
      const ceiling = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attempt);
      attempt += 1;
      retry = setTimeout(open, Math.round(Math.random() * ceiling));
    };

    open();
    return () => {
      closed = true;
      if (retry !== null) clearTimeout(retry);
      abort?.abort();
    };
  }, [session, kind, id, enabled]);

  return state;
}
