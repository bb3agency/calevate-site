"use client";

/**
 * Mistakes on real calls (D-949, `apps/api/agents/call_mistake_routes.py`): what an agent
 * got wrong on live calls — a line said again, a question re-asked, the wrong language.
 * Each kind is a PLATFORM rule Calevate fixes, never something the client is asked to fix.
 *
 *   GET  /v1/agents/{agent_id}/call-mistakes              one agent's, last `window_days` (client)
 *   POST /v1/agents/{agent_id}/call-mistakes/{kind}/undo  put back the script from before our fix (D-985)
 *   GET  /v1/ops/call-mistakes                            the fleet's, by kind (admin)
 *   POST /v1/ops/call-mistakes/{kind}/fixed               "the rule behind this kind is fixed, from now"
 *   GET  /v1/ops/call-mistakes/fixes                      every agent's script fixes (admin, D-985)
 *
 * The state, whether Undo is offered and the order come from the server; this module only
 * words them.
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
export type MistakeUndo = Schemas["MistakeUndoOut"];
export type FleetFix = Schemas["FleetFixOut"];
export type FleetFixes = Schemas["FleetFixesOut"];
export type MistakeState = AgentMistake["state"];
export type PlatformMistakeState = PlatformMistake["state"];

export const PLATFORM_MISTAKES_PATH = "/v1/ops/call-mistakes";
export const FLEET_FIXES_PATH = "/v1/ops/call-mistakes/fixes";

/** The owner's Undo of our fix of one mistake in their agent's script (D-985). */
export function mistakeUndoPath(agentId: string, kind: string): string {
  return `${agentMistakesPath(agentId)}/${encodeURIComponent(kind)}/undo`;
}

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

export const fleetFixesKey = ["admin", "ops", "call-mistakes", "fixes"] as const;

export function useFleetFixes(enabled = true): UseQueryResult<FleetFixes> {
  return useQuery({
    queryKey: fleetFixesKey,
    queryFn: () => apiRequest<FleetFixes>(adminSession(), FLEET_FIXES_PATH),
    enabled,
  });
}

/** Undo puts the script from before our fix back live; the list is read again after. */
export function useUndoMistakeFix(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (kind: string) =>
      apiRequest<MistakeUndo>(session, mistakeUndoPath(agentId, kind), { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: agentMistakesKey(session.orgSlug, agentId) }),
  });
}

/**
 * The client's words for each state: we fix these, the client never does. Each says only
 * what is true (D-970). The platform's three: "told" because the account's first call
 * showing a kind alerts our team (`call_mistake_new`) and a kind back after a fix alerts it
 * again (`call_mistake_back`); "fixed" only once an operator recorded the change. The
 * `script_*` ones are the agent's own script fix (D-985), which the server says is live,
 * held, put back or undone.
 */
export function clientStateLine(
  state: MistakeState,
  fixedOn: string | null,
  cleanCalls = 0,
): string {
  switch (state) {
    case "back":
      return fixedOn ? `Seen again after our fix on ${fixedOn} · our team has been told` : "Seen again after our fix · our team has been told";
    case "fixed":
      return fixedOn ? `Fixed on ${fixedOn} · not seen since` : "Fixed · not seen since";
    case "script_fixing":
      return "Fixing it in your script";
    case "script_live":
      return fixedOn ? `Fixed in your script on ${fixedOn} · watching the next calls` : "Fixed in your script · watching the next calls";
    case "script_fixed":
      return `Fixed in your script · not seen in ${callsWord(cleanCalls)}`;
    case "script_rolled_back":
      return "Came back · we put your script back";
    case "script_undone":
      return "You put your old script back";
    case "with_team":
      return "Our team is fixing this";
    default:
      return "Not fixed yet · our team has been told";
  }
}

function callsWord(calls: number): string {
  return `${calls} ${calls === 1 ? "call" : "calls"}`;
}

/** The operator's words for a script fix's state and why it stopped (`FleetFixOut`). */
export const FIX_STATE_WORDS: Record<FleetFix["state"], string> = {
  fixing: "Being fixed",
  live: "Live, watching calls",
  fixed: "Held",
  rolled_back: "Put back",
  needs_person: "Handed to us",
};

export const FIX_ENDED_WORDS: Record<string, string> = {
  came_back: "the mistake came back",
  worse: "other mistakes rose",
  owner: "the owner pressed Undo",
  no_script_cause: "no line of the script causes it",
  waited_too_long: "waited too long for a chance",
  attempts_spent: "the fixes did not pass their check",
  script_changed: "the script changed after the fix",
  agent_gone: "the agent is gone",
};

/** What the call page says beside a mistake on that call, whatever has happened since. */
export const CALL_MISTAKE_TOLD = "Our team has been told";

export function callsLine(calls: number, windowDays: number): string {
  return `${calls} ${calls === 1 ? "call" : "calls"} in ${windowDays} days`;
}
