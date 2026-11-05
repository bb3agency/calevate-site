"use client";

/**
 * Make a call: one AI call to one person, now or at a chosen time (`POST /v1/one-calls`).
 *
 * The ONE form every Call button in the client console opens (founder, 5 Nov 2026). A lead's
 * Call and a call's Call back arrive here as a link (`makeCallHref`) carrying ids only, never
 * a number: a phone number in a URL lands in history, logs and referrers.
 *
 * The server does the work through the paths that already existed (`crm/one_call.py`): the
 * dial gate, the idempotency claim and the audit row of "call this lead", or one booked
 * call-back for a later time. `blocked` is the gate's answer with its own sentence, never
 * an error.
 */

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { callbackKeys, CALLBACK_LIST_LIMIT, type ScheduledCallback } from "./callbacks";
import { apiRequest, type CallSummary, type Session } from "./client";
import { queryKeys } from "./hooks";
import type { components } from "./schema";

export type OneCallInput = components["schemas"]["OneCallIn"];
export type OneCallResult = components["schemas"]["OneCallOut"];

/** The longest "why" and "details" the server takes (`crm/one_call.REASON_MAX`). */
export const REASON_MAX = 150;
export const DETAILS_MAX = 150;
export const NAME_MAX = 120;

/** How many recent calls the screen lists under the form. */
export const RECENT_LIMIT = 10;

export type MakeCallPrefill = {
  /** A lead on file: its Call button. */
  lead?: string;
  /** An earlier call: its Call back button. */
  call?: string;
  /** The agent the screen it came from had chosen. */
  agent?: string;
  /** Open on "At a time" (a lead's Call back later). */
  later?: boolean;
};

/** The Make a call screen, pre-filled. Ids only: never a number in a URL. */
export function makeCallHref(slug: string, prefill: MakeCallPrefill = {}): string {
  const search = new URLSearchParams();
  if (prefill.call) search.set("call", prefill.call);
  else if (prefill.lead) search.set("lead", prefill.lead);
  if (prefill.agent) search.set("agent", prefill.agent);
  if (prefill.later) search.set("when", "later");
  const query = search.toString();
  return `/c/${slug}/make-a-call${query ? `?${query}` : ""}`;
}

/**
 * Place or book the call.
 *
 * ONE `Idempotency-Key` PER ATTEMPT, HELD UNTIL AN ANSWER, `useCallAssist`'s rule. A fresh
 * key per press made a second press after a lost response (a timeout, a dropped connection)
 * a request the server had never seen, i.e. a second phone ringing. Holding it means that
 * press is answered from the first: replayed if it finished, refused "in flight" if the
 * vendor may be dialling. Keyed by the whole body, because the server hashes it into the
 * claim; success clears it, since the next press is a person asking for another call.
 */
export function useMakeCall(session: Session) {
  const client = useQueryClient();
  const held = useRef(new Map<string, string>());
  return useMutation({
    mutationFn: (input: OneCallInput) => {
      const attempt = JSON.stringify(input);
      const key = held.current.get(attempt) ?? crypto.randomUUID();
      held.current.set(attempt, key);
      return apiRequest<OneCallResult>(session, "/v1/one-calls", {
        method: "POST",
        body: input,
        idempotencyKey: key,
      });
    },
    onSuccess: (_result, input) => {
      held.current.delete(JSON.stringify(input));
      for (const queryKey of [
        ["calls", session.orgSlug],
        queryKeys.callsLog(session.orgSlug),
        callbackKeys.list(session.orgSlug, true),
        callbackKeys.list(session.orgSlug, false),
        ["leads", session.orgSlug],
        // A follow-up of a call changes that call's own eligibility and its follow-ups.
        ["callback-check", session.orgSlug],
        ["call", session.orgSlug],
      ]) {
        void client.invalidateQueries({ queryKey });
      }
    },
  });
}

/** The one-off calls people in this account placed, newest first. */
export function useRecentOneCalls(session: Session, enabled = true): UseQueryResult<CallSummary[]> {
  return useQuery({
    // Under the `calls` family, so every write that adds or marks a call refreshes it.
    queryKey: queryKeys.calls(session.orgSlug, { placed_by_person: true, limit: RECENT_LIMIT }),
    queryFn: () =>
      apiRequest<CallSummary[]>(
        session,
        `/v1/calls?placed_by_person=true&limit=${RECENT_LIMIT}&test_calls=false`,
      ),
    enabled,
  });
}

/** Calls a person booked for a time that have not rung yet, soonest first. */
export function useBookedOneCalls(
  session: Session,
  enabled = true,
): UseQueryResult<ScheduledCallback[]> {
  return useQuery({
    // Under the open call-backs key, so calling one off or moving it refreshes this too.
    queryKey: [...callbackKeys.list(session.orgSlug, true), "booked-by-person"],
    queryFn: () =>
      apiRequest<ScheduledCallback[]>(
        session,
        `/v1/callbacks?limit=${CALLBACK_LIST_LIMIT}&open_only=true&booked_by_person=true`,
      ),
    enabled,
  });
}
