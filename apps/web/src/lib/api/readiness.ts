"use client";

/**
 * The readiness gauge (D-870): one agent's 0-100 score and the account's.
 *
 * Each component carries its points and a sentence; each fix carries `action` (one plain
 * sentence) and `href`, a REALM-RELATIVE link ("/agents/{id}?section=script",
 * "/knowledge") to prefix with the realm's own `href()`. Fixes come biggest gain first.
 * The formula is `apps/api/agents/readiness.py`'s docstring.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AgentReadiness = Schemas["AgentReadinessOut"];
export type AccountReadiness = Schemas["AccountReadinessOut"];
export type ReadinessComponent = Schemas["ReadinessComponentOut"];
export type ReadinessFix = Schemas["ReadinessFixOut"];

export const readinessKeys = {
  all: (org: string) => ["readiness", org] as const,
  agent: (org: string, agentId: string) => ["readiness", org, "agent", agentId] as const,
  account: (org: string) => ["readiness", org, "account"] as const,
};

export function useAgentReadiness(
  session: Session,
  agentId: string | undefined,
): UseQueryResult<AgentReadiness> {
  return useQuery({
    queryKey: readinessKeys.agent(session.orgSlug, agentId ?? ""),
    queryFn: () => apiRequest<AgentReadiness>(session, `/v1/agents/${agentId}/readiness`),
    enabled: Boolean(agentId),
  });
}

export function useAccountReadiness(session: Session): UseQueryResult<AccountReadiness> {
  return useQuery({
    queryKey: readinessKeys.account(session.orgSlug),
    queryFn: () => apiRequest<AccountReadiness>(session, "/v1/readiness"),
  });
}
