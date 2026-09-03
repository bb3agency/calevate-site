/**
 * The call-backs an agent promised on a call (D-514).
 *
 * READ AND CANCEL, AND NO CREATE, which mirrors the API deliberately rather than by
 * omission: a call-back exists because a caller asked for one mid-call, and the only
 * booking path is the agent's in-call tool. "Ring this lead" is a different button on a
 * different screen (`leads.ts`), and conflating them here would put a way to make the
 * platform phone somebody behind a list view.
 *
 * Types alias the GENERATED schema (client.ts doctrine) so they cannot drift from the API.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
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
 * Call one off before it rings.
 *
 * Invalidates BOTH views rather than the one that issued it: cancelling removes a row
 * from the open list and changes a row in the full one, and a client who cancels from the
 * filtered view and then clears the filter must not read "waiting" about a promise they
 * just stopped.
 */
export function useCancelCallback(
  session: Session,
): UseMutationResult<ScheduledCallback, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (callbackId: string) =>
      apiRequest<ScheduledCallback>(session, `/v1/callbacks/${callbackId}`, {
        method: "DELETE",
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: callbackKeys.list(session.orgSlug, true) }),
        client.invalidateQueries({ queryKey: callbackKeys.list(session.orgSlug, false) }),
      ]),
  });
}
