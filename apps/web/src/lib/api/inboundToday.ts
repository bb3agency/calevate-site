"use client";

/**
 * An inbound line's day and the people it still owes a call (W4.1, W4.2), its "call back
 * missed callers" switch, and how long the account keeps call recordings (W12.9).
 *
 * `/v1/inbound-lines/today`, `/v1/inbound-lines/{id}/callers` and
 * `/v1/inbound-lines/{id}/missed-call-back` count and read only our own call rows and
 * Follow-ups (`apps/api/inbound/today.py`, `apps/api/follow_ups/starters.py`).
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type InboundToday = Schemas["InboundTodayOut"];
export type LineToday = Schemas["LineTodayOut"];
export type LineCallers = Schemas["LineCallersOut"];
export type OwedCaller = Schemas["OwedCallerOut"];
export type LineCallBack = Schemas["LineCallBackOut"];
export type CallRetention = Schemas["CallsKeptOut"];

const linePath = (lineId: string) => `/v1/inbound-lines/${encodeURIComponent(lineId)}`;

/**
 * Keys in the families the live notes already refresh (`lib/live/topics.ts`): a call that
 * ends moves "inbound-line-calls", a Follow-up switched on or off moves "follow-ups".
 */
export const inboundTodayKeys = {
  today: (org: string) => ["inbound-line-calls", org, "today"] as const,
  callers: (org: string, lineId: string) => ["inbound-line-calls", org, lineId, "callers"] as const,
  callBack: (org: string, lineId: string) => ["follow-ups", org, "line-call-back", lineId] as const,
  retention: (org: string) => ["call-retention", org] as const,
};

export function useInboundToday(session: Session, enabled = true): UseQueryResult<InboundToday> {
  return useQuery({
    queryKey: inboundTodayKeys.today(session.orgSlug),
    queryFn: () => apiRequest<InboundToday>(session, "/v1/inbound-lines/today"),
    enabled,
  });
}

/** One line's counts out of the account's, zeros for a line with nothing today. */
export function todayOf(data: InboundToday | undefined, lineId: string): LineToday | undefined {
  if (!data) return undefined;
  return (
    data.lines.find((line) => line.line_id === lineId) ?? {
      line_id: lineId,
      answered: 0,
      call_back: 0,
      missed: 0,
      waiting: 0,
    }
  );
}

export function useLineCallers(session: Session, lineId: string, enabled = true): UseQueryResult<LineCallers> {
  return useQuery({
    queryKey: inboundTodayKeys.callers(session.orgSlug, lineId),
    queryFn: () => apiRequest<LineCallers>(session, `${linePath(lineId)}/callers`),
    enabled,
  });
}

export function useLineCallBack(session: Session, lineId: string): UseQueryResult<LineCallBack> {
  return useQuery({
    queryKey: inboundTodayKeys.callBack(session.orgSlug, lineId),
    queryFn: () => apiRequest<LineCallBack>(session, `${linePath(lineId)}/missed-call-back`),
  });
}

/** Switch it; the answer is the state read back from the live Follow-ups. */
export function useSetLineCallBack(session: Session, lineId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) =>
      apiRequest<LineCallBack>(session, `${linePath(lineId)}/missed-call-back`, { method: "PUT", body: { on } }),
    onSuccess: (data) => {
      client.setQueryData(inboundTodayKeys.callBack(session.orgSlug, lineId), data);
      // The Follow-ups list shows the line's Follow-up too.
      void client.invalidateQueries({ queryKey: ["follow-ups", session.orgSlug] });
    },
  });
}

export function useCallRetention(session: Session): UseQueryResult<CallRetention> {
  return useQuery({
    queryKey: inboundTodayKeys.retention(session.orgSlug),
    queryFn: () => apiRequest<CallRetention>(session, "/v1/calls/kept"),
    // Changed only from the admin console's retention settings.
    staleTime: 10 * 60_000,
  });
}
