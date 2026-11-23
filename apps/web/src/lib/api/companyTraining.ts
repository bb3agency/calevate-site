"use client";

/**
 * How they speak (D-996), the company training: the one training every agent of the account is
 * given ahead of its own script, the owner's overview it is written from, and Pip's background
 * write of it (D-1034). A tab of What your agents know. `/v1/company-training`.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { PIP_POLL_MS } from "./campaignWorkspace";
import { apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type CompanyTraining = Schemas["CompanyTrainingOut"];
export type TrainingProposal = Schemas["TrainingProposalOut"];
export type WriteReason = TrainingProposal["reasons"][number];

const BASE = "/v1/company-training";
/** A queued write waits for changes to settle (about a minute), so it is checked less often. */
const QUEUED_POLL_MS = 15_000;

export const trainingKey = (org: string) => ["company-training", org] as const;

export function useCompanyTraining(session: Session): UseQueryResult<CompanyTraining> {
  return useQuery({
    queryKey: trainingKey(session.orgSlug),
    queryFn: () => apiRequest<CompanyTraining>(session, BASE),
    refetchInterval: untilRefused((query) => {
      const status = query.state.data?.proposal?.status;
      return status === "drafting" ? PIP_POLL_MS : status === "queued" ? QUEUED_POLL_MS : false;
    }),
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

/** The owner's edit of the training; Pip's next rewrite keeps it. */
export function useSaveTraining(session: Session) {
  return useTrainingMutation(session, (input: { training: string }) =>
    apiRequest<CompanyTraining>(session, `${BASE}/training`, { method: "PUT", body: input }),
  );
}

/** Rewrite now: Pip's background write, started without waiting. */
export function useRequestTraining(session: Session) {
  return useTrainingMutation(session, () =>
    apiRequest<TrainingProposal>(session, `${BASE}/proposal`, { method: "POST" }),
  );
}

/** Dismiss a write that failed. */
export function useClearTrainingProposal(session: Session) {
  return useTrainingMutation(session, (proposalId: string) =>
    apiRequest<void>(session, `${BASE}/proposal/${encodeURIComponent(proposalId)}`, { method: "DELETE" }),
  );
}
