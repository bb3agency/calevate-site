/**
 * Each client's own ThinnestAI customer workspace, run by an operator (D-693).
 *
 * The operator's half of `ownNumbers.ts`: the same purchase gates and the same charge to the
 * client, plus the levers only an operator has — retry provisioning, offboard a closed
 * account, send or re-read the business details, and "Release our record" for a number the
 * platform no longer holds or a platform-held test number being taken back.
 *
 * In its own module rather than `numbers.ts` for that file's reason: these spend money at a
 * vendor on a recurring commitment, and a caller should import them from a file named for it.
 */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TenantWorkspace = Schemas["TenantWorkspaceOut"];
export type WorkspacesSummary = Schemas["WorkspacesSummaryOut"];
export type WorkspaceBusinessDetails = Schemas["BusinessDetailsStateOut"];
export type AdminCity = Schemas["AdminCityOut"];
export type AdminAvailableNumber = Schemas["AdminAvailableNumberOut"];
export type AdminAvailableNumbers = Schemas["AdminAvailableNumbersOut"];
export type AdminPurchaseIn = Schemas["AdminPurchaseIn"];
export type AdminPurchased = Schemas["AdminPurchasedOut"];
export type AdminReleased = Schemas["AdminReleasedOut"];

const BASE = "/v1/admin/engine-workspaces";

export const WORKSPACE_PATHS = {
  summary: `${BASE}/summary`,
  tenant: (tenantId: string) => `${BASE}/tenants/${tenantId}`,
  provision: (tenantId: string) => `${BASE}/tenants/${tenantId}/provision`,
  offboard: (tenantId: string) => `${BASE}/tenants/${tenantId}/offboard`,
  businessDetails: (tenantId: string) => `${BASE}/tenants/${tenantId}/business-details`,
  refreshDetails: (tenantId: string) => `${BASE}/tenants/${tenantId}/business-details/refresh`,
  cities: (tenantId: string) => `${BASE}/tenants/${tenantId}/numbers/cities`,
  available: (tenantId: string, city: string, pattern: string, cursor: string | null) => {
    const query = new URLSearchParams({ city });
    if (pattern) query.set("pattern", pattern);
    if (cursor) query.set("cursor", cursor);
    return `${BASE}/tenants/${tenantId}/numbers/available?${query.toString()}`;
  },
  purchase: (tenantId: string) => `${BASE}/tenants/${tenantId}/numbers/purchase`,
  release: (tenantId: string, numberId: string) =>
    `${BASE}/tenants/${tenantId}/numbers/${numberId}/release`,
  forget: (tenantId: string, numberId: string) =>
    `${BASE}/tenants/${tenantId}/numbers/${numberId}/forget`,
} as const;

const tenantKey = (tenantId: string) => ["admin", "engine-workspace", tenantId] as const;

export function useWorkspacesSummary(enabled = true) {
  return useQuery({
    queryKey: ["admin", "engine-workspaces", "summary"],
    queryFn: () => apiRequest<WorkspacesSummary>(adminSession(), WORKSPACE_PATHS.summary),
    enabled,
  });
}

export function useTenantWorkspace(tenantId: string) {
  return useQuery({
    queryKey: tenantKey(tenantId),
    queryFn: () => apiRequest<TenantWorkspace>(adminSession(), WORKSPACE_PATHS.tenant(tenantId)),
    enabled: Boolean(tenantId),
  });
}

/** Every number-shaped read on the tenant's screen moves when a workspace action lands. */
function useInvalidateTenant(tenantId: string) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: tenantKey(tenantId) });
    void client.invalidateQueries({ queryKey: ["admin", "engine-numbers", tenantId] });
    void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
    void client.invalidateQueries({ queryKey: ["admin", "engine-workspaces", "summary"] });
  };
}

/** A body-less POST that answers the workspace's new state. */
function useWorkspaceAction(tenantId: string, path: (tenantId: string) => string) {
  const invalidate = useInvalidateTenant(tenantId);
  return useMutation({
    mutationFn: () => apiRequest<unknown>(adminSession(), path(tenantId), { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useProvisionWorkspace(tenantId: string) {
  return useWorkspaceAction(tenantId, WORKSPACE_PATHS.provision);
}

export function useOffboardWorkspace(tenantId: string) {
  return useWorkspaceAction(tenantId, WORKSPACE_PATHS.offboard);
}

export function useSendWorkspaceBusinessDetails(tenantId: string) {
  return useWorkspaceAction(tenantId, WORKSPACE_PATHS.businessDetails);
}

export function useRefreshWorkspaceBusinessDetails(tenantId: string) {
  return useWorkspaceAction(tenantId, WORKSPACE_PATHS.refreshDetails);
}

export function useWorkspaceCities(tenantId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...tenantKey(tenantId), "cities"],
    queryFn: () => apiRequest<AdminCity[]>(adminSession(), WORKSPACE_PATHS.cities(tenantId)),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useWorkspaceAvailableNumbers(
  tenantId: string,
  search: { city: string; pattern: string } | null,
) {
  return useInfiniteQuery({
    queryKey: [...tenantKey(tenantId), "available", search?.city ?? "", search?.pattern ?? ""],
    queryFn: ({ pageParam }) =>
      apiRequest<AdminAvailableNumbers>(
        adminSession(),
        WORKSPACE_PATHS.available(tenantId, search?.city ?? "", search?.pattern ?? "", pageParam),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last: AdminAvailableNumbers) => last.next_cursor,
    enabled: search !== null,
    staleTime: 60_000,
    retry: false,
  });
}

/** **Spends the client's money.** The caller holds `request_key` across retries. */
export function useWorkspacePurchase(tenantId: string) {
  const invalidate = useInvalidateTenant(tenantId);
  return useMutation({
    retry: false,
    mutationFn: (body: AdminPurchaseIn) =>
      apiRequest<AdminPurchased>(adminSession(), WORKSPACE_PATHS.purchase(tenantId), {
        method: "POST",
        body,
      }),
    onSuccess: invalidate,
  });
}

export function useWorkspaceRelease(tenantId: string) {
  const invalidate = useInvalidateTenant(tenantId);
  return useMutation({
    mutationFn: (numberId: string) =>
      apiRequest<AdminReleased>(adminSession(), WORKSPACE_PATHS.release(tenantId, numberId), {
        method: "POST",
        body: { confirm: true },
      }),
    onSuccess: invalidate,
  });
}

export function useWorkspaceForget(tenantId: string) {
  const invalidate = useInvalidateTenant(tenantId);
  return useMutation({
    mutationFn: (numberId: string) =>
      apiRequest<AdminReleased>(adminSession(), WORKSPACE_PATHS.forget(tenantId, numberId), {
        method: "POST",
        body: { confirm: true },
      }),
    onSuccess: invalidate,
  });
}
