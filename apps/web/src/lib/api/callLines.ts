"use client";

/**
 * How many calls one client may have at once (F7), the operator's setting.
 *
 *   GET /v1/admin/organizations/{org_id}/call-lines   `admin:tenants`
 *   PUT /v1/admin/organizations/{org_id}/call-lines   `admin:tenants`
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
    },
  });
}

export type MyCallLines = components["schemas"]["ClientCallLinesOut"];

/**
 * `GET /v1/call-lines` (`org:read`) — the client's own view: the lines in force and how
 * many are busy now. Read-only by design; only Calevate changes the number.
 */
export function useMyCallLines(session: Session): UseQueryResult<MyCallLines> {
  return useQuery({
    queryKey: ["my-call-lines", session.orgSlug],
    queryFn: () => apiRequest<MyCallLines>(session, "/v1/call-lines"),
  });
}

/** "2 calls at once", "1 call at once". */
export function callsAtOnce(lines: number): string {
  return `${lines} ${lines === 1 ? "call" : "calls"} at once`;
}
