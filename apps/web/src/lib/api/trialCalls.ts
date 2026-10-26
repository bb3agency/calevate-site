"use client";

/**
 * The client's free-trial panel and its test calls (D-697).
 *
 * `GET /v1/trial` says whether this account is on a free trial and, if so, its days and
 * minutes left and today's test calls against the daily cap. `POST /v1/trial/calls` places
 * one test call from an agent to a number the client types, and answers with our id for it
 * and the number it rings from; `GET /v1/trial/calls[/{id}]` reads them back (D-885).
 */

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { livePoll } from "@/lib/live/liveStatus";

import { apiRequest, type Session } from "./client";
import { queryKeys } from "./hooks";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TrialPanel = Schemas["TrialPanelOut"];
export type TrialCallResult = Schemas["TrialCallOut"];

export function trialPanelKey(slug: string) {
  return ["trial", slug];
}

export function useTrialPanel(session: Session, enabled = true): UseQueryResult<TrialPanel> {
  return useQuery({
    queryKey: trialPanelKey(session.orgSlug),
    queryFn: () => apiRequest<TrialPanel>(session, "/v1/trial"),
    enabled,
  });
}

/** One test call as the dashboard card follows it (D-885). */
export type TestCall = Schemas["TestCallOut"];

/** The statuses a call is still running in; every other one has ended. */
const LIVE_STATUSES: ReadonlySet<string> = new Set(["queued", "ringing", "in_progress"]);

export function testCallIsLive(call: { status: string }): boolean {
  return LIVE_STATUSES.has(call.status);
}

/**
 * How often a running test call is read: often enough that "Ringing" turns into
 * "Connected" while the person still has the phone at their ear.
 */
export const TEST_CALL_POLL_MS = 4_000;

/**
 * Past this long after it was placed a call that still reads as live is not going to move
 * (the longest test call is a few minutes), so the card stops asking.
 */
const TEST_CALL_FOLLOW_MS = 20 * 60_000;

/** How long after a call ends its one-line summary is still worth waiting for. */
const HEADLINE_WAIT_MS = 10 * 60_000;

function young(call: TestCall, windowMs: number, now = Date.now()): boolean {
  const placed = Date.parse(call.placed_at);
  return Number.isFinite(placed) && now - placed < windowMs;
}

/**
 * When the card reads one test call again. WHILE IT RUNS this is a fixed short interval and
 * deliberately not `livePoll`: our call row says nothing between the dial and the end (the
 * voice platform reports the end only), so the live stream has nothing to announce, and the
 * server asks the platform for "ringing" or "connected" on each read. Once it ends, the
 * summary arrives as a write to the call, which the stream does announce, so the wait for
 * it is `livePoll`'s. Then nothing.
 */
export function testCallPollMs(call: TestCall | undefined, now = Date.now()): number | false {
  if (call === undefined) return TEST_CALL_POLL_MS;
  if (testCallIsLive(call)) return young(call, TEST_CALL_FOLLOW_MS, now) ? TEST_CALL_POLL_MS : false;
  return call.status === "completed" && !call.headline && young(call, HEADLINE_WAIT_MS, now) ? 20_000 : false;
}

export function testCallKey(slug: string, callId: string) {
  return ["trial", slug, "calls", callId];
}

export function useTestCall(session: Session, callId: string): UseQueryResult<TestCall> {
  return useQuery({
    queryKey: testCallKey(session.orgSlug, callId),
    queryFn: () => apiRequest<TestCall>(session, `/v1/trial/calls/${callId}`),
    refetchInterval: (query) => {
      const base = testCallPollMs(query.state.data);
      return base === TEST_CALL_POLL_MS ? base : livePoll(base)(query);
    },
  });
}

/** Today's test calls, newest first, so the card still shows them after a reload. */
export function useRecentTestCalls(session: Session, enabled = true): UseQueryResult<TestCall[]> {
  return useQuery({
    queryKey: ["trial", session.orgSlug, "calls"],
    queryFn: () => apiRequest<TestCall[]>(session, "/v1/trial/calls"),
    enabled,
  });
}

/**
 * Place one test call. ONE `Idempotency-Key` PER ATTEMPT, held until an answer, the rule
 * `useCallLead` follows: a second press after a lost response is answered from the first
 * rather than ringing the person a second time.
 */
export function usePlaceTrialCall(session: Session) {
  const client = useQueryClient();
  const held = useRef(new Map<string, string>());
  const attemptOf = (agentId: string, number: string) => JSON.stringify([agentId, number]);
  return useMutation({
    mutationFn: ({
      agentId,
      number,
      numberIsMine = false,
    }: {
      agentId: string;
      number: string;
      /** The owner ticked "this number is mine" (D-855); recorded by the server. */
      numberIsMine?: boolean;
    }) => {
      const attempt = attemptOf(agentId, number);
      const key = held.current.get(attempt) ?? crypto.randomUUID();
      held.current.set(attempt, key);
      return apiRequest<TrialCallResult>(session, "/v1/trial/calls", {
        method: "POST",
        body: numberIsMine ? { agent_id: agentId, number, number_is_mine: true } : { agent_id: agentId, number },
        idempotencyKey: key,
      });
    },
    onSuccess: (_result, { agentId, number }) => {
      held.current.delete(attemptOf(agentId, number));
      void client.invalidateQueries({ queryKey: trialPanelKey(session.orgSlug) });
      // The dashboard's trial card reads the trial from the dashboard read (D-786).
      void client.invalidateQueries({ queryKey: queryKeys.dashboard(session.orgSlug) });
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
      void client.invalidateQueries({ queryKey: queryKeys.callsLog(session.orgSlug) });
    },
  });
}
