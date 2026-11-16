"use client";

/**
 * Inbound lines (D-997): what the business's numbers say when called, each in one agent's
 * voice. `/v1/inbound-lines`.
 *
 * The line owns its words (main task, sources, script, which of the agent's actions it
 * uses); the agent is only the voice. Every write that changes what callers hear answers
 * with the line, so the cache takes the server's copy rather than refetching it.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { PIP_POLL_MS, type CampaignProposal } from "./campaignWorkspace";
import { apiRequest, type Session } from "./client";
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

export function useInboundLines(session: Session): UseQueryResult<InboundLine[]> {
  return useQuery({
    queryKey: inboundLineKeys.all(session.orgSlug),
    queryFn: async () => (await apiRequest<{ lines: InboundLine[] }>(session, BASE)).lines,
  });
}

export function useInboundLine(session: Session, lineId: string): UseQueryResult<InboundLine> {
  return useQuery({
    queryKey: inboundLineKeys.one(session.orgSlug, lineId),
    queryFn: () => apiRequest<InboundLine>(session, linePath(lineId)),
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

/**
 * A write on one line. The line the server answers with replaces the cached one; a write
 * that answers nothing refetches it. The list is refetched either way, since it shows the
 * same line's name, voice, numbers and state.
 */
function useLineMutation<TIn>(session: Session, lineId: string, call: (input: TIn) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (out) => {
      if (out && typeof out === "object" && "agent_id" in out && "numbers" in out) {
        client.setQueryData(inboundLineKeys.one(session.orgSlug, lineId), out);
      } else {
        void client.invalidateQueries({ queryKey: inboundLineKeys.one(session.orgSlug, lineId) });
      }
      void client.invalidateQueries({ queryKey: inboundLineKeys.all(session.orgSlug), exact: true });
    },
    // A refusal titled "Saved, but not live yet" kept the edit, so the page must show it.
    onError: () => void client.invalidateQueries({ queryKey: inboundLineKeys.one(session.orgSlug, lineId) }),
  });
}

export type LinePatch = { name?: string; agent_id?: string; main_task?: string };

export function useUpdateInboundLine(session: Session, lineId: string) {
  return useLineMutation(session, lineId, (patch: LinePatch) =>
    apiRequest<InboundLine>(session, linePath(lineId), { method: "PATCH", body: patch }),
  );
}

export function useSetLineSources(session: Session, lineId: string) {
  return useLineMutation(session, lineId, (sourceIds: string[]) =>
    apiRequest<InboundLine>(session, `${linePath(lineId)}/sources`, { method: "PUT", body: { source_ids: sourceIds } }),
  );
}

/** The agent's actions this line does not use, by name; every other one stays on. */
export function useSetLineActions(session: Session, lineId: string) {
  return useLineMutation(session, lineId, (off: string[]) =>
    apiRequest<InboundLine>(session, `${linePath(lineId)}/actions`, { method: "PUT", body: { off } }),
  );
}

/** Save the script and put it live; `proposalId` settles the Pip draft it came from. */
export function useSaveLineScript(session: Session, lineId: string) {
  return useLineMutation(session, lineId, ({ script, proposalId }: { script: CallScript; proposalId?: string }) =>
    apiRequest<InboundLine>(session, `${linePath(lineId)}/script`, {
      method: "PUT",
      body: proposalId ? { script, proposal_id: proposalId } : { script },
    }),
  );
}

export function usePublishInboundLine(session: Session, lineId: string) {
  return useLineMutation(session, lineId, () =>
    apiRequest<InboundLine>(session, `${linePath(lineId)}/publish`, { method: "POST" }),
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
