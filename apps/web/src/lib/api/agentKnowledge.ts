/**
 * The operator's per-agent knowledge list (D-868): everything one agent holds on the voice
 * platform, ours and not, and the client's live items not on it with the reason.
 *
 *   GET  /v1/admin/tenants/{tid}/agents/{aid}/knowledge         the list
 *   POST /v1/admin/tenants/{tid}/agents/{aid}/knowledge/remove  remove one we did not send
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
export type AgentKnowledge = Schemas["AgentKnowledgeOut"];
export type AgentKnowledgeItem = Schemas["AgentKnowledgeItemOut"];

const path = (tenantId: string, agentId: string) =>
  `/v1/admin/tenants/${tenantId}/agents/${agentId}/knowledge`;
const key = (tenantId: string, agentId: string) => ["agent-knowledge", tenantId, agentId] as const;

export function useAdminAgentKnowledge(
  tenantId: string,
  agentId: string,
): UseQueryResult<AgentKnowledge> {
  return useQuery({
    queryKey: key(tenantId, agentId),
    queryFn: () => apiRequest<AgentKnowledge>(adminSession(), path(tenantId, agentId)),
    enabled: Boolean(tenantId) && Boolean(agentId),
  });
}

export function useAdminRemoveAgentDocument(
  tenantId: string,
  agentId: string,
): UseMutationResult<void, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (handle: string) =>
      apiRequest<void>(adminSession(), `${path(tenantId, agentId)}/remove`, {
        method: "POST",
        body: { handle },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(tenantId, agentId) }),
  });
}
