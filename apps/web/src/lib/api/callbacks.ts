/**
 * The call-backs promised to callers and leads (D-514, D-869, D-893).
 *
 * READ, MOVE AND CALL OFF, AND NO CREATE here: a call-back is booked by a caller mid-call
 * or on a lead (`swipe.ts`, "Call back later"), which keeps the person it is about. This
 * list changes when and whether one rings.
 *
 * Types alias the GENERATED schema (client.ts doctrine) so they cannot drift from the API.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type ScheduledCallback = components["schemas"]["ScheduledCallbackOut"];

/** Matches `callbacks/routes.MAX_PAGE`. The API refuses anything larger. */
export const CALLBACK_LIST_LIMIT = 200;

export const callbackKeys = {
  list: (slug: string, openOnly: boolean) => ["callbacks", slug, openOnly] as const,
};

/**
 * Every promise this account's agents made, most recent first.
 *
 * `openOnly` is part of the KEY and not just the query string: the two views hold
 * different rows, and sharing one cache entry would show a stale full list under the
 * filtered heading for the width of one refetch.
 */
export function useCallbacks(
  session: Session,
  openOnly = false,
): UseQueryResult<ScheduledCallback[]> {
  return useQuery({
    queryKey: callbackKeys.list(session.orgSlug, openOnly),
    queryFn: () =>
      apiRequest<ScheduledCallback[]>(
        session,
        `/v1/callbacks?limit=${CALLBACK_LIST_LIMIT}&open_only=${openOnly}`,
      ),
  });
}

/**
 * After a call-back changed: BOTH views rather than the one that issued it (a change moves
 * a row in one list and changes it in the other), and the call it was booked on and the
 * lead it is for, which both say what it came to.
 */
function refreshCallbacks(client: QueryClient, org: string): Promise<unknown> {
  return Promise.all(
    [
      callbackKeys.list(org, true),
      callbackKeys.list(org, false),
      ["call", org],
      ["calls", org],
      ["calls-log", org],
      ["callback-check", org],
      ["lead", org],
      ["leads", org],
    ].map((queryKey) => client.invalidateQueries({ queryKey })),
  );
}

/** Call one off before it rings. */
export function useCancelCallback(
  session: Session,
): UseMutationResult<ScheduledCallback, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (callbackId: string) =>
      apiRequest<ScheduledCallback>(session, `/v1/callbacks/${callbackId}`, {
        method: "DELETE",
      }),
    onSuccess: () => refreshCallbacks(client, session.orgSlug),
  });
}

export type CallbackChangeResult = components["schemas"]["CallbackChangeOut"];
export type CallbacksBulkResult = components["schemas"]["CallbacksBulkOut"];
export type CallbacksBulkBody = components["schemas"]["CallbacksBulkIn"];

/**
 * Move one that is still waiting (`PATCH /v1/callbacks/{id}`). `at` carries its offset
 * (`…+05:30`); the server holds it to 9am–9pm India time, as booking does.
 */
export function useMoveCallback(
  session: Session,
): UseMutationResult<ScheduledCallback, Error, { callbackId: string; at: string }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ callbackId, at }) =>
      apiRequest<ScheduledCallback>(session, `/v1/callbacks/${callbackId}`, {
        method: "PATCH",
        body: { at },
      }),
    onSuccess: () => refreshCallbacks(client, session.orgSlug),
  });
}

/**
 * Move or call off the ticked ones (`POST /v1/callbacks/bulk`), at most one page. Each is
 * changed on its own; the answer says, per call-back, what happened and why not.
 */
export function useChangeCallbacks(
  session: Session,
): UseMutationResult<CallbacksBulkResult, Error, CallbacksBulkBody> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<CallbacksBulkResult>(session, "/v1/callbacks/bulk", { method: "POST", body }),
    onSettled: () => refreshCallbacks(client, session.orgSlug),
  });
}
