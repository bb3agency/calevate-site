"use client";

/**
 * The company training (founder, 16 Nov 2026): the one training every agent of the account is
 * given ahead of its own script, the owner's overview and materials it is written from, and
 * Pip's draft of it. `/v1/company-training`.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { PIP_POLL_MS } from "./campaignWorkspace";
import { apiRequest, apiUpload, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type CompanyTraining = Schemas["CompanyTrainingOut"];
export type TrainingMaterial = Schemas["TrainingMaterialOut"];
export type TrainingMaterialIn = Schemas["TrainingMaterialIn"];
export type TrainingProposal = Schemas["TrainingProposalOut"];

const BASE = "/v1/company-training";

export const trainingKey = (org: string) => ["company-training", org] as const;

export function useCompanyTraining(session: Session): UseQueryResult<CompanyTraining> {
  return useQuery({
    queryKey: trainingKey(session.orgSlug),
    queryFn: () => apiRequest<CompanyTraining>(session, BASE),
    refetchInterval: untilRefused((query) => (query.state.data?.proposal?.status === "drafting" ? PIP_POLL_MS : false)),
  });
}

function useTrainingMutation<TIn>(session: Session, call: (input: TIn) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (out) => {
      if (out && typeof out === "object" && "training_max" in out) {
        client.setQueryData(trainingKey(session.orgSlug), out);
      } else {
        void client.invalidateQueries({ queryKey: trainingKey(session.orgSlug) });
      }
    },
  });
}

export function useSaveOverview(session: Session) {
  return useTrainingMutation(session, (overview: string) =>
    apiRequest<CompanyTraining>(session, `${BASE}/overview`, { method: "PUT", body: { overview } }),
  );
}

/** Save the training every agent is given; `proposal_id` settles the Pip draft it keeps. */
export function useSaveTraining(session: Session) {
  return useTrainingMutation(session, (input: { training: string; proposal_id?: string }) =>
    apiRequest<CompanyTraining>(session, `${BASE}/training`, { method: "PUT", body: input }),
  );
}

export function useAddTrainingMaterial(session: Session) {
  return useTrainingMutation(session, (material: TrainingMaterialIn) =>
    apiRequest<TrainingMaterial>(session, `${BASE}/materials`, { method: "POST", body: material }),
  );
}

/** Upload a file for the training: into the knowledge, or the copy already there reused. */
export function useUploadTrainingMaterial(session: Session) {
  return useTrainingMutation(session, ({ file, title }: { file: File; title?: string }) => {
    const form = new FormData();
    form.set("file", file);
    if (title) form.set("title", title);
    return apiUpload<TrainingMaterial>(session, `${BASE}/materials/upload`, form);
  });
}

export function useArchiveTrainingMaterial(session: Session) {
  return useTrainingMutation(session, (materialId: string) =>
    apiRequest<void>(session, `${BASE}/materials/${encodeURIComponent(materialId)}/archive`, { method: "POST" }),
  );
}

export function useRequestTraining(session: Session) {
  return useTrainingMutation(session, () =>
    apiRequest<TrainingProposal>(session, `${BASE}/proposal`, { method: "POST" }),
  );
}

/** Stop Pip while it writes, or discard a written draft. */
export function useClearTrainingProposal(session: Session) {
  return useTrainingMutation(session, (proposalId: string) =>
    apiRequest<void>(session, `${BASE}/proposal/${encodeURIComponent(proposalId)}`, { method: "DELETE" }),
  );
}
