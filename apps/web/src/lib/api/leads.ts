"use client";

/**
 * The leads data layer — ownership, history, and the list filter that needs both.
 *
 * **Why `useLeads` lives here and not beside `useMe` in `hooks.ts`.** The list gained a
 * server-side `assigned_to` filter, and a filter that a hook's type does not name is a
 * filter that cannot be sent: `hooks.ts::useLeads` declares
 * `{status, search, limit, offset}` and nothing more. This module replaces it, and the
 * ONE caller — `app/c/[slug]/leads` — moves with it in the same change, so there are
 * never two live ways to read the leads list.
 *
 * `hooks.ts::useLeads` was deleted in the same change, so the move is a replacement
 * rather than a fork — two live ways to read one list is the defect even when both
 * work. The query KEY is deliberately identical (`["leads", orgSlug, filters]`), so
 * `hooks.ts::useUpdateLeadStatus`'s `invalidateQueries({queryKey: ["leads", orgSlug]})`
 * keeps working across the move — a cache invalidation that silently stopped matching
 * would look exactly like a screen that does not refresh.
 *
 * Everything is aliased from the GENERATED schema, never hand-written: the drift this
 * repo has already paid for once (a local `UsagePanel` interface that quietly lost
 * `overage_rate_inr`) is the reason.
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadList = Schemas["LeadListOut"];
export type Lead = Schemas["LeadOut"];
export type LeadStatus = Lead["status"];
/** One colleague. Ids and display names only — the API sends no email (tenancy/routes.py). */
export type Member = Schemas["MemberOut"];
export type LeadTimeline = Schemas["LeadTimelineOut"];
export type LeadTimelineEvent = Schemas["LeadTimelineEventOut"];

/** The leads list polls slowly — a lead lands with the post-call pipeline, not live. */
const SLOW_INTERVAL_MS = 60_000;

export interface LeadFilters {
  status?: string;
  search?: string;
  /** A member's id. "Assigned to me" is this, with the caller's own id from `/v1/me`. */
  assigned_to?: string;
  limit?: number;
  offset?: number;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function useLeads(session: Session, filters: LeadFilters = {}): UseQueryResult<LeadList> {
  return useQuery({
    // Same key shape as the hook this replaces, so existing invalidations still match.
    queryKey: ["leads", session.orgSlug, filters],
    queryFn: () => apiRequest<LeadList>(session, `/v1/leads${query({ ...filters })}`),
    refetchInterval: SLOW_INTERVAL_MS,
    refetchOnWindowFocus: true,
    // Changing a filter chip or the search box is a re-filter, not a navigation:
    // keeping the previous rows on screen beats blanking the table to a skeleton
    // (and, worse, flashing "No leads yet") on every change of the query key.
    placeholderData: keepPreviousData,
  });
}

export function useLead(session: Session, leadId: string): UseQueryResult<Lead> {
  return useQuery({
    queryKey: ["lead", session.orgSlug, leadId],
    queryFn: () => apiRequest<Lead>(session, `/v1/leads/${leadId}`),
    enabled: Boolean(leadId),
  });
}

/**
 * One lead's history (ROADMAP M3).
 *
 * NO `placeholderData` and no fallback anywhere: an empty timeline and a timeline whose
 * request failed are different sentences, and the screen has to be able to tell them
 * apart from the query alone (BUILD-LOG §52 — "loading is a skeleton, failure is a
 * refusal, and neither is a number, a state, or an empty state").
 */
export function useLeadTimeline(
  session: Session,
  leadId: string,
  limit = 50,
): UseQueryResult<LeadTimeline> {
  return useQuery({
    queryKey: ["lead-timeline", session.orgSlug, leadId, limit],
    queryFn: () =>
      apiRequest<LeadTimeline>(session, `/v1/leads/${leadId}/timeline${query({ limit })}`),
    enabled: Boolean(leadId),
  });
}

/**
 * The account's team, for the assignee picker.
 *
 * `staleTime` is generous because a team changes when somebody accepts an invitation,
 * which is not a thing that happens while a table is open.
 */
export function useMembers(session: Session): UseQueryResult<Member[]> {
  return useQuery({
    queryKey: ["members", session.orgSlug],
    queryFn: () => apiRequest<Member[]>(session, "/v1/members"),
    staleTime: 5 * 60_000,
  });
}

/**
 * Set or clear a lead's owner.
 *
 * `userId: null` is sent as an explicit `null` and MUST stay one: the API tells
 * "unassign" from "leave the owner alone" by whether the key is present in the body
 * (`crm.routes.patch_lead`), so dropping the key when the value is null — which is what
 * a helper that strips undefined-ish values would do — would silently turn every
 * unassignment into a no-op that answered 200.
 */
export function useAssignLead(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, userId }: { leadId: string; userId: string | null }) =>
      apiRequest<Lead>(session, `/v1/leads/${leadId}`, {
        method: "PATCH",
        body: { assigned_to: userId },
      }),
    onSuccess: (_lead, { leadId }) => {
      // Invalidate rather than patch: the assignment also writes a timeline row, and
      // the list's own status counts are computed over the filtered set — so a screen
      // filtered to "assigned to me" has to re-ask rather than re-render.
      void client.invalidateQueries({ queryKey: ["leads", session.orgSlug] });
      void client.invalidateQueries({
        queryKey: ["lead", session.orgSlug, leadId],
      });
      void client.invalidateQueries({
        queryKey: ["lead-timeline", session.orgSlug, leadId],
      });
    },
  });
}
