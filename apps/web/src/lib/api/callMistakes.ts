"use client";

/**
 * Mistakes on real calls (D-949, `apps/api/agents/call_mistake_routes.py`): what an agent
 * got wrong on live calls — a line said again, a question re-asked, the wrong language.
 * Each kind is a PLATFORM rule Calevate fixes, never something the client is asked to fix.
 *
 *   GET  /v1/agents/{agent_id}/call-mistakes   one agent's, last `window_days` (client)
 *   GET  /v1/ops/call-mistakes                 the fleet's, by kind (admin)
 *   POST /v1/ops/call-mistakes/{kind}/fixed    "the rule behind this kind is fixed, from now"
 *
 * The state ("fixing" / "fixed" / "back") and the order come from the server; this module
 * only words them.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AgentMistake = Schemas["AgentMistakeOut"];
export type AgentMistakes = Schemas["AgentMistakesOut"];
export type CallMistake = Schemas["CallMistakeOut"];
export type PlatformMistake = Schemas["PlatformMistakeOut"];
export type PlatformMistakes = Schemas["PlatformMistakesOut"];
export type MistakeFix = Schemas["MistakeFixOut"];
export type MistakeState = AgentMistake["state"];

export const PLATFORM_MISTAKES_PATH = "/v1/ops/call-mistakes";

/** The server's limit on a fix note (`MistakeFixIn.note`). */
export const FIX_NOTE_MAX = 300;

export function agentMistakesPath(agentId: string): string {
  return `/v1/agents/${encodeURIComponent(agentId)}/call-mistakes`;
}

export function mistakeFixedPath(kind: string): string {
  return `${PLATFORM_MISTAKES_PATH}/${encodeURIComponent(kind)}/fixed`;
}

export function agentMistakesKey(slug: string, agentId: string) {
  return ["call-mistakes", slug, agentId] as const;
}

/** Not org-scoped: the board counts every client's calls. */
export const platformMistakesKey = ["admin", "ops", "call-mistakes"] as const;

/** No poll: the counts move when a call is checked after it ends, which the live stream announces. */
export function useAgentMistakes(session: Session, agentId: string): UseQueryResult<AgentMistakes> {
  return useQuery({
    queryKey: agentMistakesKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<AgentMistakes>(session, agentMistakesPath(agentId)),
  });
}

export function usePlatformMistakes(enabled = true): UseQueryResult<PlatformMistakes> {
  return useQuery({
    queryKey: platformMistakesKey,
    queryFn: () => apiRequest<PlatformMistakes>(adminSession(), PLATFORM_MISTAKES_PATH),
    enabled,
  });
}

export function useMarkMistakeFixed() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, note }: { kind: string; note: string }) =>
      apiRequest<MistakeFix>(adminSession(), mistakeFixedPath(kind), {
        method: "POST",
        body: { note },
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: platformMistakesKey }),
  });
}

/**
 * The client's words for each state: we fix these, the client never does. Each says only
 * what is true (D-970): "told" because the account's first call showing a kind alerts our
 * team (`call_mistake_new`) and a kind back after a fix alerts it again
 * (`call_mistake_back`); "fixed" only once an operator recorded the change.
 */
export function clientStateLine(state: MistakeState, fixedOn: string | null): string {
  if (state === "back") {
    return fixedOn ? `Seen again after our fix on ${fixedOn} · our team has been told` : "Seen again after our fix · our team has been told";
  }
  if (state === "fixed") return fixedOn ? `Fixed on ${fixedOn} · not seen since` : "Fixed · not seen since";
  return "Not fixed yet · our team has been told";
}

/** What the call page says beside a mistake on that call, whatever has happened since. */
export const CALL_MISTAKE_TOLD = "Our team has been told";

export function callsLine(calls: number, windowDays: number): string {
  return `${calls} ${calls === 1 ? "call" : "calls"} in ${windowDays} days`;
}
