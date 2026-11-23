"use client";

/**
 * Inbound lines (D-997): what the business's numbers say when called, each in one agent's
 * voice. `/v1/inbound-lines`.
 *
 * The line owns its words (main task, sources, script, which of the agent's actions it
 * uses); the agent is only the voice. Every write that changes what callers hear answers
 * with the line, so the cache takes the server's copy rather than refetching it.
 */

import {
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
  type Mutation,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useRef } from "react";

import { PIP_POLL_MS, type CampaignProposal } from "./campaignWorkspace";
import { ApiProblem, apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";
import type { CallScript } from "./script";

type Schemas = components["schemas"];
export type InboundLine = Omit<Schemas["InboundLineOut"], "script" | "proposal"> & {
  script: CallScript | null;
  proposal: CampaignProposal | null;
};
export type LineCall = Schemas["LineCallOut"];

export const inboundLineKeys = {
  all: (org: string) => ["inbound-lines", org] as const,
  one: (org: string, lineId: string) => ["inbound-lines", org, lineId] as const,
  // Its own family so a new call refreshes it with the call logs (`live/topics.ts`).
  calls: (org: string, lineId: string) => ["inbound-line-calls", org, lineId] as const,
};

const BASE = "/v1/inbound-lines";
const linePath = (lineId: string) => `${BASE}/${encodeURIComponent(lineId)}`;

export function useInboundLines(session: Session, enabled = true): UseQueryResult<InboundLine[]> {
  return useQuery({
    queryKey: inboundLineKeys.all(session.orgSlug),
    queryFn: async () => (await apiRequest<{ lines: InboundLine[] }>(session, BASE)).lines,
    enabled,
  });
}

export function useInboundLine(session: Session, lineId: string, enabled = true): UseQueryResult<InboundLine> {
  return useQuery({
    queryKey: inboundLineKeys.one(session.orgSlug, lineId),
    queryFn: () => apiRequest<InboundLine>(session, linePath(lineId)),
    enabled,
    refetchInterval: untilRefused((query) => (query.state.data?.proposal?.status === "drafting" ? PIP_POLL_MS : false)),
  });
}

export function useLineCalls(session: Session, lineId: string): UseQueryResult<LineCall[]> {
  return useQuery({
    queryKey: inboundLineKeys.calls(session.orgSlug, lineId),
    queryFn: async () => (await apiRequest<{ calls: LineCall[] }>(session, `${linePath(lineId)}/calls`)).calls,
  });
}

export type NewLine = { agent_id: string; name?: string; main_task?: string };

export function useCreateInboundLine(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (line: NewLine) => apiRequest<InboundLine>(session, BASE, { method: "POST", body: line }),
    onSuccess: (line) => {
      client.setQueryData(inboundLineKeys.one(session.orgSlug, line.id), line);
      void client.invalidateQueries({ queryKey: inboundLineKeys.all(session.orgSlug), exact: true });
    },
  });
}

/** Every write on one line is filed under this key, so the page can read their outcomes. */
const lineWriteKey = (org: string, lineId: string) => ["inbound-line-write", org, lineId] as const;

/**
 * The title the api gives a write it kept while the put-live after it was refused
 * (`inbound/routes._put_live_after_save`).
 */
export const SAVED_NOT_LIVE_TITLE = "Saved, but not live yet";

export function isSavedNotLive(error: unknown): boolean {
  return error instanceof ApiProblem && error.title === SAVED_NOT_LIVE_TITLE;
}

/** Whether a successful write with this input put the line live again (when it was live). */
type Republishes<TIn> = (input: TIn) => boolean;

/**
 * A write on one line. The line the server answers with replaces the cached one; a write
 * that answers nothing refetches it. The list is refetched either way, since it shows the
 * same line's name, voice, numbers and state.
 */
function useLineMutation<TIn>(
  session: Session,
  lineId: string,
  call: (input: TIn) => Promise<unknown>,
  alsoShownBy: readonly (readonly unknown[])[] = [],
  republishes?: Republishes<TIn>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationKey: lineWriteKey(session.orgSlug, lineId),
    meta: republishes ? { republishes } : undefined,
    mutationFn: call,
    onSuccess: (out) => {
      if (out && typeof out === "object" && "agent_id" in out && "numbers" in out) {
        client.setQueryData(inboundLineKeys.one(session.orgSlug, lineId), out);
      } else {
        void client.invalidateQueries({ queryKey: inboundLineKeys.one(session.orgSlug, lineId) });
      }
      void client.invalidateQueries({ queryKey: inboundLineKeys.all(session.orgSlug), exact: true });
      for (const queryKey of alsoShownBy) void client.invalidateQueries({ queryKey });
    },
    // A refusal titled "Saved, but not live yet" kept the edit, so the page must show it.
    onError: () => void client.invalidateQueries({ queryKey: inboundLineKeys.one(session.orgSlug, lineId) }),
  });
}

function wentLive(mutation: Mutation<unknown, Error, unknown, unknown>): boolean {
  const republishes = mutation.options.meta?.republishes as Republishes<unknown> | undefined;
  return mutation.state.status === "success" && republishes !== undefined && republishes(mutation.state.variables);
}

/**
 * Whether this line holds an edit callers do not hear yet: the latest write that put it live
 * or was refused with `SAVED_NOT_LIVE_TITLE` was the refusal. A live line still reads as live
 * then, since its engine agent answers with what it had before, so this is what offers its
 * Put it live.
 */
export function useLineAwaitsPutLive(session: Session, lineId: string): boolean {
  const outcomes = useMutationState({
    filters: { mutationKey: lineWriteKey(session.orgSlug, lineId) },
    select: (mutation) => ({
      at: mutation.state.submittedAt,
      refused: isSavedNotLive(mutation.state.error),
      live: wentLive(mutation),
    }),
  });
  let latest: { at: number; refused: boolean } | undefined;
  for (const outcome of outcomes) {
    if ((outcome.refused || outcome.live) && (!latest || outcome.at >= latest.at)) latest = outcome;
  }
  return latest?.refused ?? false;
}

export type LinePatch = { name?: string; agent_id?: string; main_task?: string };

export function useUpdateInboundLine(session: Session, lineId: string) {
  return useLineMutation(
    session,
    lineId,
    (patch: LinePatch) => apiRequest<InboundLine>(session, linePath(lineId), { method: "PATCH", body: patch }),
    // Phone numbers names each number's line, and the live topic a rename announces does not
    // reach that list.
    [["campaign-numbers", session.orgSlug]],
    // A new voice puts a live line live again; a name or a main task does not.
    (patch) => patch.agent_id !== undefined,
  );
}

export function useSetLineSources(session: Session, lineId: string) {
  return useLineMutation(session, lineId, (sourceIds: string[]) =>
    apiRequest<InboundLine>(session, `${linePath(lineId)}/sources`, { method: "PUT", body: { source_ids: sourceIds } }),
  );
}

/** The agent's actions this line does not use, by name; every other one stays on. */
export function useSetLineActions(session: Session, lineId: string) {
  return useLineMutation(
    session,
    lineId,
    (off: string[]) => apiRequest<InboundLine>(session, `${linePath(lineId)}/actions`, { method: "PUT", body: { off } }),
    [],
    () => true,
  );
}

/** Save the script and put it live; `proposalId` settles the Pip draft it came from. */
export function useSaveLineScript(session: Session, lineId: string) {
  return useLineMutation(
    session,
    lineId,
    ({ script, proposalId }: { script: CallScript; proposalId?: string }) =>
      apiRequest<InboundLine>(session, `${linePath(lineId)}/script`, {
        method: "PUT",
        body: proposalId ? { script, proposal_id: proposalId } : { script },
      }),
    [],
    () => true,
  );
}

export function usePublishInboundLine(session: Session, lineId: string) {
  return useLineMutation(
    session,
    lineId,
    () => apiRequest<InboundLine>(session, `${linePath(lineId)}/publish`, { method: "POST" }),
    [],
    () => true,
  );
}

export function useRequestLineScript(session: Session, lineId: string) {
  return useLineMutation(session, lineId, () =>
    apiRequest<CampaignProposal>(session, `${linePath(lineId)}/proposal`, { method: "POST" }),
  );
}

/** Stop Pip while it writes, or discard a written draft. */
export function useClearLineProposal(session: Session, lineId: string) {
  return useLineMutation(session, lineId, (proposalId: string) =>
    apiRequest<void>(session, `${linePath(lineId)}/proposal/${encodeURIComponent(proposalId)}`, { method: "DELETE" }),
  );
}

/** Put a number on this line; it leaves whichever line answered it before. */
export function useAssignLineNumber(session: Session, lineId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (numberId: string) =>
      apiRequest<InboundLine>(session, `${linePath(lineId)}/numbers`, { method: "POST", body: { number_id: numberId } }),
    onSuccess: (line) => {
      client.setQueryData(inboundLineKeys.one(session.orgSlug, lineId), line);
      // The list, the line it moved from, and the number's agent on the phone numbers screen.
      void client.invalidateQueries({ queryKey: ["inbound-lines", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["campaign-numbers", session.orgSlug] });
    },
  });
}

export type LineTestCall = Schemas["CampaignTestCallOut"];
export type LineTestCallItem = Schemas["CampaignTestCallItem"];

const lineTestCallsKey = (org: string, lineId: string) => ["inbound-line-test-calls", org, lineId] as const;
/** The account's saved test numbers: the campaigns' family, one list per account. */
const testNumbersKey = (org: string) => ["test-numbers", org];

/**
 * Ring the owner's own phone with this line (`POST /v1/inbound-lines/{id}/test-call`). Each
 * number keeps its Idempotency-Key until the call is placed, so a retried press is the same
 * call, never a second ring.
 */
export function useLineTestCall(session: Session, lineId: string) {
  const held = useRef(new Map<string, string>());
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ number, numberIsMine }: { number: string; numberIsMine: boolean }) => {
      const key = held.current.get(number) ?? crypto.randomUUID();
      held.current.set(number, key);
      return apiRequest<LineTestCall>(session, `${linePath(lineId)}/test-call`, {
        method: "POST",
        body: { number, number_is_mine: numberIsMine },
        idempotencyKey: key,
      });
    },
    onSuccess: (_out, { number }) => {
      held.current.delete(number);
      void client.invalidateQueries({ queryKey: inboundLineKeys.one(session.orgSlug, lineId) });
      void client.invalidateQueries({ queryKey: lineTestCallsKey(session.orgSlug, lineId) });
      void client.invalidateQueries({ queryKey: testNumbersKey(session.orgSlug) });
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
    },
  });
}

const LIVE_STATUSES = new Set(["queued", "ringing", "in_progress"]);

/** The test calls rung through this line, re-read every 10 s while one is still going. */
export function useLineTestCalls(session: Session, lineId: string): UseQueryResult<LineTestCallItem[]> {
  return useQuery({
    queryKey: lineTestCallsKey(session.orgSlug, lineId),
    queryFn: () => apiRequest<LineTestCallItem[]>(session, `${linePath(lineId)}/test-calls`),
    refetchInterval: untilRefused((query: { state: { data?: LineTestCallItem[] } }) =>
      (query.state.data ?? []).some((call) => LIVE_STATUSES.has(call.status)) ? 10_000 : false,
    ),
  });
}

export function useLineTestNumbers(session: Session, lineId: string) {
  return useQuery({
    queryKey: testNumbersKey(session.orgSlug),
    queryFn: () => apiRequest<Schemas["TestNumbersOut"]>(session, `${linePath(lineId)}/test-numbers`),
  });
}

export function useArchiveInboundLine(session: Session, lineId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<void>(session, `${linePath(lineId)}/archive`, { method: "POST" }),
    onSuccess: () => {
      client.removeQueries({ queryKey: inboundLineKeys.one(session.orgSlug, lineId) });
      void client.invalidateQueries({ queryKey: inboundLineKeys.all(session.orgSlug), exact: true });
    },
  });
}
