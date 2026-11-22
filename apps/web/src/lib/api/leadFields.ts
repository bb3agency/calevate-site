"use client";

/**
 * The lead details a business captures (founder decision 15; per campaign and line since
 * D-1029): the fixed core every lead carries, the business's starting set, every open
 * campaign's and line's own list, and the one AI draft.
 *
 * Reads, the draft review and the account-wide apply are `/v1/lead-fields` (client; the draft
 * itself is asked of Pip, D-821) and `/v1/admin/tenants/{id}/lead-fields` (operator). One
 * job's list is saved through that job's own notes route (`lib/api/campaignWorkspace`, and its
 * admin twin here), so a list has one write path whichever screen edits it.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import type { JobKind, JobNotes, JobNotesInput } from "./campaignWorkspace";
import { apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadFields = Schemas["LeadFieldsOut"];
export type LeadFieldsJob = Schemas["LeadFieldsJobOut"];
export type LeadFieldsDraft = Schemas["LeadFieldsDraftOut"];
export type LeadField = Schemas["ExtractionField"];
export type JobRef = Schemas["JobRefIn"];
export type ReplaceOut = Schemas["ReplaceOut"];
export type DraftRequestOut = Schemas["DraftRequestOut"];
export type DraftReviewOut = Schemas["LeadFieldsReviewOut"];
export type DraftReviewIn = Schemas["LeadFieldsReviewIn"];
export type CapturedField = Schemas["CapturedFieldOut"];
export type CapturedFields = Schemas["CapturedFieldsOut"];
export type BusinessType = NonNullable<Schemas["AdminReplaceIn"]["business_type"]>;

export const leadFieldsKeys = {
  client: (org: string) => ["lead-fields", org] as const,
  admin: (tenantId: string) => ["admin", "lead-fields", tenantId] as const,
  adminNotes: (tenantId: string, kind: JobKind, jobId: string) =>
    ["admin", "lead-fields", tenantId, "notes", kind, jobId] as const,
  captured: (org: string, leadId: string) => ["lead-captured", org, leadId] as const,
};

/** The ref an apply sends for a job: its id and the digest of the list the screen showed. */
export function jobRef(job: LeadFieldsJob): JobRef {
  return { kind: job.kind, id: job.id, digest: job.digest };
}

/** While a draft is being written the screen asks again on this interval, then stops. */
const DRAFT_POLL_MS = 3000;

function drafting(data: LeadFields | undefined): boolean {
  return data?.draft?.status === "queued" || data?.draft?.status === "running";
}

const adminPath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/lead-fields`;

/** Every job's list after an apply: the per-job editors and their suggestions re-read. */
function refreshJobs(client: ReturnType<typeof useQueryClient>, org: string): Promise<unknown> {
  return Promise.all(
    [["lead-fields", org], ["campaign-notes", org], ["line-notes", org], ["lead-suggestions", org]].map(
      (queryKey) => client.invalidateQueries({ queryKey }),
    ),
  );
}

// ------------------------------------------------------------------------------- client

export function useLeadFields(session: Session): UseQueryResult<LeadFields> {
  return useQuery({
    queryKey: leadFieldsKeys.client(session.orgSlug),
    queryFn: () => apiRequest<LeadFields>(session, "/v1/lead-fields"),
    refetchInterval: untilRefused((query) => (drafting(query.state.data) ? DRAFT_POLL_MS : false)),
  });
}

/**
 * Keep some or none of the drafted details (D-821) and write what is kept onto the ticked
 * campaigns and lines. The draft itself is asked of Pip.
 */
export function useReviewLeadFieldsDraft(
  session: Session,
): UseMutationResult<DraftReviewOut, Error, DraftReviewIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: DraftReviewIn) =>
      apiRequest<DraftReviewOut>(session, "/v1/lead-fields/draft/review", { method: "POST", body }),
    onSuccess: () => refreshJobs(client, session.orgSlug),
  });
}

export function useReplaceLeadFields(
  session: Session,
): UseMutationResult<ReplaceOut, Error, { jobs: JobRef[] }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<ReplaceOut>(session, "/v1/lead-fields/replace", { method: "POST", body }),
    onSuccess: () => refreshJobs(client, session.orgSlug),
  });
}

/** The client's names for the core details, by key; a blank name is the platform's again. */
export type CoreLabelsIn = Schemas["CoreLabelsIn"];

/** Every screen that prints a core detail's name: the lists, a lead, a call, the new-agent
 *  preview. A rename names no lead, so each family is refreshed by its prefix. */
function refreshCoreNames(client: ReturnType<typeof useQueryClient>, org: string): Promise<unknown> {
  return Promise.all(
    [["leads", org], ["lead", org], ["lead-captured", org], ["calls", org], ["calls-log", org], ["call", org], ["agent-starters", org]].map(
      (queryKey) => client.invalidateQueries({ queryKey }),
    ),
  );
}

export function useNameCoreDetails(session: Session): UseMutationResult<LeadFields, Error, CoreLabelsIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<LeadFields>(session, "/v1/lead-fields/core-labels", { method: "PUT", body }),
    onSuccess: (data) => {
      client.setQueryData(leadFieldsKeys.client(session.orgSlug), data);
      return refreshCoreNames(client, session.orgSlug);
    },
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
    refetchInterval: untilRefused((query) => (drafting(query.state.data) ? DRAFT_POLL_MS : false)),
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
): UseMutationResult<ReplaceOut, Error, { jobs: JobRef[]; business_type?: BusinessType | null }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<ReplaceOut>(adminSession(), `${adminPath(tenantId)}/replace`, {
        method: "POST",
        body,
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
        client.invalidateQueries({ queryKey: ["admin", "lead-suggestions", tenantId] }),
      ]),
  });
}

export function useAdminNameCoreDetails(
  tenantId: string,
): UseMutationResult<LeadFields, Error, CoreLabelsIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<LeadFields>(adminSession(), `${adminPath(tenantId)}/core-labels`, {
        method: "PUT",
        body,
      }),
    onSuccess: (data) => client.setQueryData(leadFieldsKeys.admin(tenantId), data),
  });
}

/** One client job's notes path, the operator's twin of `campaignWorkspace.jobNotesPath`. */
function adminNotesPath(tenantId: string, kind: JobKind, jobId: string): string {
  const tenant = encodeURIComponent(tenantId);
  const id = encodeURIComponent(jobId);
  return kind === "campaign"
    ? `/v1/admin/tenants/${tenant}/campaigns/${id}/notes`
    : `/v1/admin/tenants/${tenant}/inbound-lines/${id}/notes`;
}

function adminNotesQuery(tenantId: string, kind: JobKind, jobId: string) {
  return {
    queryKey: leadFieldsKeys.adminNotes(tenantId, kind, jobId),
    queryFn: () => apiRequest<JobNotes>(adminSession(), adminNotesPath(tenantId, kind, jobId)),
  };
}

export function useAdminJobNotes(tenantId: string, kind: JobKind, jobId: string): UseQueryResult<JobNotes> {
  return useQuery(adminNotesQuery(tenantId, kind, jobId));
}

export function useAdminSaveJobNotes(
  tenantId: string,
  kind: JobKind,
  jobId: string,
): UseMutationResult<JobNotes, Error, JobNotesInput> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: JobNotesInput) =>
      apiRequest<JobNotes>(adminSession(), adminNotesPath(tenantId, kind, jobId), {
        method: "PUT",
        body: input,
      }),
    // The whole admin family: the job's notes, and the job list's digests beside them.
    onSuccess: () => client.invalidateQueries({ queryKey: leadFieldsKeys.admin(tenantId) }),
  });
}

/** Another client job's list, read once when the operator imports it into an editor. */
export function useAdminFetchJobNotes(tenantId: string, kind: JobKind): (jobId: string) => Promise<JobNotes> {
  const client = useQueryClient();
  return (jobId: string) => client.fetchQuery(adminNotesQuery(tenantId, kind, jobId));
}
