"use client";

/**
 * Suggested changes to one agent's lead details (D-889): choices to add or remove, or a new
 * detail to capture, from the business's script, details, quick facts and what recent callers
 * asked for that no choice fitted. Nothing changes until one is accepted.
 *
 * The client reads `/v1/agents/{id}/lead-suggestions`, the operator
 * `/v1/admin/tenants/{tenant}/agents/{id}/lead-suggestions`; both shapes are one
 * `LeadSuggestionsApi`, so the Lead details screen renders one component for either.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { agentKeys } from "./agents";
import { apiRequest, type Session } from "./client";
import { leadFieldsKeys } from "./leadFields";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadSuggestions = Schemas["LeadSuggestionsOut"];
export type LeadSuggestion = Schemas["LeadSuggestionOut"];
export type LeadSuggestionAnswered = Schemas["LeadSuggestionAnsweredOut"];

export const leadSuggestionKeys = {
  client: (org: string, agentId: string) => ["lead-suggestions", org, agentId] as const,
  admin: (tenantId: string, agentId: string) =>
    ["admin", "lead-suggestions", tenantId, agentId] as const,
};

/** While a pass is reading, the screen asks again on this interval, then stops. */
const PASS_POLL_MS = 4000;

function checking(data: LeadSuggestions | undefined): boolean {
  return data?.state === "queued" || data?.state === "running";
}

export interface LeadSuggestionsApi {
  query: UseQueryResult<LeadSuggestions>;
  accept: UseMutationResult<LeadSuggestionAnswered, Error, string>;
  dismiss: UseMutationResult<LeadSuggestionAnswered, Error, string>;
  check: UseMutationResult<LeadSuggestions, Error, void>;
}

/** The three answers, shared by both realms; each realm's hook declares its own read. */
function useAnswers(
  session: Session,
  base: string,
  key: readonly unknown[],
  afterAccept: () => Promise<unknown>,
): Omit<LeadSuggestionsApi, "query"> {
  const client = useQueryClient();
  const answer = (verb: "accept" | "dismiss") => (id: string) =>
    apiRequest<LeadSuggestionAnswered>(session, `${base}/${encodeURIComponent(id)}/${verb}`, {
      method: "POST",
    });
  const accept = useMutation({
    mutationFn: answer("accept"),
    onSuccess: (out) => {
      client.setQueryData(key, out.remaining);
      // The agent's details changed: the editor re-reads them, as after its own Save.
      return afterAccept();
    },
    // A suggestion the details overtook is gone from the server's list; show the list as
    // it now is rather than the stale one.
    onError: () => client.invalidateQueries({ queryKey: key }),
  });
  const dismiss = useMutation({
    mutationFn: answer("dismiss"),
    onSuccess: (out) => client.setQueryData(key, out.remaining),
  });
  const check = useMutation({
    mutationFn: () => apiRequest<LeadSuggestions>(session, `${base}/check`, { method: "POST" }),
    onSuccess: (out) => client.setQueryData(key, out),
  });
  return { accept, dismiss, check };
}

export function useLeadSuggestions(session: Session, agentId: string): LeadSuggestionsApi {
  const client = useQueryClient();
  const base = `/v1/agents/${encodeURIComponent(agentId)}/lead-suggestions`;
  const query = useQuery({
    queryKey: leadSuggestionKeys.client(session.orgSlug, agentId),
    queryFn: () => apiRequest<LeadSuggestions>(session, base),
    refetchInterval: (q) => (checking(q.state.data) ? PASS_POLL_MS : false),
  });
  const answers = useAnswers(session, base, leadSuggestionKeys.client(session.orgSlug, agentId), () =>
    Promise.all([
      client.invalidateQueries({ queryKey: leadFieldsKeys.client(session.orgSlug) }),
      client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
    ]),
  );
  return { query, ...answers };
}

export function useAdminLeadSuggestions(tenantId: string, agentId: string): LeadSuggestionsApi {
  const client = useQueryClient();
  const session = adminSession();
  const base = `/v1/admin/tenants/${encodeURIComponent(tenantId)}/agents/${encodeURIComponent(agentId)}/lead-suggestions`;
  const query = useQuery({
    queryKey: leadSuggestionKeys.admin(tenantId, agentId),
    queryFn: () => apiRequest<LeadSuggestions>(session, base),
    refetchInterval: (q) => (checking(q.state.data) ? PASS_POLL_MS : false),
  });
  const answers = useAnswers(session, base, leadSuggestionKeys.admin(tenantId, agentId), () =>
    client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
  );
  return { query, ...answers };
}
