"use client";

/**
 * The lead details a business captures (founder decision 15): the fixed core every lead
 * carries, each agent's own business fields, and the one AI draft a custom business gets.
 *
 * Reads and the draft/replace actions are `/v1/lead-fields` (client) and
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
export type ReplaceOut = Schemas["ReplaceOut"];
export type DraftRequestOut = Schemas["DraftRequestOut"];
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

export function useDraftLeadFields(
  session: Session,
): UseMutationResult<DraftRequestOut, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<DraftRequestOut>(session, "/v1/lead-fields/draft", { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: leadFieldsKeys.client(session.orgSlug) }),
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
      ]),
  });
}

export function useSaveAgentLeadFields(
  session: Session,
): UseMutationResult<ExtractionSchemaOut, Error, { agentId: string; fields: LeadField[] }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, fields }) =>
      apiRequest<ExtractionSchemaOut>(
        session,
        `/v1/agents/${encodeURIComponent(agentId)}/extraction-schema`,
        { method: "PUT", body: { fields } },
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
): UseMutationResult<ExtractionSchemaOut, Error, { agentId: string; fields: LeadField[] }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, fields }) =>
      apiRequest<ExtractionSchemaOut>(
        adminSession(),
        `/v1/admin/tenants/${encodeURIComponent(tenantId)}/agents/${encodeURIComponent(agentId)}/extraction-schema`,
        { method: "PUT", body: { fields } },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
  });
}
