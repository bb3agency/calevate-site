"use client";

/**
 * Who hears about hot leads (D-904, D-967): the business's own team addresses beside the owner;
 * per agent, whether it may message the team during a call; and per campaign and Inbound line,
 * which of its calls the list hears about after they end (D-1040).
 *
 *   GET    /v1/team-alerts/contacts                 `org:read`
 *   POST   /v1/team-alerts/contacts                 `org:manage` (a code is sent to it)
 *   POST   /v1/team-alerts/contacts/{id}/code       `org:manage`
 *   POST   /v1/team-alerts/contacts/{id}/verify     `org:manage`
 *   DELETE /v1/team-alerts/contacts/{id}            `org:manage`
 *   GET    /v1/agents/{agent_id}/team-alert         `agents:read`
 *   PUT    /v1/agents/{agent_id}/team-alert         `org:manage`
 *   GET    /v1/campaigns/{id}/team-alert            `agents:read`
 *   PUT    /v1/campaigns/{id}/team-alert            `org:manage`
 *   GET    /v1/inbound-lines/{id}/team-alert        `agents:read`
 *   PUT    /v1/inbound-lines/{id}/team-alert        `org:manage`
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TeamContacts = Schemas["TeamContactsOut"];
export type TeamContact = Schemas["TeamContactOut"];
export type TeamContactIn = Schemas["TeamContactIn"];
export type AgentTeamAlert = Schemas["AgentTeamAlertOut"];
export type AgentTeamAlertIn = Schemas["AgentTeamAlertIn"];
export type JobTeamAlert = Schemas["JobTeamAlertOut"];
export type JobTeamAlertIn = Schemas["JobTeamAlertIn"];
export type AlertJobKind = JobTeamAlert["kind"];

const CONTACTS_PATH = "/v1/team-alerts/contacts";

export const teamAlertKeys = {
  all: (org: string) => ["team-alerts", org] as const,
  contacts: (org: string) => ["team-alerts", org, "contacts"] as const,
  rule: (org: string, agentId: string) => ["team-alerts", org, "rule", agentId] as const,
  job: (org: string, kind: AlertJobKind, jobId: string) => ["team-alerts", org, "job", kind, jobId] as const,
};

function jobPath(kind: AlertJobKind, jobId: string): string {
  return kind === "campaign" ? `/v1/campaigns/${jobId}/team-alert` : `/v1/inbound-lines/${jobId}/team-alert`;
}

export function useTeamContacts(session: Session): UseQueryResult<TeamContacts> {
  return useQuery({
    queryKey: teamAlertKeys.contacts(session.orgSlug),
    queryFn: () => apiRequest<TeamContacts>(session, CONTACTS_PATH),
  });
}

export function useAgentTeamAlert(session: Session, agentId: string): UseQueryResult<AgentTeamAlert> {
  return useQuery({
    queryKey: teamAlertKeys.rule(session.orgSlug, agentId),
    queryFn: () => apiRequest<AgentTeamAlert>(session, `/v1/agents/${agentId}/team-alert`),
  });
}

export function useJobTeamAlert(session: Session, kind: AlertJobKind, jobId: string): UseQueryResult<JobTeamAlert> {
  return useQuery({
    queryKey: teamAlertKeys.job(session.orgSlug, kind, jobId),
    queryFn: () => apiRequest<JobTeamAlert>(session, jobPath(kind, jobId)),
  });
}

/** A contact change moves how many hear and whether an agent may tell the team during a call, so the rules refetch too. */
function useContactMutation<V>(
  session: Session,
  request: (vars: V) => Promise<TeamContacts | undefined>,
): UseMutationResult<TeamContacts | undefined, Error, V> {
  const client = useQueryClient();
  const org = session.orgSlug;
  return useMutation({
    mutationFn: request,
    onSuccess: (contacts) => {
      if (contacts) client.setQueryData(teamAlertKeys.contacts(org), contacts);
      return client.invalidateQueries({ queryKey: teamAlertKeys.all(org) });
    },
  });
}

export function useAddTeamContact(session: Session) {
  return useContactMutation(session, (body: TeamContactIn) =>
    apiRequest<TeamContacts>(session, CONTACTS_PATH, { method: "POST", body }),
  );
}

export function useVerifyTeamContact(session: Session) {
  return useContactMutation(session, ({ id, code }: { id: string; code: string }) =>
    apiRequest<TeamContacts>(session, `${CONTACTS_PATH}/${id}/verify`, {
      method: "POST",
      body: { code },
    }),
  );
}

export function useResendTeamCode(session: Session) {
  return useContactMutation(session, (id: string) =>
    apiRequest<TeamContacts>(session, `${CONTACTS_PATH}/${id}/code`, { method: "POST" }),
  );
}

export function useRemoveTeamContact(session: Session) {
  return useContactMutation(session, async (id: string) => {
    await apiRequest<void>(session, `${CONTACTS_PATH}/${id}`, { method: "DELETE" });
    return undefined;
  });
}

export function useSaveAgentTeamAlert(
  session: Session,
  agentId: string,
): UseMutationResult<AgentTeamAlert, Error, AgentTeamAlertIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AgentTeamAlertIn) =>
      apiRequest<AgentTeamAlert>(session, `/v1/agents/${agentId}/team-alert`, {
        method: "PUT",
        body,
      }),
    onSuccess: (rule) => client.setQueryData(teamAlertKeys.rule(session.orgSlug, agentId), rule),
  });
}

export function useSaveJobTeamAlert(
  session: Session,
  kind: AlertJobKind,
  jobId: string,
): UseMutationResult<JobTeamAlert, Error, JobTeamAlertIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: JobTeamAlertIn) =>
      apiRequest<JobTeamAlert>(session, jobPath(kind, jobId), { method: "PUT", body }),
    onSuccess: (rule) => client.setQueryData(teamAlertKeys.job(session.orgSlug, kind, jobId), rule),
  });
}
