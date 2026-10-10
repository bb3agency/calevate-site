"use client";

/**
 * Teaching the agents and the improvement loop (`apps/api/teach/`).
 *
 * The teach box posts words, a photo, a file or a voice note; a worker reads and sorts it,
 * so the screen polls the teaching until it is `heard` (check the words) or `ready`
 * (review). Saving puts facts into the business's knowledge at once and rules into the
 * chosen agent's script as waiting rules.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, apiUpload, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Knows = Schemas["KnowsOut"];
export type Fact = Schemas["FactOut"];
export type KnownItem = Schemas["KnownItemOut"];
export type Teaching = Schemas["TeachingOut"];
export type TeachItem = Schemas["TeachItemIO"];
export type Struggle = Schemas["StruggleOut"];
export type ProposedRule = Schemas["RuleOut"];
export type TestCase = Schemas["TestCaseOut"];
export type TestCases = Schemas["TestCasesOut"];
export type CaseDraft = Schemas["CaseDraftOut"];
export type TryChatReply = Schemas["TryChatOut"];

export type TeachUploadKind = "photo" | "file" | "voice";

const knowsKey = (slug: string) => ["kb-knows", slug] as const;
const struggleKey = (slug: string, agentId?: string) => ["kb-struggles", slug, agentId ?? null] as const;
const teachingKey = (slug: string, id: string | null) => ["kb-teaching", slug, id] as const;
const casesKey = (slug: string, agentId: string) => ["agent-test-cases", slug, agentId] as const;

/** A teaching the worker is still reading or sorting. */
export function isTeachingBusy(status: string | undefined): boolean {
  return status === "queued" || status === "reading" || status === "sorting";
}

export function useKnows(session: Session): UseQueryResult<Knows> {
  return useQuery({
    queryKey: knowsKey(session.orgSlug),
    queryFn: () => apiRequest<Knows>(session, "/v1/kb/knows"),
    // While new facts are on their way to the agents, look again so "Reaching your agents"
    // turns into nothing without a reload.
    refetchInterval: (query) =>
      query.state.data?.facts_state === "publishing" ? 15_000 : false,
  });
}

export function useStruggles(session: Session, agentId?: string): UseQueryResult<Struggle[]> {
  const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
  return useQuery({
    queryKey: struggleKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<Struggle[]>(session, `/v1/kb/struggles${query}`),
  });
}

export function useTeaching(session: Session, id: string | null): UseQueryResult<Teaching> {
  return useQuery({
    queryKey: teachingKey(session.orgSlug, id),
    queryFn: () => apiRequest<Teaching>(session, `/v1/kb/teach/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => (isTeachingBusy(query.state.data?.status) ? 1_500 : false),
  });
}

export function useStartTeaching(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (
      input:
        | { kind: "text"; words: string; gapId?: string | null }
        | { kind: TeachUploadKind; file: Blob; filename: string; gapId?: string | null },
    ): Promise<Teaching> => {
      if (input.kind === "text") {
        return apiRequest<Teaching>(session, "/v1/kb/teach", {
          method: "POST",
          body: { words: input.words, gap_id: input.gapId ?? null },
        });
      }
      const form = new FormData();
      form.append("file", input.file, input.filename);
      form.append("kind", input.kind);
      if (input.gapId) form.append("gap_id", input.gapId);
      return apiUpload<Teaching>(session, "/v1/kb/teach/upload", form);
    },
    onSuccess: (teaching) =>
      client.setQueryData(teachingKey(session.orgSlug, teaching.id), teaching),
  });
}

export function useConfirmWords(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, words }: { id: string; words: string }) =>
      apiRequest<Teaching>(session, `/v1/kb/teach/${id}/words`, {
        method: "POST",
        body: { words },
      }),
    onSuccess: (teaching) =>
      client.setQueryData(teachingKey(session.orgSlug, teaching.id), teaching),
  });
}

export function useSaveTeaching(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      items,
      agentId,
    }: {
      id: string;
      items: TeachItem[];
      agentId: string | null;
    }) =>
      apiRequest<Schemas["SavedOut"]>(session, `/v1/kb/teach/${id}/save`, {
        method: "POST",
        body: { items, agent_id: agentId },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: knowsKey(session.orgSlug) });
      void client.invalidateQueries({ queryKey: ["kb-struggles", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["kb", session.orgSlug] });
    },
  });
}

export function useDiscardTeaching(session: Session) {
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<Teaching>(session, `/v1/kb/teach/${id}/discard`, { method: "POST" }),
  });
}

export function useEditFact(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: {
      id: string;
      text?: string;
      question?: string;
      pinned?: boolean;
    }) => apiRequest<Fact>(session, `/v1/kb/facts/${id}`, { method: "PATCH", body: patch }),
    onSuccess: () => void client.invalidateQueries({ queryKey: knowsKey(session.orgSlug) }),
  });
}

export function useAddFact(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; question: string | null; pinned: boolean }) =>
      apiRequest<Fact>(session, "/v1/kb/facts", { method: "POST", body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: knowsKey(session.orgSlug) }),
  });
}

export function useReorderPinned(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) =>
      apiRequest<void>(session, "/v1/kb/facts/pinned-order", { method: "POST", body: { ids } }),
    onSettled: () => void client.invalidateQueries({ queryKey: knowsKey(session.orgSlug) }),
  });
}

export function useRemoveFact(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<void>(session, `/v1/kb/facts/${id}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: knowsKey(session.orgSlug) }),
  });
}

export function useProposedRules(session: Session, agentId: string) {
  return useQuery({
    queryKey: ["agent-proposed-rules", session.orgSlug, agentId],
    queryFn: () =>
      apiRequest<ProposedRule[]>(session, `/v1/agents/${agentId}/script/proposed-rules`),
  });
}

export function useResolveRule(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, status }: { ruleId: string; status: "applied" | "dismissed" }) =>
      apiRequest<ProposedRule>(
        session,
        `/v1/agents/${agentId}/script/proposed-rules/${ruleId}`,
        { method: "POST", body: { status } },
      ),
    onSuccess: () =>
      void client.invalidateQueries({
        queryKey: ["agent-proposed-rules", session.orgSlug, agentId],
      }),
  });
}

export function useTestCases(session: Session, agentId: string): UseQueryResult<TestCases> {
  return useQuery({
    queryKey: casesKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<TestCases>(session, `/v1/agents/${agentId}/test-cases`),
    refetchInterval: (query) =>
      query.state.data?.cases.some((c) => c.status !== "idle") ? 3_000 : false,
  });
}

export function useRunTestCases(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<TestCases>(session, `/v1/agents/${agentId}/test-cases/run`, { method: "POST" }),
    onSuccess: (data) => client.setQueryData(casesKey(session.orgSlug, agentId), data),
  });
}

export function useDeleteTestCase(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (caseId: string) =>
      apiRequest<void>(session, `/v1/agents/${agentId}/test-cases/${caseId}`, {
        method: "DELETE",
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: casesKey(session.orgSlug, agentId) }),
  });
}

export function useCaseDraft(session: Session, callId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["call-test-case-draft", session.orgSlug, callId],
    queryFn: () => apiRequest<CaseDraft>(session, `/v1/calls/${callId}/test-case-draft`),
    enabled,
  });
}

export function useMakeCallATest(session: Session, callId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; caller_lines: string[]; expected: string }) =>
      apiRequest<TestCase>(session, `/v1/calls/${callId}/test-case`, { method: "POST", body }),
    onSuccess: (created) =>
      void client.invalidateQueries({ queryKey: casesKey(session.orgSlug, created.agent_id) }),
  });
}

export function useTryChat(session: Session, agentId: string) {
  return useMutation({
    mutationFn: ({ message, chatSession }: { message: string; chatSession: string | null }) =>
      apiRequest<TryChatReply>(session, `/v1/agents/${agentId}/try-chat`, {
        method: "POST",
        body: { message, session: chatSession },
      }),
  });
}
