"use client";

/**
 * A campaign's workspace (D-992): its main task, materials, its own call script and Pip's
 * draft of it, and the questions its calls could not answer. `/v1/campaigns/{id}/...`.
 *
 * The campaign owns what its calls say. Start puts only the script live on the campaign's
 * agent, which is the voice; everything else stays here.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useRef } from "react";

import { apiRequest, apiUpload, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";
import type { CallScript } from "./script";

type Schemas = components["schemas"];
export type CampaignMaterial = Schemas["MaterialOut"];
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

export type MaterialIn = Schemas["MaterialIn"];

export function useAddMaterial(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (material: MaterialIn) =>
    apiRequest<CampaignMaterial>(session, `${base(campaignId)}/materials`, {
      method: "POST",
      body: material,
    }),
  );
}

export function useArchiveMaterial(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (materialId: string) =>
    apiRequest<void>(session, `${base(campaignId)}/materials/${encodeURIComponent(materialId)}/archive`, {
      method: "POST",
    }),
  );
}

export function useRequestCampaignScript(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, () =>
    apiRequest<CampaignProposal>(session, `${base(campaignId)}/script/proposal`, { method: "POST" }),
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

export function useAnswerQuestion(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (answer: { topic: string; answer: string }) =>
      apiRequest<CampaignMaterial>(session, `${base(campaignId)}/questions/answer`, {
        method: "POST",
        body: answer,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: workspaceKey(session.orgSlug, campaignId) });
      void client.invalidateQueries({ queryKey: questionsKey(session.orgSlug, campaignId) });
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
    },
  });
}

/** Upload a file for a campaign: into the knowledge, or the copy already there reused. */
export function uploadMaterial(session: Session, campaignId: string, file: File, title?: string) {
  const form = new FormData();
  form.set("file", file);
  if (title) form.set("title", title);
  return apiUpload<CampaignMaterial>(session, `${base(campaignId)}/materials/upload`, form);
}

export function useUploadMaterial(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, ({ file, title }: { file: File; title?: string }) =>
    uploadMaterial(session, campaignId, file, title),
  );
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
