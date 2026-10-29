"use client";

/**
 * Follow-ups (D-940): per-lead journeys built by Pip, with small edits by hand.
 *
 *   GET  /v1/follow-ups                              `leads:read`, at most 200 rows
 *   POST /v1/follow-ups                              `leads:dispatch` (a draft)
 *   GET  /v1/follow-ups/starters                     `leads:read`
 *   GET  /v1/follow-ups/{id}                         `leads:read`
 *   PATCH /v1/follow-ups/{id}                        `leads:dispatch` (small edits, to the draft)
 *   POST /v1/follow-ups/{id}/publish|pause|resume|turn-off   `leads:dispatch`
 *   POST /v1/follow-ups/{id}/start                   `leads:dispatch`
 *   GET  /v1/follow-ups/{id}/runs?cursor=            `leads:read`
 *   POST /v1/follow-ups/{id}/runs/{run_id}/stop      `leads:dispatch`
 *   GET  /v1/follow-ups/{id}/results                 `leads:read`
 *
 * Every shape is the generated one (`schema.d.ts`); the names below are aliases so a
 * screen imports from here, not from the schema.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import { lensBody, type LeadLens } from "./leads";
import type { components } from "./schema";

// ---- wire types ---------------------------------------------------------------------

type Schemas = components["schemas"];

export type FollowUpOut = Schemas["FollowUpOut"];
export type FollowUpSummaryOut = Schemas["FollowUpSummaryOut"];
export type FollowUpListOut = Schemas["FollowUpListOut"];
export type FollowUpStarterOut = Schemas["FollowUpStarterOut"];
export type FollowUpStartersOut = Schemas["FollowUpStartersOut"];
export type FollowUpCreateIn = Schemas["FollowUpCreateIn"];
export type FollowUpEditIn = Schemas["FollowUpEditIn"];
export type FollowUpStepEditIn = Schemas["StepEditIn"];
export type FollowUpWaitIn = Schemas["WaitEditIn"];
export type FollowUpStartOut = Schemas["FollowUpStartOut"];
export type FollowUpRunOut = Schemas["FollowUpRunOut"];
export type FollowUpRunsOut = Schemas["FollowUpRunsOut"];
export type FollowUpResultsOut = Schemas["FollowUpResultsOut"];
export type FollowUpProblem = Schemas["ProblemOut"];
export type FollowUpSettings = Schemas["Settings"];

export type FollowUpStatus = FollowUpOut["status"];
export type FollowUpTrigger = FollowUpOut["trigger"];
/** One step as the server sends it back, with its plain-words `summary`. */
export type FollowUpStep = FollowUpOut["steps"][number];
export type FollowUpStepKind = FollowUpStep["kind"];
export type FollowUpStarterNeed = FollowUpStarterOut["needs"][number];
export type FollowUpRunStatus = FollowUpRunOut["status"];

/** More than this many leads at once is refused (`follow_up_start_too_many`); Pip starts
 *  a larger set as a plan. */
export const FOLLOW_UP_START_MAX = 200;


// ---- hooks --------------------------------------------------------------------------

const PATH = "/v1/follow-ups";

export const followUpKeys = {
  all: (org: string) => ["follow-ups", org] as const,
  list: (org: string) => ["follow-ups", org, "list"] as const,
  starters: (org: string) => ["follow-ups", org, "starters"] as const,
  one: (org: string, id: string) => ["follow-ups", org, "one", id] as const,
  runs: (org: string, id: string) => ["follow-ups", org, "runs", id] as const,
  results: (org: string, id: string) => ["follow-ups", org, "results", id] as const,
};

/** Every Follow-up read refreshes after any write: counts, status and rows all move. */
function refresh(client: QueryClient, org: string): Promise<unknown> {
  return client.invalidateQueries({ queryKey: followUpKeys.all(org) });
}

export function useFollowUps(session: Session): UseQueryResult<FollowUpListOut> {
  return useQuery({
    queryKey: followUpKeys.list(session.orgSlug),
    queryFn: () => apiRequest<FollowUpListOut>(session, PATH),
  });
}

export function useFollowUpStarters(
  session: Session,
  enabled = true,
): UseQueryResult<FollowUpStartersOut> {
  return useQuery({
    queryKey: followUpKeys.starters(session.orgSlug),
    queryFn: () => apiRequest<FollowUpStartersOut>(session, `${PATH}/starters`),
    enabled,
  });
}

export function useFollowUp(session: Session, id: string): UseQueryResult<FollowUpOut> {
  return useQuery({
    queryKey: followUpKeys.one(session.orgSlug, id),
    queryFn: () => apiRequest<FollowUpOut>(session, `${PATH}/${id}`),
  });
}

export function useCreateFollowUp(
  session: Session,
): UseMutationResult<FollowUpOut, Error, FollowUpCreateIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => apiRequest<FollowUpOut>(session, PATH, { method: "POST", body }),
    // Settled: a 409 `follow_up_starter_exists` means the list it was offered from is stale.
    onSettled: () => refresh(client, session.orgSlug),
  });
}

/**
 * A small edit to the draft. A removal drops the step from the cached copy at once and
 * puts it back if the server refuses; every other edit waits for the server, whose answer
 * carries the step's new `summary`.
 */
export function useEditFollowUp(
  session: Session,
  id: string,
): UseMutationResult<FollowUpOut, Error, FollowUpEditIn, { before?: FollowUpOut }> {
  const client = useQueryClient();
  const key = followUpKeys.one(session.orgSlug, id);
  return useMutation({
    mutationFn: (body) =>
      apiRequest<FollowUpOut>(session, `${PATH}/${id}`, { method: "PATCH", body }),
    onMutate: async (body) => {
      const removed = new Set(
        (body.step_edits ?? []).filter((edit) => edit.remove).map((edit) => edit.step_id),
      );
      if (removed.size === 0) return {};
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<FollowUpOut>(key);
      if (before) {
        client.setQueryData<FollowUpOut>(key, {
          ...before,
          steps: before.steps.filter((step) => !removed.has(step.id)),
          has_unpublished_changes: true,
        });
      }
      return { before };
    },
    onError: (_error, _body, context) => {
      if (context?.before) client.setQueryData(key, context.before);
    },
    onSuccess: (data) => client.setQueryData(key, data),
    onSettled: () => refresh(client, session.orgSlug),
  });
}

export type FollowUpMove = "publish" | "pause" | "resume" | "turn-off";

/**
 * Publish, pause, resume or turn off. Publish carries the `updated_at` the person saw, so a
 * colleague's change in between is a 409 rather than a publish of something unseen.
 */
export function useMoveFollowUp(
  session: Session,
  id: string,
): UseMutationResult<FollowUpOut, Error, { move: FollowUpMove; expectedUpdatedAt?: string }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ move, expectedUpdatedAt }) =>
      apiRequest<FollowUpOut>(session, `${PATH}/${id}/${move}`, {
        method: "POST",
        body: move === "publish" ? { expected_updated_at: expectedUpdatedAt } : {},
      }),
    onSuccess: (data) => client.setQueryData(followUpKeys.one(session.orgSlug, id), data),
    // Settled, not success: a refused publish (422) brings back the draft's `problems`.
    onSettled: () => refresh(client, session.orgSlug),
  });
}

export type FollowUpStartRequest =
  | { leadIds: string[] }
  | { lens: LeadLens; expectedCount: number };

export function useStartFollowUp(
  session: Session,
): UseMutationResult<FollowUpStartOut, Error, { followUpId: string } & FollowUpStartRequest> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request) =>
      apiRequest<FollowUpStartOut>(session, `${PATH}/${request.followUpId}/start`, {
        method: "POST",
        body:
          "leadIds" in request
            ? { lead_ids: request.leadIds }
            : { lens: lensBody(request.lens), expected_count: request.expectedCount },
      }),
    onSettled: () => refresh(client, session.orgSlug),
  });
}

export function useFollowUpRuns(session: Session, id: string) {
  return useInfiniteQuery({
    queryKey: followUpKeys.runs(session.orgSlug, id),
    queryFn: ({ pageParam }) =>
      apiRequest<FollowUpRunsOut>(
        session,
        `${PATH}/${id}/runs${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last: FollowUpRunsOut) => last.next_cursor,
  });
}

export function useStopFollowUpRun(
  session: Session,
  id: string,
): UseMutationResult<FollowUpRunOut, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId) =>
      apiRequest<FollowUpRunOut>(session, `${PATH}/${id}/runs/${runId}/stop`, { method: "POST" }),
    onSettled: () => refresh(client, session.orgSlug),
  });
}

export function useFollowUpResults(
  session: Session,
  id: string,
  enabled = true,
): UseQueryResult<FollowUpResultsOut> {
  return useQuery({
    queryKey: followUpKeys.results(session.orgSlug, id),
    queryFn: () => apiRequest<FollowUpResultsOut>(session, `${PATH}/${id}/results`),
    enabled,
  });
}
