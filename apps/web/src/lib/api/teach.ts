"use client";

/**
 * Teaching the agents and the improvement loop (`apps/api/teach/`).
 *
 * The teach box: Pip is asked to teach (D-821) and a worker sorts what it sends; the screen
 * polls the open teaching until it is `ready` for review. A voice note is heard here and its
 * words go back into the teach box. Saving puts facts into the business's knowledge at once
 * and rules into the chosen agent's script as waiting rules.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, apiUpload, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Knows = Schemas["KnowsOut"];
export type PinnedNotYetOn = Schemas["PinnedNotYetOut"];
export type Fact = Schemas["FactOut"];
export type KnownItem = Schemas["KnownItemOut"];
export type Teaching = Schemas["TeachingOut"];
export type TeachItem = Schemas["TeachItemIO"];
export type ProposedRule = Schemas["RuleOut"];
export type TestCase = Schemas["TestCaseOut"];
export type TestCases = Schemas["TestCasesOut"];
export type CaseDraft = Schemas["CaseDraftOut"];
export type TryChatReply = Schemas["TryChatOut"];



export const knowsKey = (slug: string) => ["kb-knows", slug] as const;
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
    // and "Being added to …" turn into nothing without a reload.
    refetchInterval: (query) => {
      const data = query.state.data;
      const arriving =
        data?.facts_state === "publishing" ||
        (data?.pinned_not_yet_on ?? []).some((entry) => entry.reason === "on_the_way");
      return arriving ? 15_000 : false;
    },
  });
}

export type KnownFacts = Schemas["KnownFactsOut"];

/**
 * What one agent knows by heart and what it looks up (D-896). Under the `kb-knows` prefix,
 * so every fact mutation that refreshes "what it knows" refreshes this too; the choice
 * itself is made by a worker, so a fresh read may still show the previous one for a minute.
 */
export const knownFactsKey = (slug: string, agentId: string) =>
  [...knowsKey(slug), "agent", agentId] as const;

export function useKnownFacts(session: Session, agentId: string): UseQueryResult<KnownFacts> {
  return useQuery({
    queryKey: knownFactsKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<KnownFacts>(session, `/v1/agents/${agentId}/known-facts`),
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

/**
 * Hear a voice note for the teach box. The teaching stops at `heard`; the screen takes its
 * words into the teach box and discards it, and Pip sorts what the owner sends (D-821).
 */
export function useHearVoiceNote(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ file }: { file: Blob }): Promise<Teaching> => {
      const form = new FormData();
      form.append("file", file, "voice-note.webm");
      form.append("kind", "voice");
      return apiUpload<Teaching>(session, "/v1/kb/teach/upload", form);
    },
    onSuccess: (teaching) =>
      client.setQueryData(teachingKey(session.orgSlug, teaching.id), teaching),
  });
}

const openTeachingKey = (slug: string) => ["kb-teaching-open", slug] as const;

/**
 * What this person asked Pip to teach that is being sorted or waits for review (D-821).
 * Polls while it is sorted; Pip's confirmation refreshes every query, so a new one appears.
 */
export function useOpenTeaching(session: Session): UseQueryResult<Teaching | null> {
  return useQuery({
    queryKey: openTeachingKey(session.orgSlug),
    queryFn: async () =>
      (await apiRequest<{ teaching: Teaching | null }>(session, "/v1/kb/teach/open")).teaching,
    refetchInterval: (query) => (isTeachingBusy(query.state.data?.status) ? 1_500 : false),
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
      void client.invalidateQueries({ queryKey: ["teach-questions", session.orgSlug] });
      void client.invalidateQueries({ queryKey: openTeachingKey(session.orgSlug) });
    },
  });
}

export function useDiscardTeaching(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest<Teaching>(session, `/v1/kb/teach/${id}/discard`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: openTeachingKey(session.orgSlug) }),
  });
}

/**
 * A fact added, changed or removed can answer (or reopen) a question practice callers or
 * setup were waiting on, and moves the practice run's "Add your prices first" note.
 */
function afterFactChange(client: QueryClient, slug: string): void {
  for (const family of ["kb-knows", "teach-questions", "script-tests"]) {
    void client.invalidateQueries({ queryKey: [family, slug] });
  }
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
    onSuccess: () => afterFactChange(client, session.orgSlug),
  });
}

export function useAddFact(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; question: string | null; pinned: boolean }) =>
      apiRequest<Fact>(session, "/v1/kb/facts", { method: "POST", body }),
    onSuccess: () => afterFactChange(client, session.orgSlug),
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
    onSuccess: () => afterFactChange(client, session.orgSlug),
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

/** Save a test written by hand: what the caller says, and what the agent should do. */
export function useCreateTestCase(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; caller_lines: string[]; expected: string }) =>
      apiRequest<TestCase>(session, `/v1/agents/${agentId}/test-cases`, { method: "POST", body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: casesKey(session.orgSlug, agentId) }),
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

const caseDraftKey = (orgSlug: string, callId: string) => ["call-test-case-draft", orgSlug, callId];

/** The call's caller lines (redacted) and, when Pip prepared one, the test it left (D-822). */
export function useCaseDraft(session: Session, callId: string, enabled: boolean) {
  return useQuery({
    queryKey: caseDraftKey(session.orgSlug, callId),
    queryFn: () => apiRequest<CaseDraft>(session, `/v1/calls/${callId}/test-case-draft`),
    enabled,
  });
}

export function useMakeCallATest(session: Session, callId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; caller_lines: string[]; expected: string }) =>
      apiRequest<TestCase>(session, `/v1/calls/${callId}/test-case`, { method: "POST", body }),
    onSuccess: (created) => {
      void client.invalidateQueries({ queryKey: casesKey(session.orgSlug, created.agent_id) });
      // Saving closes what Pip prepared, so the form gives way to the button again.
      void client.invalidateQueries({ queryKey: caseDraftKey(session.orgSlug, callId) });
    },
  });
}

export function useDiscardPreparedTest(session: Session, callId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<void>(session, `/v1/calls/${callId}/test-case-draft/pending`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: caseDraftKey(session.orgSlug, callId) }),
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
