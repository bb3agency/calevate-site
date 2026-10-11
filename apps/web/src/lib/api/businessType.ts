"use client";

/**
 * An account's business type, as an operator confirms it (D-722).
 *
 * Accounts created while the wizard pre-selected "Clinic" were given that type without
 * anybody choosing it. They now run on the neutral lead details until an operator confirms
 * a type; the AI's suggestion is shown beside the prompt and changes nothing by itself.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import { leadFieldsKeys } from "./leadFields";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type BusinessTypeState = Schemas["BusinessTypeOut"];
export type ConfirmBusinessTypeIn = Schemas["ConfirmBusinessTypeIn"];

export const businessTypeKeys = {
  admin: (tenantId: string) => ["admin", "business-type", tenantId] as const,
};

const path = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/business-type`;

export function useAdminBusinessType(tenantId: string): UseQueryResult<BusinessTypeState> {
  return useQuery({
    queryKey: businessTypeKeys.admin(tenantId),
    queryFn: () => apiRequest<BusinessTypeState>(adminSession(), path(tenantId)),
  });
}

export function useConfirmBusinessType(
  tenantId: string,
): UseMutationResult<BusinessTypeState, Error, ConfirmBusinessTypeIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<BusinessTypeState>(adminSession(), `${path(tenantId)}/confirm`, {
        method: "POST",
        body,
      }),
    onSuccess: (data) => {
      client.setQueryData(businessTypeKeys.admin(tenantId), data);
      void client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) });
      void client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] });
      void client.invalidateQueries({ queryKey: ["admin", "tenant-profile", tenantId] });
    },
  });
}

/**
 * "Suggest again": queues one AI suggestion (202). The answer arrives on the GET a few
 * seconds later, so the banner polls while `asking` is set.
 */
export function useSuggestBusinessTypeAgain(
  tenantId: string,
): UseMutationResult<BusinessTypeState, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<BusinessTypeState>(adminSession(), `${path(tenantId)}/suggest`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      client.setQueryData(businessTypeKeys.admin(tenantId), data);
    },
  });
}

/** Poll the GET until a suggestion newer than `since` arrives, for at most a minute. */
export function useBusinessTypePoll(
  tenantId: string,
  since: number | null,
): UseQueryResult<BusinessTypeState> {
  return useQuery({
    queryKey: businessTypeKeys.admin(tenantId),
    queryFn: () => apiRequest<BusinessTypeState>(adminSession(), path(tenantId)),
    enabled: since !== null,
    refetchInterval: (query) => {
      if (since === null || Date.now() - since > 60_000) return false;
      const at = query.state.data?.unconfirmed?.suggested_at;
      return at && Date.parse(at) >= since ? false : 3_000;
    },
  });
}
