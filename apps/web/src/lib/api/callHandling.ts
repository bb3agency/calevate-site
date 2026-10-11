"use client";

/**
 * The pause before an agent replies and hanging up when it has finished (D-751).
 *
 *   GET   /v1/agents/{agent_id}/call-handling                    `agents:read`
 *   PATCH /v1/agents/{agent_id}/call-handling                    `org:manage` (the owner)
 *   GET   /v1/organization/call-handling                         `org:read`
 *   PUT   /v1/organization/call-handling                         `org:manage`
 *   PATCH /v1/admin/tenants/{tid}/agents/{aid}/call-handling     the operator's door
 *
 * Each value resolves agent, then the account default, then Calevate's, on the server; the
 * screens render `*_effective` and `*_source` as they arrive and never resolve it themselves.
 * The pause is whole milliseconds on the wire; seconds are only for people.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession, viewAsSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AgentCallHandling = Schemas["AgentCallHandlingOut"];
export type AgentCallHandlingIn = Schemas["AgentCallHandlingIn"];
export type OrganizationCallHandling = Schemas["OrganizationCallHandlingOut"];
export type OrganizationCallHandlingIn = Schemas["OrganizationCallHandlingIn"];
export type CallHandlingSource = AgentCallHandling["turn_silence_source"];

export const ORGANIZATION_CALL_HANDLING_PATH = "/v1/organization/call-handling";

export const callHandlingKeys = {
  organization: (org: string) => ["call-handling", org, "organization"] as const,
  agent: (org: string, agentId: string) => ["call-handling", org, "agent", agentId] as const,
  /** Every agent's read for one org: an account default moves the ones that inherit it. */
  agents: (org: string) => ["call-handling", org, "agent"] as const,
};

/** The three pauses offered by name; anything else in range is a custom value. */
export const PAUSE_PRESETS: readonly { ms: number; label: string; hint: string }[] = [
  { ms: 250, label: "Quick", hint: "Replies as soon as the caller stops." },
  { ms: 500, label: "Relaxed", hint: "A short breath before replying." },
  { ms: 700, label: "Patient", hint: "Good for callers reading out numbers." },
];

/** "0.25 s", "0.7 s", "1.2 s": a pause as people read it. */
export function formatPause(ms: number): string {
  return `${Number((ms / 1000).toFixed(3))} s`;
}

/** The preset's name with its seconds, or the seconds alone for a custom value. */
export function pauseLabel(ms: number): string {
  const preset = PAUSE_PRESETS.find((p) => p.ms === ms);
  return preset ? `${preset.label} (${formatPause(ms)})` : formatPause(ms);
}

/** Where a value in force comes from, in the owner's words. */
export function sourceLabel(source: CallHandlingSource): string {
  if (source === "agent") return "Set for this agent";
  if (source === "organization") return "Your organisation default";
  return "Calevate default";
}

/** The "use the default" card's words: the account's value when it set one, else ours. */
export function inheritLabels(state: AgentCallHandling): { pause: string; hangUp: string } {
  const pauseMs = state.organization_turn_silence_ms;
  const hangUp = state.organization_end_call_on_finish;
  return {
    pause:
      pauseMs === null
        ? `Calevate default (${formatPause(state.bounds.platform_turn_silence_ms)})`
        : `Organisation default (${formatPause(pauseMs)})`,
    hangUp:
      hangUp === null
        ? `Calevate default (${state.bounds.platform_end_call_on_finish ? "on" : "off"})`
        : `Organisation default (${hangUp ? "on" : "off"})`,
  };
}

export function useAgentCallHandling(
  session: Session,
  agentId: string,
): UseQueryResult<AgentCallHandling> {
  return useQuery({
    queryKey: callHandlingKeys.agent(session.orgSlug, agentId),
    queryFn: () =>
      apiRequest<AgentCallHandling>(session, `/v1/agents/${agentId}/call-handling`),
    enabled: Boolean(agentId),
  });
}

export function useSetAgentCallHandling(
  session: Session,
  agentId: string,
): UseMutationResult<AgentCallHandling, Error, AgentCallHandlingIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: AgentCallHandlingIn) =>
      apiRequest<AgentCallHandling>(session, `/v1/agents/${agentId}/call-handling`, {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: (data) => {
      client.setQueryData(callHandlingKeys.agent(session.orgSlug, agentId), data);
    },
  });
}

export function useOrganizationCallHandling(
  session: Session,
): UseQueryResult<OrganizationCallHandling> {
  return useQuery({
    queryKey: callHandlingKeys.organization(session.orgSlug),
    queryFn: () => apiRequest<OrganizationCallHandling>(session, ORGANIZATION_CALL_HANDLING_PATH),
  });
}

export function useSetOrganizationCallHandling(
  session: Session,
): UseMutationResult<OrganizationCallHandling, Error, OrganizationCallHandlingIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: OrganizationCallHandlingIn) =>
      apiRequest<OrganizationCallHandling>(session, ORGANIZATION_CALL_HANDLING_PATH, {
        method: "PUT",
        body: payload,
      }),
    onSuccess: (data) => {
      client.setQueryData(callHandlingKeys.organization(session.orgSlug), data);
      return client.invalidateQueries({ queryKey: callHandlingKeys.agents(session.orgSlug) });
    },
  });
}

/** The operator's console: read through the view-as session, write through its own door. */
export function useTenantAgentCallHandling(
  slug: string,
  agentId: string,
): UseQueryResult<AgentCallHandling> {
  const session = viewAsSession(slug);
  return useQuery({
    queryKey: callHandlingKeys.agent(slug, agentId),
    queryFn: () =>
      apiRequest<AgentCallHandling>(session, `/v1/agents/${agentId}/call-handling`),
    enabled: Boolean(slug) && Boolean(agentId),
  });
}

export function useAdminSetAgentCallHandling({
  tenantId,
  agentId,
  slug,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
}): UseMutationResult<AgentCallHandling, Error, AgentCallHandlingIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: AgentCallHandlingIn) =>
      apiRequest<AgentCallHandling>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/agents/${agentId}/call-handling`,
        { method: "PATCH", body: payload },
      ),
    onSuccess: (data) => {
      client.setQueryData(callHandlingKeys.agent(slug, agentId), data);
    },
  });
}
