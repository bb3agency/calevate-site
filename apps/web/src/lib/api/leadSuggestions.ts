"use client";

/**
 * Suggested changes to what one campaign or inbound line notes (D-889; per job since D-1029):
 * choices to add or remove, or a new detail to capture, from the business's details, the job's
 * script, quick facts and what the job's recent callers asked for that no choice fitted.
 * Nothing changes until one is accepted.
 *
 * The client reads `/v1/campaigns/{id}/lead-suggestions` or `/v1/inbound-lines/{id}/...`, the
 * operator the same under `/v1/admin/tenants/{tenant}/...`; both shapes are one
 * `LeadSuggestionsApi`, so What it notes renders one component for either.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { jobNotesKey, type JobKind } from "./campaignWorkspace";
import { apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import { leadFieldsKeys } from "./leadFields";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadSuggestions = Schemas["LeadSuggestionsOut"];
export type LeadSuggestion = Schemas["LeadSuggestionOut"];
export type LeadSuggestionAnswered = Schemas["LeadSuggestionAnsweredOut"];

export const leadSuggestionKeys = {
  client: (org: string, kind: JobKind, jobId: string) => ["lead-suggestions", org, kind, jobId] as const,
  admin: (tenantId: string, kind: JobKind, jobId: string) =>
    ["admin", "lead-suggestions", tenantId, kind, jobId] as const,
};

/** While a pass is reading, the screen asks again on this interval, then stops. */
const PASS_POLL_MS = 4000;

function checking(data: LeadSuggestions | undefined): boolean {
  return data?.state === "queued" || data?.state === "running";
}

/** The job's suggestions path below the realm's root. */
function jobPath(kind: JobKind, jobId: string): string {
  const id = encodeURIComponent(jobId);
  return kind === "campaign" ? `/campaigns/${id}/lead-suggestions` : `/inbound-lines/${id}/lead-suggestions`;
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
      // The job's list changed: its editor re-reads it, as after its own Save.
      return afterAccept();
    },
    // A suggestion the list overtook is gone from the server's list; show the list as it now
    // is rather than the stale one.
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

export function useLeadSuggestions(session: Session, kind: JobKind, jobId: string): LeadSuggestionsApi {
  const client = useQueryClient();
  const base = `/v1${jobPath(kind, jobId)}`;
  const query = useQuery<LeadSuggestions>({
    queryKey: leadSuggestionKeys.client(session.orgSlug, kind, jobId),
    queryFn: () => apiRequest<LeadSuggestions>(session, base),
    refetchInterval: untilRefused((q) => (checking(q.state.data) ? PASS_POLL_MS : false)),
  });
  const answers = useAnswers(session, base, leadSuggestionKeys.client(session.orgSlug, kind, jobId), () =>
    Promise.all([
      client.invalidateQueries({ queryKey: jobNotesKey(session.orgSlug, kind, jobId) }),
      client.invalidateQueries({ queryKey: leadFieldsKeys.client(session.orgSlug) }),
    ]),
  );
  return { query, ...answers };
}

export function useAdminLeadSuggestions(tenantId: string, kind: JobKind, jobId: string): LeadSuggestionsApi {
  const client = useQueryClient();
  const session = adminSession();
  const base = `/v1/admin/tenants/${encodeURIComponent(tenantId)}${jobPath(kind, jobId)}`;
  const query = useQuery<LeadSuggestions>({
    queryKey: leadSuggestionKeys.admin(tenantId, kind, jobId),
    queryFn: () => apiRequest<LeadSuggestions>(session, base),
    refetchInterval: untilRefused((q) => (checking(q.state.data) ? PASS_POLL_MS : false)),
  });
  const answers = useAnswers(session, base, leadSuggestionKeys.admin(tenantId, kind, jobId), () =>
    client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
  );
  return { query, ...answers };
}
