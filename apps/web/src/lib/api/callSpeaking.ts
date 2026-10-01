"use client";

import { useEffect, useState } from "react";

import { ApiProblem, openEventStream, type Session } from "./client";

/**
 * Who is speaking on a live call, for the console's speaking indicator (D-656).
 *
 * `GET /v1/calls/{call_id}/speaking` streams `text/event-stream` frames: one at once, one
 * per change, and a last one with `live: false` when the call ends. A stream rather than a
 * poll because the indicator needs about a second and a 1 Hz poll per open call screen
 * would spend half of nginx's 120 r/m per-address `client_api` zone on its own —
 * `apps/api/crm/live_speaking.py` carries the evidence.
 *
 * NOT A TANSTACK QUERY, deliberately: a query is a request that resolves once and is
 * refetched on an interval, and this is one long request whose value changes while it is
 * open. Nothing else reads this state, so there is no cache to share.
 */

export type Speaker = "caller" | "agent";

/**
 * One frame, exactly `crm/live_speaking.CallSpeakingOut`.
 *
 * WRITTEN BY HAND, not taken from `schema.d.ts`: FastAPI 0.140 drops an SSE route's item
 * model from the document when the router is included under a prefix, so the generator has
 * nothing to emit. `tests/live_speaking_contract_test.py` reads this interface and fails
 * when its fields stop matching the Python model.
 */
export interface CallSpeakingFrame {
  speaker: Speaker | null;
  live: boolean;
  since: string | null;
}

export interface CallSpeaking {
  /** Who is audible now. `null` is silence, or no state reported yet. */
  speaker: Speaker | null;
  /** True while the stream is up and the call has not ended. */
  live: boolean;
}

export const callSpeakingPath = (callId: string): string => `/v1/calls/${callId}/speaking`;

/** Reconnect delays after a stream closes while the call is still live. */
export const RECONNECT_BASE_MS = 1_000;
export const RECONNECT_MAX_MS = 15_000;

const IDLE: CallSpeaking = { speaker: null, live: false };

/** A frame, or `null` when the payload is not one. A bad frame is dropped, not fatal. */
export function parseSpeakingFrame(data: string): CallSpeakingFrame | null {
  try {
    const value: unknown = JSON.parse(data);
    if (typeof value !== "object" || value === null) return null;
    const frame = value as Record<string, unknown>;
    const speaker = frame.speaker;
    if (speaker !== null && speaker !== "caller" && speaker !== "agent") return null;
    if (typeof frame.live !== "boolean") return null;
    return {
      speaker,
      live: frame.live,
      since: typeof frame.since === "string" ? frame.since : null,
    };
  } catch {
    return null;
  }
}

/**
 * `{ speaker, live }` for one call, kept current while the call is live.
 *
 * Pass `enabled: false` for a call that is not in progress — no request is made. The
 * stream stops for good on a `live: false` frame or on a refusal (`404` for a call this
 * account cannot see, `401`/`403`), and reconnects with backoff when it merely closed.
 * Unmounting, or a different `callId`, aborts the request.
 */
export function useCallSpeaking(
  session: Session,
  callId: string,
  { enabled = true }: { enabled?: boolean } = {},
): CallSpeaking {
  const [state, setState] = useState<CallSpeaking>(IDLE);

  useEffect(() => {
    if (!enabled) {
      setState(IDLE);
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let ended = false;

    const connect = (): void => {
      openEventStream(session, callSpeakingPath(callId), {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.event !== "message") return;
          const frame = parseSpeakingFrame(event.data);
          if (frame === null) return;
          attempt = 0;
          if (!frame.live) ended = true;
          setState({ speaker: frame.live ? frame.speaker : null, live: frame.live });
        },
      })
        .then(() => retry())
        .catch((failure: unknown) => {
          if (controller.signal.aborted) return;
          if (failure instanceof ApiProblem && failure.status >= 400 && failure.status < 500 && failure.status !== 429) {
            ended = true;
          }
          retry();
        });
    };

    const retry = (): void => {
      if (controller.signal.aborted) return;
      if (ended) {
        setState(IDLE);
        return;
      }
      setState((current) => ({ speaker: null, live: current.live }));
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
      attempt += 1;
      timer = setTimeout(connect, delay);
    };

    connect();
    return () => {
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
    // `session` is the memoized value of `useClientSession()` (`lib/api/session.tsx`), so it
    // changes only when the account does — which should reopen the stream.
  }, [callId, enabled, session]);

  return state;
}
