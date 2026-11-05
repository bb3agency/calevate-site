"use client";

/**
 * How many calls one client may have at once (F7), the operator's setting.
 *
 *   GET /v1/admin/organizations/{org_id}/call-lines   `admin:tenants`
 *   PUT /v1/admin/organizations/{org_id}/call-lines   `admin:tenants`
 *
 * and a client's request for more (`POST /v1/call-lines/requests`), which an operator
 * answers by raising the number or declining it; the console bell lists the open ones.
 *
 * `null` is Calevate's default (the server's `paid_default` / `trial_default`); the screen
 * renders `call_lines` and `source` as they arrive and never works out the default itself.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession, callLinesConfirmation, confirmedAdminRequest } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type CallLines = components["schemas"]["CallLinesOut"];
export type CallLinesIn = components["schemas"]["CallLinesIn"];

export const callLinesPath = (tenantId: string) => `/v1/admin/organizations/${tenantId}/call-lines`;
const callLinesKey = (tenantId: string) => ["call-lines", tenantId] as const;

export function useCallLines(tenantId: string): UseQueryResult<CallLines> {
  return useQuery({
    queryKey: callLinesKey(tenantId),
    queryFn: () => apiRequest<CallLines>(adminSession(), callLinesPath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

export function useSetCallLines(tenantId: string): UseMutationResult<CallLines, Error, CallLinesIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CallLinesIn) =>
      confirmedAdminRequest<CallLines>(
        callLinesPath(tenantId),
        { method: "PUT", body: payload, confirmAction: callLinesConfirmation(tenantId) },
        "Changing how many calls this client may have at once.",
      ),
    onSuccess: (data) => {
      client.setQueryData(callLinesKey(tenantId), data);
      // A raise closes the client's open request, which the console bell lists.
      void client.invalidateQueries({ queryKey: OPEN_CALL_LINE_REQUESTS_KEY });
    },
  });
}

export type MyCallLines = components["schemas"]["ClientCallLinesOut"];

/**
 * `GET /v1/call-lines` (`org:read`) — the client's own view: the lines in force, how many
 * are busy now, and its request for more. Only Calevate changes the number; the client asks.
 */
export function useMyCallLines(session: Session): UseQueryResult<MyCallLines> {
  return useQuery({
    queryKey: myCallLinesKey(session),
    queryFn: () => apiRequest<MyCallLines>(session, "/v1/call-lines"),
  });
}

const myCallLinesKey = (session: Session) => ["my-call-lines", session.orgSlug] as const;

export type CallLineRequest = components["schemas"]["CallLineRequestOut"];
export type CallLineRequestIn = components["schemas"]["CallLineRequestIn"];

/**
 * `POST /v1/call-lines/requests` (`org:manage`) — ask Calevate for more calls at once. A
 * second ask while one is open answers the open one (200), so a double tap is harmless.
 */
export function useAskForMoreLines(
  session: Session,
): UseMutationResult<CallLineRequest, Error, CallLineRequestIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CallLineRequestIn) =>
      apiRequest<CallLineRequest>(session, "/v1/call-lines/requests", { method: "POST", body: payload }),
    onSuccess: (request) => {
      client.setQueryData<MyCallLines>(myCallLinesKey(session), (old) => (old ? { ...old, request } : old));
    },
  });
}

export type OpenCallLineRequest = components["schemas"]["OpenCallLineRequestOut"];
export const OPEN_CALL_LINE_REQUESTS_KEY = ["call-line-requests"] as const;
export const OPEN_CALL_LINE_REQUESTS_PATH = "/v1/admin/call-line-requests";

/** `GET /v1/admin/call-line-requests` (`org:read`, admin) — the console bell's list. */
export function useOpenCallLineRequests(): UseQueryResult<OpenCallLineRequest[]> {
  return useQuery({
    queryKey: OPEN_CALL_LINE_REQUESTS_KEY,
    queryFn: () => apiRequest<OpenCallLineRequest[]>(adminSession(), OPEN_CALL_LINE_REQUESTS_PATH),
  });
}

/** Where an operator raises one client's lines: its Numbers page with the control open. */
export function callLinesPagePath(tenantId: string): string {
  return `/admin/tenants/${tenantId}/numbers?focus=call-lines`;
}

/** `POST .../call-lines/requests/{id}/decline` (`admin:tenants`) — "no", and why. */
export function useDeclineCallLinesRequest(
  tenantId: string,
): UseMutationResult<CallLineRequest, Error, { requestId: string; reason: string }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, reason }) =>
      apiRequest<CallLineRequest>(adminSession(), `${callLinesPath(tenantId)}/requests/${requestId}/decline`, {
        method: "POST",
        body: { reason },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: callLinesKey(tenantId) });
      void client.invalidateQueries({ queryKey: OPEN_CALL_LINE_REQUESTS_KEY });
    },
  });
}

/** "2 calls at once", "1 call at once". */
export function callsAtOnce(lines: number): string {
  return `${lines} ${lines === 1 ? "call" : "calls"} at once`;
}
