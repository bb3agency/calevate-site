"use client";

/**
 * The longest reply one agent may give, in tokens (D-769, admin only).
 *
 *   GET   /v1/admin/tenants/{tid}/agents/{aid}/reply-length   `admin:tenants`
 *   PATCH /v1/admin/tenants/{tid}/agents/{aid}/reply-length   `agents:write`, audited
 *
 * `max_reply_tokens` null inherits the console's default, which the read reports beside it.
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
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type ReplyLength = Schemas["ReplyLengthOut"];
export type ReplyLengthIn = Schemas["ReplyLengthIn"];

const PATH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/reply-length" satisfies keyof paths;

export function replyLengthPath(tenantId: string, agentId: string): string {
  return PATH.replace("{tenant_id}", tenantId).replace("{agent_id}", agentId);
}

export const replyLengthKey = (tenantId: string, agentId: string) =>
  ["reply-length", tenantId, agentId] as const;

export function useReplyLength(tenantId: string, agentId: string): UseQueryResult<ReplyLength> {
  return useQuery({
    queryKey: replyLengthKey(tenantId, agentId),
    queryFn: () => apiRequest<ReplyLength>(adminSession(), replyLengthPath(tenantId, agentId)),
    enabled: Boolean(tenantId) && Boolean(agentId),
  });
}

export function useSetReplyLength(
  tenantId: string,
  agentId: string,
): UseMutationResult<ReplyLength, Error, ReplyLengthIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ReplyLengthIn) =>
      apiRequest<ReplyLength>(adminSession(), replyLengthPath(tenantId, agentId), {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: (data) => {
      client.setQueryData(replyLengthKey(tenantId, agentId), data);
    },
  });
}
