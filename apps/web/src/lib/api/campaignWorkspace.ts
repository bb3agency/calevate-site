"use client";

/**
 * A campaign's workspace (D-992): its main task, the sources it picked from What your agents
 * know, its own call script and Pip's draft of it, and the questions its calls could not
 * answer. `/v1/campaigns/{id}/...`.
 *
 * The campaign owns what its calls say. Start puts only the script live on the campaign's
 * agent, which is the voice; everything else stays here.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useRef } from "react";

import { apiRequest, apiUpload, type Session } from "./client";
import { invalidateKnowledgeLists } from "./kb";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";
import type { CallScript } from "./script";

type Schemas = components["schemas"];
export type CampaignProposal = Omit<Schemas["CampaignProposalOut"], "script" | "base_script"> & {
  script: CallScript | null;
  base_script: CallScript | null;
};
export type CampaignWorkspace = Omit<Schemas["WorkspaceOut"], "script" | "proposal"> & {
  script: CallScript | null;
  proposal: CampaignProposal | null;
};
export type CampaignQuestion = Schemas["CampaignQuestionOut"];

/** While Pip writes, the page asks every 5 seconds (global rule 3: live status, 5-10 s). */
export const PIP_POLL_MS = 5_000;

export const workspaceKey = (org: string, campaignId: string) => ["campaign-workspace", org, campaignId] as const;
export const questionsKey = (org: string, campaignId: string) => ["campaign-questions", org, campaignId] as const;

const base = (campaignId: string) => `/v1/campaigns/${encodeURIComponent(campaignId)}`;

export function useCampaignWorkspace(session: Session, campaignId: string): UseQueryResult<CampaignWorkspace> {
  return useQuery({
    queryKey: workspaceKey(session.orgSlug, campaignId),
    queryFn: () => apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/workspace`),
    refetchInterval: untilRefused((query) => (query.state.data?.proposal?.status === "drafting" ? PIP_POLL_MS : false)),
  });
}

function useWorkspaceMutation<TIn>(
  session: Session,
  campaignId: string,
  call: (input: TIn) => Promise<CampaignWorkspace | unknown>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (out) => {
      if (out && typeof out === "object" && "campaign_id" in out) {
        client.setQueryData(workspaceKey(session.orgSlug, campaignId), out);
      } else {
        void client.invalidateQueries({ queryKey: workspaceKey(session.orgSlug, campaignId) });
      }
    },
  });
}

export function useSaveMainTask(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (main_task: string) =>
    apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/main-task`, {
      method: "PUT",
      body: { main_task },
    }),
  );
}

export function useSaveCampaignScript(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (script: CallScript) =>
    apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/script`, {
      method: "PUT",
      body: { script },
    }),
  );
}

/** The sources from What your agents know that Pip writes the campaign from. */
export function useSetCampaignSources(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (sourceIds: string[]) =>
    apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/sources`, {
      method: "PUT",
      body: { source_ids: sourceIds },
    }),
  );
}

/** What "Add a file or note" adds: it goes into What your agents know and is picked. */
export type NewCampaignSource =
  | { kind: "file"; file: File }
  | { kind: "link"; url: string; name?: string }
  | { kind: "note"; note: string; title?: string };

function addSource(session: Session, campaignId: string, item: NewCampaignSource): Promise<CampaignWorkspace> {
  if (item.kind === "file") {
    const form = new FormData();
    form.set("file", item.file);
    return apiUpload<CampaignWorkspace>(session, `${base(campaignId)}/sources/upload`, form);
  }
  if (item.kind === "link") {
    return apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/sources/link`, {
      method: "POST",
      body: { url: item.url, ...(item.name ? { name: item.name } : {}) },
    });
  }
  return apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/sources/note`, {
    method: "POST",
    body: { note: item.note, ...(item.title ? { title: item.title } : {}) },
  });
}

export function useAddCampaignSource(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (item: NewCampaignSource) => addSource(session, campaignId, item),
    onSuccess: (out) => {
      client.setQueryData(workspaceKey(session.orgSlug, campaignId), out);
      // The new item is in What your agents know now, so the pick list shows it.
      invalidateKnowledgeLists(client, session);
    },
  });
}

/** The whole script, or with `part` and `language` that one part rewritten in that language. */
export function useRequestCampaignScript(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (only?: { part: string; language: string }) =>
    apiRequest<CampaignProposal>(session, `${base(campaignId)}/script/proposal`, {
      method: "POST",
      ...(only ? { body: only } : {}),
    }),
  );
}

/** Stop Pip while it writes, or discard / settle a written draft. */
export function useClearCampaignProposal(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (proposalId: string) =>
    apiRequest<void>(session, `${base(campaignId)}/script/proposal/${encodeURIComponent(proposalId)}`, {
      method: "DELETE",
    }),
  );
}

export function useCampaignQuestions(session: Session, campaignId: string, enabled = true) {
  return useQuery({
    queryKey: questionsKey(session.orgSlug, campaignId),
    queryFn: () => apiRequest<CampaignQuestion[]>(session, `${base(campaignId)}/questions`),
    enabled,
  });
}

/** The answer goes into What your agents know as a note, and the campaign picks it. */
export function useAnswerQuestion(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (answer: { topic: string; answer: string }) =>
      apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/questions/answer`, {
        method: "POST",
        body: answer,
      }),
    onSuccess: (out) => {
      client.setQueryData(workspaceKey(session.orgSlug, campaignId), out);
      void client.invalidateQueries({ queryKey: questionsKey(session.orgSlug, campaignId) });
      invalidateKnowledgeLists(client, session);
    },
  });
}

export type CampaignInsights = Schemas["CampaignInsightsOut"];
export const insightsKey = (org: string, campaignId: string) => ["campaign-insights", org, campaignId] as const;

export function useCampaignInsights(session: Session, campaignId: string) {
  return useQuery({
    queryKey: insightsKey(session.orgSlug, campaignId),
    queryFn: () => apiRequest<CampaignInsights>(session, `${base(campaignId)}/insights`),
  });
}

/** Test a second opening line against the script's own; null stops the test. */
export function useSaveOpeningB(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (opening_b: string | null) =>
      apiRequest<void>(session, `${base(campaignId)}/opening-b`, { method: "PUT", body: { opening_b } }),
    onSuccess: () => void client.invalidateQueries({ queryKey: insightsKey(session.orgSlug, campaignId) }),
  });
}

/**
 * Put the campaign's script on its agent and ring the owner's phone. One Idempotency-Key per
 * attempt, held until an answer, so a second press after a lost response rings nobody twice.
 */
export function useCampaignTestCall(session: Session, campaignId: string) {
  const held = useRef(new Map<string, string>());
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ number, numberIsMine }: { number: string; numberIsMine: boolean }) => {
      const key = held.current.get(number) ?? crypto.randomUUID();
      held.current.set(number, key);
      return apiRequest<Schemas["CampaignTestCallOut"]>(session, `${base(campaignId)}/test-call`, {
        method: "POST",
        body: { number, number_is_mine: numberIsMine },
        idempotencyKey: key,
      });
    },
    onSuccess: (_out, { number }) => {
      held.current.delete(number);
      void client.invalidateQueries({ queryKey: workspaceKey(session.orgSlug, campaignId) });
      void client.invalidateQueries({ queryKey: testCallsKey(session.orgSlug, campaignId) });
      void client.invalidateQueries({ queryKey: testNumbersKey(session.orgSlug) });
    },
  });
}

/** The account's saved test numbers: one list for every campaign, so keyed by account. */
const testNumbersKey = (org: string) => ["test-numbers", org];

export function useTestNumbers(session: Session, campaignId: string) {
  return useQuery({
    queryKey: testNumbersKey(session.orgSlug),
    queryFn: () => apiRequest<Schemas["TestNumbersOut"]>(session, `${base(campaignId)}/test-numbers`),
  });
}

export function useSaveTestNumbers(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (numbers: string[]) =>
      apiRequest<Schemas["TestNumbersOut"]>(session, `${base(campaignId)}/test-numbers`, {
        method: "PUT",
        body: { numbers },
      }),
    onSuccess: (out) => client.setQueryData(testNumbersKey(session.orgSlug), out),
  });
}

export type CampaignTestCallItem = Schemas["CampaignTestCallItem"];
const testCallsKey = (org: string, campaignId: string) => ["campaign-test-calls", org, campaignId];

/** The test calls this campaign placed. Re-read every 10 s while one is still in progress. */
const LIVE_STATUSES = new Set(["queued", "ringing", "in_progress"]);
/** A call still going, or finished in the last ten minutes with its recording not yet copied. */
function stillComing(call: CampaignTestCallItem): boolean {
  if (LIVE_STATUSES.has(call.status)) return true;
  const recent = Date.now() - new Date(call.placed_at).getTime() < 10 * 60_000;
  return call.status === "completed" && !call.has_recording && recent;
}

export function useCampaignTestCalls(session: Session, campaignId: string) {
  return useQuery({
    queryKey: testCallsKey(session.orgSlug, campaignId),
    queryFn: () => apiRequest<CampaignTestCallItem[]>(session, `${base(campaignId)}/test-calls`),
    refetchInterval: untilRefused((query: { state: { data?: CampaignTestCallItem[] } }) =>
      (query.state.data ?? []).some(stillComing) ? 10_000 : false,
    ),
  });
}

export function useRemoveCampaignTestCall(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (callId: string) =>
      apiRequest<void>(session, `${base(campaignId)}/test-calls/${encodeURIComponent(callId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: testCallsKey(session.orgSlug, campaignId) }),
  });
}

export type CampaignSettings = Schemas["CampaignSettingsOut"];
export type CampaignSettingsValues = Schemas["CampaignSettingsValues-Output"];
export type CampaignSettingsInput = Schemas["CampaignSettingsValues-Input"];
export const settingsKey = (org: string, campaignId: string) => ["campaign-settings", org, campaignId] as const;

/** The agent's defaults and this campaign's own settings over them (D-994). */
export function useCampaignSettings(session: Session, campaignId: string, agentId: string) {
  return useQuery({
    queryKey: [...settingsKey(session.orgSlug, campaignId), agentId],
    queryFn: () => apiRequest<CampaignSettings>(session, `${base(campaignId)}/settings`),
  });
}

export function useSaveCampaignSettings(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (overrides: CampaignSettingsInput) =>
      apiRequest<CampaignSettings>(session, `${base(campaignId)}/settings`, { method: "PUT", body: overrides }),
    onSuccess: () => void client.invalidateQueries({ queryKey: settingsKey(session.orgSlug, campaignId) }),
  });
}

/** The campaign whose script and settings an agent carries now, if any. */
export function useAgentHolder(session: Session, agentId: string) {
  return useQuery({
    queryKey: ["agent-holder", session.orgSlug, agentId],
    queryFn: () =>
      apiRequest<Schemas["AgentHolderOut"]>(session, `/v1/campaigns/agents/${encodeURIComponent(agentId)}/holder`),
  });
}

/** An Excel sheet's first tab as CSV text, read on the server; nothing is stored. */
export function contactsFromExcel(session: Session, file: File) {
  const form = new FormData();
  form.set("file", file);
  return apiUpload<Schemas["ContactSheetOut"]>(session, "/v1/campaigns/contacts/from-excel", form);
}
