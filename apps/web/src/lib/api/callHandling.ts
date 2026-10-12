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
  { ms: 700, label: "Unhurried", hint: "Good for callers reading out numbers." },
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

export type Ambience = AgentCallHandling["ambience_effective"];
export type CallHandlingBounds = AgentCallHandling["bounds"];

/** "8 s", "1 min 30 s": a wait as people read it. */
export function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** "once", "twice", "3 times". */
export function timesLabel(count: number): string {
  if (count === 1) return "once";
  if (count === 2) return "twice";
  return `${count} times`;
}

/** "Asks after 8 s, once · hangs up after 20 s of silence", or "Never asks · …". */
export function silenceSummary(afterSeconds: number, count: number, hangUpSeconds: number): string {
  const ask = afterSeconds === 0 ? "Never asks" : `Asks after ${formatSeconds(afterSeconds)}, ${timesLabel(count)}`;
  return `${ask} · hangs up after ${formatSeconds(hangUpSeconds)} of silence`;
}

export const AMBIENCE_LABELS: Record<Ambience, string> = {
  off: "Off",
  office: "Office",
  "office-quiet": "Quiet office",
};

/** "Off", or "Office at 15%". */
export function ambienceSummary(ambience: Ambience, volumePct: number): string {
  return ambience === "off" ? AMBIENCE_LABELS.off : `${AMBIENCE_LABELS[ambience]} at ${volumePct}%`;
}

/** "The standard lines", or "3 of your own lines". */
export function fillerSummary(lines: readonly string[]): string {
  if (lines.length === 0) return "The standard lines";
  return lines.length === 1 ? "1 line of your own" : `${lines.length} lines of your own`;
}

/** The voice settings one level holds; `null` follows the level above. */
export interface VoiceSettings {
  nudge_after_seconds: number | null;
  nudge_count: number | null;
  nudge_phrase: string | null;
  end_after_silence_seconds: number | null;
  filler_lines: string[] | null;
  ambience: Ambience | null;
  ambience_volume_pct: number | null;
}

export interface InheritedVoice {
  nudge_after_seconds: number;
  nudge_count: number;
  nudge_phrase: string;
  end_after_silence_seconds: number;
  filler_lines: string[];
  ambience: Ambience;
  ambience_volume_pct: number;
  /** Per setting, the level "use the default" follows: the organisation's or Calevate's. */
  from: Record<keyof VoiceSettings, "Organisation default" | "Calevate default">;
}

const ORG = "Organisation default" as const;
const OURS = "Calevate default" as const;

/** The voice settings an agent with no value of its own follows: the account's, where it set
 * one, else Calevate's. Read from the server's fields, never resolved here beyond that. */
export function inheritedVoice(state: AgentCallHandling): InheritedVoice {
  const b = state.bounds;
  const pick = <T,>(org: T | null, platform: T): T => (org === null ? platform : org);
  const from = (org: unknown) => (org === null ? OURS : ORG);
  return {
    nudge_after_seconds: pick(state.organization_nudge_after_seconds, b.platform_nudge_after_seconds),
    nudge_count: pick(state.organization_nudge_count, b.platform_nudge_count),
    nudge_phrase: pick(state.organization_nudge_phrase, ""),
    end_after_silence_seconds: pick(
      state.organization_end_after_silence_seconds,
      b.platform_end_after_silence_seconds,
    ),
    filler_lines: pick(state.organization_filler_lines, []),
    ambience: pick(state.organization_ambience, b.platform_ambience),
    ambience_volume_pct: pick(state.organization_ambience_volume_pct, b.platform_ambience_volume_pct),
    from: {
      nudge_after_seconds: from(state.organization_nudge_after_seconds),
      nudge_count: from(state.organization_nudge_count),
      nudge_phrase: from(state.organization_nudge_phrase),
      end_after_silence_seconds: from(state.organization_end_after_silence_seconds),
      filler_lines: from(state.organization_filler_lines),
      ambience: from(state.organization_ambience),
      ambience_volume_pct: from(state.organization_ambience_volume_pct),
    },
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

/** What "use the default" means at the organisation level: Calevate's own values. */
export function platformVoice(bounds: CallHandlingBounds): InheritedVoice {
  return {
    nudge_after_seconds: bounds.platform_nudge_after_seconds,
    nudge_count: bounds.platform_nudge_count,
    nudge_phrase: "",
    end_after_silence_seconds: bounds.platform_end_after_silence_seconds,
    filler_lines: [],
    ambience: bounds.platform_ambience,
    ambience_volume_pct: bounds.platform_ambience_volume_pct,
    from: {
      nudge_after_seconds: OURS,
      nudge_count: OURS,
      nudge_phrase: OURS,
      end_after_silence_seconds: OURS,
      filler_lines: OURS,
      ambience: OURS,
      ambience_volume_pct: OURS,
    },
  };
}

/** One hint for a row whose values may come from different levels. */
export function rowSource(sources: readonly CallHandlingSource[]): string {
  const first = sources[0];
  if (first !== undefined && sources.every((s) => s === first)) return sourceLabel(first);
  return sources.includes("agent") ? "Partly set for this agent" : "Partly your organisation default";
}
