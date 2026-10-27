"use client";

/**
 * Saved views of the Calls log (D-893 L2): `/v1/calls/views`, private to the person who
 * saved them, stored beside the Leads table's views.
 *
 * The query key starts `lead-views` like the Leads views', because both live in one table
 * and its live topic (`leads`, `lib/live/topics.ts`) refreshes that family; the third part
 * keeps the two screens' lists apart in the cache.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CallView = Schemas["CallSavedViewOut"];
export type CallViewFilters = Schemas["CallViewFilters"];

export interface CallViewBody {
  name: string;
  filters: CallViewFilters;
}

export const callViewsKey = (session: Session) => ["lead-views", session.orgSlug, "calls"];

export function useCallViews(session: Session): UseQueryResult<CallView[]> {
  return useQuery({
    queryKey: callViewsKey(session),
    queryFn: async () =>
      (await apiRequest<{ items: CallView[] }>(session, "/v1/calls/views")).items,
  });
}

export function useSaveCallView(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ viewId, body }: { viewId?: string; body: CallViewBody }) =>
      apiRequest<CallView>(session, viewId ? `/v1/calls/views/${viewId}` : "/v1/calls/views", {
        method: viewId ? "PATCH" : "POST",
        body,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: callViewsKey(session) }),
  });
}

export function useDeleteCallView(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (viewId: string) =>
      apiRequest<void>(session, `/v1/calls/views/${viewId}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: callViewsKey(session) }),
  });
}
