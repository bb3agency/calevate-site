"use client";

/**
 * The lead details a business captures (founder decision 15): the fixed core every lead
 * carries, each agent's own business fields, and the one AI draft a custom business gets.
 *
 * Reads, the draft review and the replace action are `/v1/lead-fields` (client; the draft
 * itself is asked of Pip, D-821) and
 * `/v1/admin/tenants/{id}/lead-fields` (operator). Saving one agent's fields is the same
 * per-agent PUT the agent screen uses, so a list has one write path whichever screen
 * edits it.
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
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadFields = Schemas["LeadFieldsOut"];
export type LeadFieldsAgent = Schemas["LeadFieldsAgentOut"];
export type LeadFieldsDraft = Schemas["LeadFieldsDraftOut"];
export type LeadField = Schemas["ExtractionField"];
/** One agent's whole list, with the version the editor loaded (`expected_version`): a save
 *  over a newer version is refused with `extraction_schema_changed_elsewhere`. */
export type SaveAgentLeadFieldsIn = {
  agentId: string;
  fields: LeadField[];
  expected_version?: number;
};
export type ReplaceOut = Schemas["ReplaceOut"];
export type DraftRequestOut = Schemas["DraftRequestOut"];
export type DraftReviewOut = Schemas["LeadFieldsReviewOut"];
export type CapturedField = Schemas["CapturedFieldOut"];
export type CapturedFields = Schemas["CapturedFieldsOut"];
export type ExtractionSchemaOut = Schemas["ExtractionSchemaOut"];
export type BusinessType = NonNullable<Schemas["AdminReplaceIn"]["business_type"]>;

export const leadFieldsKeys = {
  client: (org: string) => ["lead-fields", org] as const,
  admin: (tenantId: string) => ["admin", "lead-fields", tenantId] as const,
  captured: (org: string, leadId: string) => ["lead-captured", org, leadId] as const,
};

/** While a draft is being written the screen asks again on this interval, then stops. */
const DRAFT_POLL_MS = 3000;

function drafting(data: LeadFields | undefined): boolean {
  return data?.draft?.status === "queued" || data?.draft?.status === "running";
}

const adminPath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/lead-fields`;

// ------------------------------------------------------------------------------- client

export function useLeadFields(session: Session): UseQueryResult<LeadFields> {
  return useQuery({
    queryKey: leadFieldsKeys.client(session.orgSlug),
    queryFn: () => apiRequest<LeadFields>(session, "/v1/lead-fields"),
    refetchInterval: (query) => (drafting(query.state.data) ? DRAFT_POLL_MS : false),
  });
}

/**
 * Keep some or none of the drafted details (D-821). The draft itself is asked of Pip; the
 * kept fields go onto every agent without its own, so the agents' query is refreshed too.
 */
export function useReviewLeadFieldsDraft(
  session: Session,
): UseMutationResult<DraftReviewOut, Error, string[]> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (keep: string[]) =>
      apiRequest<DraftReviewOut>(session, "/v1/lead-fields/draft/review", {
        method: "POST",
        body: { keep },
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: leadFieldsKeys.client(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        // Every inheriting agent's `extraction_fields` moved, and the write names no agent.
        client.invalidateQueries({ queryKey: agentKeys.allDetails(session.orgSlug) }),
      ]),
  });
}

export function useReplaceLeadFields(
  session: Session,
): UseMutationResult<ReplaceOut, Error, { agent_ids?: string[] | null }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<ReplaceOut>(session, "/v1/lead-fields/replace", { method: "POST", body }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: leadFieldsKeys.client(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.allDetails(session.orgSlug) }),
      ]),
  });
}

export function useSaveAgentLeadFields(
  session: Session,
): UseMutationResult<ExtractionSchemaOut, Error, SaveAgentLeadFieldsIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, fields, expected_version }) =>
      apiRequest<ExtractionSchemaOut>(
        session,
        `/v1/agents/${encodeURIComponent(agentId)}/extraction-schema`,
        { method: "PUT", body: { fields, expected_version } },
      ),
    onSuccess: (_out, { agentId }) =>
      Promise.all([
        client.invalidateQueries({ queryKey: leadFieldsKeys.client(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.one(session.orgSlug, agentId) }),
      ]),
  });
}

/** A lead's captured details, each under the name it was captured with. */
export function useLeadCaptured(
  session: Session,
  leadId: string | null,
): UseQueryResult<CapturedFields> {
  return useQuery({
    queryKey: leadFieldsKeys.captured(session.orgSlug, leadId ?? ""),
    queryFn: () =>
      apiRequest<CapturedFields>(session, `/v1/leads/${encodeURIComponent(leadId ?? "")}/captured`),
    enabled: Boolean(leadId),
  });
}

// ------------------------------------------------------------------------------- admin

export function useAdminLeadFields(tenantId: string): UseQueryResult<LeadFields> {
  return useQuery({
    queryKey: leadFieldsKeys.admin(tenantId),
    queryFn: () => apiRequest<LeadFields>(adminSession(), adminPath(tenantId)),
    enabled: Boolean(tenantId),
    refetchInterval: (query) => (drafting(query.state.data) ? DRAFT_POLL_MS : false),
  });
}

export function useAdminDraftLeadFields(
  tenantId: string,
): UseMutationResult<DraftRequestOut, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<DraftRequestOut>(adminSession(), `${adminPath(tenantId)}/draft`, {
        method: "POST",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
  });
}

export function useAdminReplaceLeadFields(
  tenantId: string,
): UseMutationResult<
  ReplaceOut,
  Error,
  { agent_ids?: string[] | null; business_type?: BusinessType | null }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<ReplaceOut>(adminSession(), `${adminPath(tenantId)}/replace`, {
        method: "POST",
        body,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
  });
}

export function useAdminSaveAgentLeadFields(
  tenantId: string,
): UseMutationResult<ExtractionSchemaOut, Error, SaveAgentLeadFieldsIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, fields, expected_version }) =>
      apiRequest<ExtractionSchemaOut>(
        adminSession(),
        `/v1/admin/tenants/${encodeURIComponent(tenantId)}/agents/${encodeURIComponent(agentId)}/extraction-schema`,
        { method: "PUT", body: { fields, expected_version } },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
  });
}
