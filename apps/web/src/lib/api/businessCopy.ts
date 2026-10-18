"use client";

/**
 * The account's own examples and suggestions, written by AI from its business details and
 * its calls (D-827): the placeholders the per-trade table serves, suggested script steps,
 * details to ask callers and example questions.
 *
 * Read by every client screen that shows an example (`useVerticalExamples`) and by the
 * Business profile screen, which says when they were last refreshed. Asking for a refresh
 * is Pip's (`business_copy_refresh`). Operators read the same copy with its cost and
 * refresh it at our cost.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type BusinessCopy = Schemas["BusinessCopyOut"];
export type AdminBusinessCopy = Schemas["AdminBusinessCopyOut"];
export type GeneratedPlaceholders = Schemas["Placeholders"];
export type StepSuggestion = Schemas["StepSuggestion"];

export const businessCopyKeys = {
  client: (org: string) => ["business-copy", org] as const,
  admin: (tenantId: string) => ["admin", "business-copy", tenantId] as const,
};

/** While a run is in progress the screen asks again on this interval, then stops. */
export const REFRESH_POLL_MS = 4000;

const adminPath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/business-copy`;

export function useBusinessCopy(session: Session): UseQueryResult<BusinessCopy> {
  return useQuery({
    queryKey: businessCopyKeys.client(session.orgSlug),
    queryFn: () => apiRequest<BusinessCopy>(session, "/v1/business-copy"),
    // The copy changes once a fortnight at most; every screen shares this one read.
    staleTime: 5 * 60_000,
    refetchInterval: (query) => (query.state.data?.refreshing ? REFRESH_POLL_MS : false),
  });
}

export function useAdminBusinessCopy(tenantId: string): UseQueryResult<AdminBusinessCopy> {
  return useQuery({
    queryKey: businessCopyKeys.admin(tenantId),
    queryFn: () => apiRequest<AdminBusinessCopy>(adminSession(), adminPath(tenantId)),
    refetchInterval: (query) => (query.state.data?.refreshing ? REFRESH_POLL_MS : false),
  });
}

/** The operator's refresh (202): queued at our cost; the GET polls until it lands. */
export function useAdminRefreshBusinessCopy(
  tenantId: string,
): UseMutationResult<AdminBusinessCopy, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<AdminBusinessCopy>(adminSession(), `${adminPath(tenantId)}/refresh`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      client.setQueryData(businessCopyKeys.admin(tenantId), data);
    },
  });
}
