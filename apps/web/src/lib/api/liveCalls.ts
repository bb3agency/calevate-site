"use client";

/**
 * Where the calls the call log shows as live stand now (D-886): `GET /v1/calls/live`.
 *
 * An outbound call's row says `queued` from the dial to the end, because the voice platform
 * reports nothing in between, so the live stream has nothing to announce while it rings or
 * talks. This read asks for the log's live rows by id and the server asks the platform, one
 * read per call. It polls on a short fixed interval, not `livePoll`, for the same reason the
 * dashboard's test-call card does (`trialCalls.testCallPollMs`), and only while ids are
 * given: the log passes none once no row is live, and the server stops calling a row live
 * past the longest a call can run, so the poll always ends.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type CallLive = components["schemas"]["CallLiveOut"];

/** Often enough that "Ringing" turns into "On the call" while the person is still talking. */
export const LIVE_CALLS_POLL_MS = 4_000;

/** The most ids one read takes (`crm/live_calls.MAX_LIVE_IDS`). */
export const MAX_LIVE_IDS = 20;

export function liveCallsKey(slug: string, ids: readonly string[]) {
  return ["calls-live", slug, [...ids].sort()];
}

export function useLiveCalls(session: Session, ids: readonly string[]): UseQueryResult<CallLive[]> {
  const asked = ids.slice(0, MAX_LIVE_IDS);
  return useQuery({
    queryKey: liveCallsKey(session.orgSlug, asked),
    queryFn: () => {
      const search = new URLSearchParams();
      for (const id of asked) search.append("ids", id);
      return apiRequest<CallLive[]>(session, `/v1/calls/live?${search.toString()}`);
    },
    enabled: asked.length > 0,
    refetchInterval: asked.length > 0 ? LIVE_CALLS_POLL_MS : false,
    // Keep the last answer while the id set changes, so a row does not flicker back to
    // "Dialling" for the moment the next read is out.
    placeholderData: (previous) => previous,
  });
}
