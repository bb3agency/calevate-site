"use client";

/**
 * Follow-ups (D-940): per-lead journeys built by Pip, with small edits by hand.
 *
 *   GET  /v1/follow-ups                              `leads:read`
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
 * TODO(follow-ups merge): HAND-WRITTEN WIRE TYPES. The backend lane is building this
 * contract (docs/FOLLOW-UPS.md, "HTTP contract") in parallel, so `schema.d.ts` does not
 * carry it yet. Once it lands and `pnpm -C apps/web gen:api` has run, replace every
 * interface in the "wire types" block below with its generated alias, keeping the names:
 *
 *   export type FollowUpOut = Schemas["FollowUpOut"];   // and so on for each name below
 *
 * then delete the block. The names are the contract's own. Fields the contract does not
 * spell out are marked ASSUMED; the generated types win wherever they disagree.
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

// ---- wire types (hand-written; swap for schema.d.ts aliases once generated) ----------

export type FollowUpStatus = "draft" | "live" | "paused" | "off";

export type FollowUpTrigger =
  | { kind: "new_lead"; source_ids: string[] | null; only_if?: Record<string, unknown> | null }
  | {
      kind: "call_ended";
      agent_ids: string[] | null;
      calls: "inbound" | "outbound" | "both";
      outcomes: string[] | null;
      only_if?: Record<string, unknown> | null;
    }
  | { kind: "manual"; only_if?: Record<string, unknown> | null }
  | {
      kind: "lead_date";
      field: string;
      offset_days: number;
      at: string;
      only_if?: Record<string, unknown> | null;
    };

export type FollowUpStepKind =
  | "call"
  | "decide"
  | "wait"
  | "whatsapp"
  | "assign"
  | "set_status"
  | "tell_team"
  | "action"
  | "end";

/**
 * One step. `summary` is the server's plain line. Where it goes next: `next` for a
 * single-exit step, `exits` for a step with named exits (ASSUMED: `{answered,
 * not_reached}`, `{sent, not_sent}`, `{done, failed}`), and `on` + `other` for `decide`.
 */
export interface FollowUpStep {
  id: string;
  kind: FollowUpStepKind;
  summary: string;
  next?: string | null;
  exits?: Record<string, string | null>;
  on?: Record<string, string | null>;
  other?: string | null;
  agent_id?: string;
  wait_minutes?: number;
  retries?: number;
  retry_minutes?: number;
  minutes?: number;
  hours?: number;
  days?: number;
  until_field?: string;
  offset_days?: number;
  at?: string;
  template_id?: string;
  values?: Record<string, unknown>;
  user_id?: string;
  status?: string;
  contact_id?: string | null;
  why?: string;
  action_id?: string;
  goal?: boolean;
}

export interface FollowUpSettings {
  goal?: string | null;
  stop_on_reply?: boolean;
  stop_on_won_lost?: boolean;
  again?: "never" | "after_last" | "after_30_days";
  max_days?: number;
  starts_per_hour?: number | null;
}

export interface FollowUpProblem {
  step_id: string | null;
  code: string;
  message: string;
}

export interface FollowUpCounts {
  running: number;
  waiting: number;
  done_30d: number;
  goal_30d: number;
}

export interface FollowUpOut {
  id: string;
  name: string;
  status: FollowUpStatus;
  starter: string | null;
  trigger: FollowUpTrigger;
  settings: FollowUpSettings;
  steps: FollowUpStep[];
  has_unpublished_changes: boolean;
  live_version: { number: number; published_at: string } | null;
  counts: FollowUpCounts;
  problems: FollowUpProblem[];
  updated_at: string;
}

/** ASSUMED: the contract names the type, not its fields; a row needs these. */
export interface FollowUpSummaryOut {
  id: string;
  name: string;
  status: FollowUpStatus;
  starter: string | null;
  trigger: FollowUpTrigger;
  has_unpublished_changes: boolean;
  counts: FollowUpCounts;
  updated_at: string;
}

export interface FollowUpListOut {
  items: FollowUpSummaryOut[];
}

/** ASSUMED: one ready-made Follow-up, filled in for this account. */
export interface FollowUpStarterOut {
  key: string;
  name: string;
  trigger: FollowUpTrigger;
  steps: FollowUpStep[];
  settings: FollowUpSettings;
}

export interface FollowUpStarterListOut {
  items: FollowUpStarterOut[];
}

export interface FollowUpCreateIn {
  name: string;
  trigger: FollowUpTrigger;
  steps: FollowUpStep[];
  settings?: FollowUpSettings;
  starter?: string | null;
}

/** ASSUMED: `wait` carries one unit, as a `wait` step does; on a `call` step it is the
 *  wait before the first try. */
export interface FollowUpWaitIn {
  minutes?: number;
  hours?: number;
  days?: number;
}

export interface FollowUpStepEditIn {
  step_id: string;
  wait?: FollowUpWaitIn;
  template_id?: string;
  values?: Record<string, unknown>;
  agent_id?: string;
  remove?: boolean;
}

export interface FollowUpEditIn {
  name?: string;
  step_edits?: FollowUpStepEditIn[];
  settings?: FollowUpSettings;
}

export interface FollowUpStartOut {
  started: number;
  skipped: number;
  plan_id?: string | null;
}

export type FollowUpRunStatus = "running" | "waiting" | "done" | "stopped";

export interface FollowUpRunEventOut {
  step_id: string;
  kind: string;
  result: string;
  at: string;
  call_id: string | null;
}

/** ASSUMED beyond the table's columns: `lead_name` and `last_result` (the row needs them). */
export interface FollowUpRunOut {
  id: string;
  follow_up_id: string;
  lead_id: string | null;
  lead_name: string | null;
  status: FollowUpRunStatus;
  step_id: string | null;
  last_result: string | null;
  started_at: string;
  ended_at: string | null;
  end_reason: string | null;
  goal_reached: boolean;
  events?: FollowUpRunEventOut[];
}

export interface FollowUpRunListOut {
  items: FollowUpRunOut[];
  next_cursor: string | null;
}

export interface FollowUpResultsOut {
  days: number;
  started: number;
  finished: number;
  goal_reached: number;
  steps: { step_id: string; reached: number; exits: Record<string, number> }[];
}

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
): UseQueryResult<FollowUpStarterListOut> {
  return useQuery({
    queryKey: followUpKeys.starters(session.orgSlug),
    queryFn: () => apiRequest<FollowUpStarterListOut>(session, `${PATH}/starters`),
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
    onSuccess: () => refresh(client, session.orgSlug),
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
      apiRequest<FollowUpRunListOut>(
        session,
        `${PATH}/${id}/runs${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last: FollowUpRunListOut) => last.next_cursor,
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
