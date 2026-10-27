"use client";

/**
 * Tell my team (D-904): the business's own team addresses and, per agent, when the team hears
 * about a caller.
 *
 *   GET    /v1/team-alerts/contacts                 `org:read`
 *   POST   /v1/team-alerts/contacts                 `org:manage` (a code is sent to it)
 *   POST   /v1/team-alerts/contacts/{id}/code       `org:manage`
 *   POST   /v1/team-alerts/contacts/{id}/verify     `org:manage`
 *   POST   /v1/team-alerts/contacts/{id}/default    `org:manage`
 *   DELETE /v1/team-alerts/contacts/{id}            `org:manage`
 *   GET    /v1/agents/{agent_id}/team-alert         `agents:read`
 *   PUT    /v1/agents/{agent_id}/team-alert         `org:manage`
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
export type TeamAlertRule = Schemas["TeamAlertRuleOut"];
export type TeamAlertRuleIn = Schemas["TeamAlertRuleIn"];

const CONTACTS_PATH = "/v1/team-alerts/contacts";

export const teamAlertKeys = {
  all: (org: string) => ["team-alerts", org] as const,
  contacts: (org: string) => ["team-alerts", org, "contacts"] as const,
  rule: (org: string, agentId: string) => ["team-alerts", org, "rule", agentId] as const,
};

export function useTeamContacts(session: Session): UseQueryResult<TeamContacts> {
  return useQuery({
    queryKey: teamAlertKeys.contacts(session.orgSlug),
    queryFn: () => apiRequest<TeamContacts>(session, CONTACTS_PATH),
  });
}

export function useTeamAlertRule(session: Session, agentId: string): UseQueryResult<TeamAlertRule> {
  return useQuery({
    queryKey: teamAlertKeys.rule(session.orgSlug, agentId),
    queryFn: () => apiRequest<TeamAlertRule>(session, `/v1/agents/${agentId}/team-alert`),
  });
}

/** Every contact change can move which address an agent sends to, so the rules refetch too. */
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

export function useDefaultTeamContact(session: Session) {
  return useContactMutation(session, (id: string) =>
    apiRequest<TeamContacts>(session, `${CONTACTS_PATH}/${id}/default`, { method: "POST" }),
  );
}

export function useRemoveTeamContact(session: Session) {
  return useContactMutation(session, async (id: string) => {
    await apiRequest<void>(session, `${CONTACTS_PATH}/${id}`, { method: "DELETE" });
    return undefined;
  });
}

export function useSaveTeamAlertRule(
  session: Session,
  agentId: string,
): UseMutationResult<TeamAlertRule, Error, TeamAlertRuleIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: TeamAlertRuleIn) =>
      apiRequest<TeamAlertRule>(session, `/v1/agents/${agentId}/team-alert`, {
        method: "PUT",
        body,
      }),
    onSuccess: (rule) => client.setQueryData(teamAlertKeys.rule(session.orgSlug, agentId), rule),
  });
}
