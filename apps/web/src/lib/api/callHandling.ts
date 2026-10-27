"use client";

/**
 * The pause before an agent replies and hanging up when it has finished (D-751).
 *
 *   GET   /v1/agents/{agent_id}/call-handling                    `agents:read`
 *   PATCH /v1/agents/{agent_id}/call-handling                    `org:manage` (the owner)
 *   GET   /v1/organization/call-handling                         `org:read`
 *   POST  /v1/organization/call-handling/all-agents              `org:manage`
 *   PATCH /v1/admin/tenants/{tid}/agents/{aid}/call-handling     the operator's door
 *   GET   /v1/admin/organizations/{org_id}/call-handling         `admin:tenants`
 *   PUT   /v1/admin/organizations/{org_id}/call-handling         `admin:tenants`
 *
 * Each value resolves agent, then the account default, then Calevate's, on the server; the
 * screens render `*_effective` and `*_source` as they arrive and never resolve it themselves.
 * The pause is whole milliseconds on the wire; seconds are only for people.
 *
 * A client changes these on an agent's Settings only, for that agent or for all of them
 * (`useSaveCallHandling`); the account defaults' own PUT is the operator's console's.
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
export type AgentOwnCallHandling = Schemas["AgentOwnCallHandlingOut"];
export type CallHandlingSource = AgentCallHandling["turn_silence_source"];
export type AllAgentsCallHandlingIn = Schemas["AllAgentsCallHandlingIn"];
export type AllAgentsCallHandling = Schemas["AllAgentsCallHandlingOut"];

export const ORGANIZATION_CALL_HANDLING_PATH = "/v1/organization/call-handling";
export const ALL_AGENTS_CALL_HANDLING_PATH = "/v1/organization/call-handling/all-agents";

/** Whom a change on an agent's Settings is for. */
export type CallHandlingScope = "agent" | "all";

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
  if (source === "agent") return "Only this agent";
  if (source === "organization") return "Same for all your agents";
  return "Calevate default";
}

/** The default "use the default" follows and what it resolves to, "Calevate default: On":
 * the setting the account's agents share when it set one, else ours. */
export function inheritLabels(state: AgentCallHandling): { pause: string; hangUp: string } {
  const pauseMs = state.organization_turn_silence_ms;
  const hangUp = state.organization_end_call_on_finish;
  return {
    pause:
      pauseMs === null
        ? `Calevate default: ${pauseLabel(state.bounds.platform_turn_silence_ms)}`
        : `${SHARED}: ${pauseLabel(pauseMs)}`,
    hangUp:
      hangUp === null
        ? `Calevate default: ${state.bounds.platform_end_call_on_finish ? "On" : "Off"}`
        : `${SHARED}: ${hangUp ? "On" : "Off"}`,
  };
}

/** Calevate's own pause and hang-up, what "use the default" means for all agents at once. */
export function platformLabels(bounds: CallHandlingBounds): { pause: string; hangUp: string } {
  return {
    pause: `Calevate default: ${pauseLabel(bounds.platform_turn_silence_ms)}`,
    hangUp: `Calevate default: ${bounds.platform_end_call_on_finish ? "On" : "Off"}`,
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
  /** Per setting, the level "use the default" follows: the one the agents share or Calevate's. */
  from: Record<keyof VoiceSettings, typeof SHARED | typeof OURS>;
}

/** Read after "Use the": "Use the setting your agents share: Quick (0.25 s)". */
const SHARED = "setting your agents share" as const;
const ORG = SHARED;
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

/** One save from an agent's Settings: the agent's own value, or the value for every agent. */
export interface CallHandlingSave {
  scope: CallHandlingScope;
  changes: AgentCallHandlingIn;
}

/**
 * The save behind every call-handling row on an agent's Settings. "agent" writes the agent's
 * own value (`PATCH /v1/agents/{id}/call-handling`); "all" makes it the account default and
 * drops every agent's own (`POST /v1/organization/call-handling/all-agents`), so every
 * agent's read is dropped too.
 */
export function useSaveCallHandling(
  session: Session,
  agentId: string,
): UseMutationResult<CallHandlingSaved, Error, CallHandlingSave> {
  const client = useQueryClient();
  const org = session.orgSlug;
  return useMutation({
    mutationFn: async ({ scope, changes }: CallHandlingSave): Promise<CallHandlingSaved> =>
      scope === "all"
        ? {
            scope,
            all: await apiRequest<AllAgentsCallHandling>(session, ALL_AGENTS_CALL_HANDLING_PATH, {
              method: "POST",
              body: allAgentsChanges(changes),
            }),
          }
        : {
            scope,
            agent: await apiRequest<AgentCallHandling>(session, `/v1/agents/${agentId}/call-handling`, {
              method: "PATCH",
              body: changes,
            }),
          },
    onSuccess: (saved) => {
      if (saved.scope === "all") {
        client.setQueryData(callHandlingKeys.organization(org), saved.all.organization);
        return client.invalidateQueries({ queryKey: callHandlingKeys.agents(org) });
      }
      client.setQueryData(callHandlingKeys.agent(org, agentId), saved.agent);
      // The account read lists the agents with values of their own.
      return client.invalidateQueries({ queryKey: callHandlingKeys.organization(org) });
    },
  });
}

/** What a save answered, by whom it was for. */
export type CallHandlingSaved =
  | { scope: "agent"; agent: AgentCallHandling }
  | { scope: "all"; all: AllAgentsCallHandling };

/** The fields "all agents" takes: every one but the agent's own `opening_waits_for_caller`. */
function allAgentsChanges(changes: AgentCallHandlingIn): AllAgentsCallHandlingIn {
  const shared: AgentCallHandlingIn = { ...changes };
  delete shared.opening_waits_for_caller;
  return shared;
}

/** The account's defaults and the agents with their own; read on an agent's Settings to say
 * how many agents "All my agents" changes. */
export function useOrganizationCallHandling(
  session: Session,
  { enabled = true }: { enabled?: boolean } = {},
): UseQueryResult<OrganizationCallHandling> {
  return useQuery({
    queryKey: callHandlingKeys.organization(session.orgSlug),
    queryFn: () => apiRequest<OrganizationCallHandling>(session, ORGANIZATION_CALL_HANDLING_PATH),
    enabled,
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
      // The account read lists the agents with values of their own.
      return Promise.all([
        client.invalidateQueries({ queryKey: adminOrganizationKey(tenantId) }),
        client.invalidateQueries({ queryKey: callHandlingKeys.organization(slug) }),
      ]);
    },
  });
}

const adminOrganizationPath = (tenantId: string) =>
  `/v1/admin/organizations/${tenantId}/call-handling`;
const adminOrganizationKey = (tenantId: string) =>
  ["call-handling", "admin", tenantId, "organization"] as const;

/** The operator's read of one client's account defaults (`admin:tenants`). */
export function useAdminOrganizationCallHandling(
  tenantId: string,
): UseQueryResult<OrganizationCallHandling> {
  return useQuery({
    queryKey: adminOrganizationKey(tenantId),
    queryFn: () =>
      apiRequest<OrganizationCallHandling>(adminSession(), adminOrganizationPath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

/**
 * The operator's write of one client's account defaults. Every agent read of that client is
 * dropped too, since an agent that inherits a moved value now resolves differently; `slug` is
 * the client's, which keys those reads.
 */
export function useAdminSetOrganizationCallHandling(
  tenantId: string,
  slug: string | undefined,
): UseMutationResult<OrganizationCallHandling, Error, OrganizationCallHandlingIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: OrganizationCallHandlingIn) =>
      apiRequest<OrganizationCallHandling>(adminSession(), adminOrganizationPath(tenantId), {
        method: "PUT",
        body: payload,
      }),
    onSuccess: (data) => {
      client.setQueryData(adminOrganizationKey(tenantId), data);
      if (!slug) return;
      client.setQueryData(callHandlingKeys.organization(slug), data);
      return client.invalidateQueries({ queryKey: callHandlingKeys.agents(slug) });
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

/** One row of the account defaults, as `CallHandlingDefaultsRows` lays them out. */
export type DefaultsRow = "pause" | "hang-up" | "silence" | "filler" | "sound";

/** An agent that does not follow one account default, and what it uses instead. */
export interface AgentOverride {
  agentId: string;
  name: string;
  /** The agent's value in force for that row, in the row's own words ("Office at 15%"). */
  value: string;
}

/**
 * Per row of the account defaults, the agents that set their own value for it and what they
 * use. A part the agent left unset (say, the volume but not the sound) follows the account,
 * so it is filled from the account's value in force, as the server resolves it.
 */
export function agentOverrides(data: OrganizationCallHandling): Record<DefaultsRow, AgentOverride[]> {
  const rows: Record<DefaultsRow, AgentOverride[]> = {
    pause: [],
    "hang-up": [],
    silence: [],
    filler: [],
    sound: [],
  };
  for (const agent of data.agents_with_own) {
    const add = (row: DefaultsRow, value: string) =>
      rows[row].push({ agentId: agent.agent_id, name: agent.name, value });
    if (agent.turn_silence_ms !== null) add("pause", pauseLabel(agent.turn_silence_ms));
    if (agent.end_call_on_finish !== null) add("hang-up", agent.end_call_on_finish ? "On" : "Off");
    if (
      agent.nudge_after_seconds !== null ||
      agent.nudge_count !== null ||
      agent.nudge_phrase !== null ||
      agent.end_after_silence_seconds !== null
    ) {
      const summary = silenceSummary(
        agent.nudge_after_seconds ?? data.nudge_after_seconds_effective,
        agent.nudge_count ?? data.nudge_count_effective,
        agent.end_after_silence_seconds ?? data.end_after_silence_seconds_effective,
      );
      // The summary names no question, so an agent that differs only in its words says so.
      add("silence", agent.nudge_phrase ? `${summary} · its own question` : summary);
    }
    if (agent.filler_lines !== null) add("filler", fillerSummary(agent.filler_lines));
    if (agent.ambience !== null || agent.ambience_volume_pct !== null) {
      add(
        "sound",
        ambienceSummary(
          agent.ambience ?? data.ambience_effective,
          agent.ambience_volume_pct ?? data.ambience_volume_pct_effective,
        ),
      );
    }
  }
  return rows;
}

const DEFAULTS_ROW_NAMES: Record<DefaultsRow, string> = {
  pause: "pause before replying",
  "hang-up": "hang up when finished",
  silence: "if the caller goes quiet",
  filler: "lines while looking something up",
  sound: "background sound",
};

/** For the assistant: "Anjali (background sound: Office at 15%)", or that every agent follows. */
export function agentOverridesSummary(data: OrganizationCallHandling): string {
  if (data.agents_with_own_total === 0) return "none; every agent follows these defaults";
  const rows = agentOverrides(data);
  // By id: two agents may share a name.
  const byAgent = new Map<string, { name: string; parts: string[] }>();
  for (const [row, agents] of Object.entries(rows) as [DefaultsRow, AgentOverride[]][]) {
    for (const agent of agents) {
      const entry = byAgent.get(agent.agentId) ?? { name: agent.name, parts: [] };
      entry.parts.push(`${DEFAULTS_ROW_NAMES[row]}: ${agent.value}`);
      byAgent.set(agent.agentId, entry);
    }
  }
  const listed = [...byAgent.values()]
    .map(({ name, parts }) => `${name} (${parts.join("; ")})`)
    .join(", ");
  const unlisted = data.agents_with_own_total - data.agents_with_own.length;
  return unlisted > 0 ? `${listed}, and ${unlisted} more not listed` : listed;
}

/** One hint for a row whose values may come from different levels. */
export function rowSource(sources: readonly CallHandlingSource[]): string {
  const first = sources[0];
  if (first !== undefined && sources.every((s) => s === first)) return sourceLabel(first);
  return sources.includes("agent") ? "Partly only this agent" : "Partly the same for all your agents";
}

/** Per row, how many agents other than this one keep a value of their own, which "All my
 * agents" replaces. From the account read's list, which holds every such agent up to the
 * server's cap. */
export function othersWithOwn(
  data: OrganizationCallHandling,
  agentId: string,
): Record<DefaultsRow, number> {
  const rows = agentOverrides(data);
  const count = (row: DefaultsRow) => rows[row].filter((a) => a.agentId !== agentId).length;
  return {
    pause: count("pause"),
    "hang-up": count("hang-up"),
    silence: count("silence"),
    filler: count("filler"),
    sound: count("sound"),
  };
}
