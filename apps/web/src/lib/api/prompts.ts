"use client";

/**
 * Admin-realm prompt versioning hooks (apps/api/agents/prompt_routes.py).
 *
 * These live on the ADMIN surface with the tenant named in the path — same D-22 shape
 * as the KB approval hooks: impersonation is read-only, so prompt mutations can only
 * exist here.
 *
 * These four shapes used to be hand-written interfaces, with a note saying to alias
 * them once the routes reached the generated schema. They have — `pnpm gen:api` now
 * emits `PromptVersionOut`, `WritePromptIn`, `PromptWrittenOut` and `RollbackOut` —
 * so they are aliased, and the hand-written copies are gone. One of them had already
 * drifted: the local `WritePromptIn.notes` was `string | undefined`, while the server
 * model accepts `string | null` and caps it at 200 characters. A hand-written request
 * body is exactly the drift the "typed client generated from OpenAPI" convention
 * exists to prevent, so nothing here restates a field the server already declares.
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
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One row of `GET .../prompt` — newest first; `active` marks the live version. */
export type PromptVersion = Schemas["PromptVersionOut"];

/** Body of `POST .../prompt` — the API enforces min 20 / max 8000 chars on `body`. */
export type WritePromptIn = Schemas["WritePromptIn"];

export type PromptWrittenOut = Schemas["PromptWrittenOut"];

/** Body of `POST .../prompt/rollback` — the version to copy forward. */
export type RollbackIn = Schemas["RollbackIn"];

export type RollbackOut = Schemas["RollbackOut"];

function promptPath(tenantId: string, agentId: string): string {
  return `/v1/admin/tenants/${tenantId}/agents/${agentId}/prompt`;
}

/**
 * Exported because `publishing.ts` has to invalidate it: applying or undoing a staged
 * script moves which version is live, and `active` on every row of this list is that
 * pointer. Two modules writing the same key literal is how one of them ends up
 * invalidating nothing after a rename.
 */
export function promptHistoryKey(tenantId: string, agentId: string) {
  return ["admin", "prompt", tenantId, agentId] as const;
}

export function usePromptHistory(
  tenantId: string,
  agentId: string,
): UseQueryResult<PromptVersion[]> {
  return useQuery({
    queryKey: promptHistoryKey(tenantId, agentId),
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
      void client.invalidateQueries({ queryKey: promptHistoryKey(tenantId, agentId) }),
  });
}

/**
 * Rollback is copy-forward, never pointer-rewind (FLOWS §7): the API republishes the
 * chosen version's content as a NEW version, so history stays linear and audited.
 */
export function useRollbackPrompt(
  tenantId: string,
  agentId: string,
): UseMutationResult<RollbackOut, Error, RollbackIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ version }: RollbackIn) =>
      apiRequest<RollbackOut>(
        adminSession(),
        `${promptPath(tenantId, agentId)}/rollback`,
        { method: "POST", body: { version } },
      ),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: promptHistoryKey(tenantId, agentId) }),
  });
}
