"use client";

/**
 * Admin-realm prompt versioning hooks (apps/api/agents/prompt_routes.py).
 *
 * These live on the ADMIN surface with the tenant named in the path — same D-22 shape
 * as the KB approval hooks: impersonation is read-only, so prompt mutations can only
 * exist here. Interfaces are defined locally because these routes are not yet in the
 * generated OpenAPI schema; regenerate and alias once they are.
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

/** One row of `GET .../prompt` — newest first; `active` marks the live version. */
export interface PromptVersion {
  id: string;
  version: number;
  notes: string | null;
  created_at: string;
  active: boolean;
}

/** Body of `POST .../prompt` — the API enforces min 20 / max 8000 chars. */
export interface WritePromptIn {
  body: string;
  notes?: string;
}

export interface PromptWrittenOut {
  version: number;
}

export interface RollbackOut {
  to_version: number;
  new_version: number;
}

function promptPath(tenantId: string, agentId: string): string {
  return `/v1/admin/tenants/${tenantId}/agents/${agentId}/prompt`;
}

function historyKey(tenantId: string, agentId: string) {
  return ["admin", "prompt", tenantId, agentId] as const;
}

export function usePromptHistory(
  tenantId: string,
  agentId: string,
): UseQueryResult<PromptVersion[]> {
  return useQuery({
    queryKey: historyKey(tenantId, agentId),
    queryFn: () =>
      apiRequest<PromptVersion[]>(adminSession(), promptPath(tenantId, agentId)),
    enabled: Boolean(tenantId) && Boolean(agentId),
  });
}

export function useWritePrompt(
  tenantId: string,
  agentId: string,
): UseMutationResult<PromptWrittenOut, Error, WritePromptIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: WritePromptIn) =>
      apiRequest<PromptWrittenOut>(adminSession(), promptPath(tenantId, agentId), {
        method: "POST",
        body: payload,
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: historyKey(tenantId, agentId) }),
  });
}

/**
 * Rollback is copy-forward, never pointer-rewind (FLOWS §7): the API republishes the
 * chosen version's content as a NEW version, so history stays linear and audited.
 */
export function useRollbackPrompt(
  tenantId: string,
  agentId: string,
): UseMutationResult<RollbackOut, Error, { version: number }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ version }: { version: number }) =>
      apiRequest<RollbackOut>(
        adminSession(),
        `${promptPath(tenantId, agentId)}/rollback`,
        { method: "POST", body: { version } },
      ),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: historyKey(tenantId, agentId) }),
  });
}
