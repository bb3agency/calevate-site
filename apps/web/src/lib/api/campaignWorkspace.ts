"use client";

/**
 * A campaign's workspace (D-992): its main task, the sources it picked from What your agents
 * know, its own call script and Pip's draft of it, and the questions its calls could not
 * answer. `/v1/campaigns/{id}/...`.
 *
 * The campaign owns what its calls say. Start puts it live on the campaign's own engine
 * agent, in its agent's voice (D-1003); the agent's own script is never touched.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type FetchQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useRef } from "react";

import { ApiProblem, apiRequest, apiUpload, type Session } from "./client";
import { cancelDraftPath, keepLivePath } from "@/lib/scriptDraft/stream";

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

export function useCampaignWorkspace(
  session: Session,
  campaignId: string,
  enabled = true,
): UseQueryResult<CampaignWorkspace> {
  return useQuery({
    queryKey: workspaceKey(session.orgSlug, campaignId),
    queryFn: () => apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/workspace`),
    enabled,
    // Also while Pip writes the outcome of a step that has none (D-1036), so it appears.
    refetchInterval: untilRefused((query) =>
      query.state.data?.proposal?.status === "drafting" || query.state.data?.step_outcomes_pending
        ? PIP_POLL_MS
        : false,
    ),
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
    // A refusal can still have stored something ("Saved, but not on its calls yet"), so the
    // page reads the workspace again rather than keep showing what it had before.
    onError: () => {
      void client.invalidateQueries({ queryKey: workspaceKey(session.orgSlug, campaignId) });
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

/** A script to save; `proposalId` names the Pip draft it keeps, settled by the same save. */
export type CampaignScriptSave = { script: CallScript; proposalId?: string };

export function useSaveCampaignScript(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, ({ script, proposalId }: CampaignScriptSave) =>
    apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/script`, {
      method: "PUT",
      body: proposalId ? { script, proposal_id: proposalId } : { script },
    }),
  );
}

/** Put back the script from before Pip's last draft; the two swap, so it can be undone. */
export function useRestoreScriptBeforePip(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (_: void) =>
    apiRequest<CampaignWorkspace>(session, `${base(campaignId)}/script/restore-before-pip`, {
      method: "POST",
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
/** How the owner wants Pip to write it (D-1004): a part and its language for a one-part
 * rewrite, a tone, and what they typed. Empty for the whole script as Pip sees fit. */
export type ScriptAsk = Schemas["CampaignProposalIn"];

/** The longest instruction the server takes (`campaign_script_ask.INSTRUCTION_MAX`). */
export const INSTRUCTION_MAX = 2000;

export function useRequestCampaignScript(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (asked?: ScriptAsk) =>
    apiRequest<CampaignProposal>(session, `${base(campaignId)}/script/proposal`, {
      method: "POST",
      ...(asked && Object.keys(asked).length > 0 ? { body: asked } : {}),
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

/** Keep Pip's streamed draft and put it live in one step, as Save does. */
export function useKeepCampaignDraftLive(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (proposalId: string) =>
    apiRequest<CampaignWorkspace>(session, keepLivePath({ kind: "campaign", id: campaignId }, proposalId), {
      method: "POST",
    }),
  );
}

/** Stop Pip while it writes a draft; nothing half-written is saved. */
export function useCancelCampaignDraft(session: Session, campaignId: string) {
  return useWorkspaceMutation(session, campaignId, (proposalId: string) =>
    apiRequest<unknown>(session, cancelDraftPath({ kind: "campaign", id: campaignId }, proposalId), {
      method: "POST",
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

/** End a test call still ringing or connected; the list refetches to show it ended. */
export function useEndCampaignTestCall(session: Session, campaignId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (callId: string) =>
      apiRequest<void>(session, `${base(campaignId)}/test-calls/${encodeURIComponent(callId)}/end`, {
        method: "POST",
      }),
    onSettled: () => void client.invalidateQueries({ queryKey: testCallsKey(session.orgSlug, campaignId) }),
  });
}

export type CampaignSettings = Schemas["CampaignSettingsOut"];
export type CampaignSettingsInput = Schemas["CampaignSettingsValues"];
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
    // Settled, not only on success: "Saved, but not on its calls yet" is a refusal that
    // stored the change, and the language picker must show what the server now holds.
    onSettled: () => void client.invalidateQueries({ queryKey: settingsKey(session.orgSlug, campaignId) }),
  });
}

/**
 * "What it notes" (D-1028): the details a campaign's or an inbound line's calls write down.
 * The list belongs to the job, never to the agent, and both jobs read and save it the same
 * way: `GET`/`PUT .../notes`, the whole list under a compare-and-set on its digest.
 */
export type JobKind = "campaign" | "line";
export type JobNotes = Schemas["JobNotesOut"];
export type JobNotesInput = Schemas["JobNotesIn"];
// One literal family per kind, so live updates (`lib/live/topics`) can name each.
export const campaignNotesKey = (org: string, jobId: string) => ["campaign-notes", org, jobId] as const;
export const lineNotesKey = (org: string, jobId: string) => ["line-notes", org, jobId] as const;
export const jobNotesKey = (org: string, kind: JobKind, jobId: string) =>
  kind === "campaign" ? campaignNotesKey(org, jobId) : lineNotesKey(org, jobId);

/**
 * The title the api gives an edit to a job's list (or a campaign's script or settings) it kept
 * while the put-live after it was refused (`campaigns/notes_live.kept_not_live`). The retry is
 * the same Save pressed again: an unchanged save puts a job that holds calls live again.
 */
export const SAVED_NOT_ON_CALLS_TITLE = "Saved, but not on its calls yet";

export function isSavedNotOnCalls(error: unknown): error is ApiProblem {
  return error instanceof ApiProblem && error.title === SAVED_NOT_ON_CALLS_TITLE;
}

export function jobNotesPath(kind: JobKind, jobId: string): string {
  return kind === "campaign" ? `${base(jobId)}/notes` : `/v1/inbound-lines/${encodeURIComponent(jobId)}/notes`;
}

function jobNotesQuery(
  session: Session,
  kind: JobKind,
  jobId: string,
): FetchQueryOptions<JobNotes, Error, JobNotes, readonly string[]> {
  const queryFn = () => apiRequest<JobNotes>(session, jobNotesPath(kind, jobId));
  return kind === "campaign"
    ? { queryKey: campaignNotesKey(session.orgSlug, jobId), queryFn }
    : { queryKey: lineNotesKey(session.orgSlug, jobId), queryFn };
}

export function useJobNotes(session: Session, kind: JobKind, jobId: string) {
  return useQuery(jobNotesQuery(session, kind, jobId));
}

export function useSaveJobNotes(session: Session, kind: JobKind, jobId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: JobNotesInput) =>
      apiRequest<JobNotes>(session, jobNotesPath(kind, jobId), { method: "PUT", body: input }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: jobNotesKey(session.orgSlug, kind, jobId) }),
        // Lead details lists every job with its digest and whether anybody chose its list.
        client.invalidateQueries({ queryKey: ["lead-fields", session.orgSlug] }),
      ]),
  });
}

/** Another job's list, read once when the owner imports it into the editor. */
export function useFetchJobNotes(session: Session, kind: JobKind) {
  const client = useQueryClient();
  return (jobId: string) => client.fetchQuery(jobNotesQuery(session, kind, jobId));
}

/** An Excel sheet's first tab as CSV text, read on the server; nothing is stored. */
export function contactsFromExcel(session: Session, file: File) {
  const form = new FormData();
  form.set("file", file);
  return apiUpload<Schemas["ContactSheetOut"]>(session, "/v1/campaigns/contacts/from-excel", form);
}
