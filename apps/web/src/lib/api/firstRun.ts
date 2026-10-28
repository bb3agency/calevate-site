"use client";

/**
 * "Meet your agent", a new owner's first run (D-855, D-863): `/v1/first-run/**`.
 *
 * The server holds where the owner is (the jobs, the brief, the questions a worker wrote, the
 * build's steps), so a reload or another device lands on the same step. Two things are
 * worked on in the background and polled while they are: the follow-up questions
 * (`questions.status === "writing"`) and the build (`build.status === "building"`); a
 * spoken piece of the brief is polled on its own row until it is heard.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { agentKeys } from "./agents";
import { businessProfileKeys } from "./businessProfile";
import { apiRequest, apiUpload, type Session, type UploadProgress } from "./client";
import type { KbUpload } from "./kb";
import type { components } from "./schema";
import { knowsKey } from "./teach";

type Schemas = components["schemas"];

export type FirstRun = Schemas["FirstRunOut"];
export type FirstRunQuestion = Schemas["QuestionOut"];
export type FirstRunBuildStep = Schemas["BuildStepOut"];
export type FirstRunRecording = Schemas["RecordingOut"];
export type FirstRunAnswers = Schemas["AnswersIn"];
export type FirstRunAnswer = Schemas["AnswerIn"];
/** A file added on the brief step: an ordinary knowledge upload (D-918). */
export type FirstRunDocument = Schemas["DocumentOut"];
/** One agent does every job picked (D-863). */
export type FirstRunJob = FirstRun["jobs"][number];

export const FIRST_RUN_PATH = "/v1/first-run";

/** How often a background step is asked about. The build's four steps land within seconds
 *  of each other, so a slower poll would show them arriving in a lump. */
const POLL_MS = 1_200;

export function firstRunKey(slug: string) {
  return ["first-run", slug] as const;
}

export function isFirstRunBusy(run: FirstRun | undefined): boolean {
  return (
    run?.questions.status === "writing" ||
    run?.build.status === "building" ||
    (run?.documents ?? []).some((document) => document.state === "reading")
  );
}

export function useFirstRun(session: Session, enabled = true): UseQueryResult<FirstRun> {
  return useQuery({
    queryKey: firstRunKey(session.orgSlug),
    queryFn: () => apiRequest<FirstRun>(session, FIRST_RUN_PATH),
    enabled,
    refetchInterval: (query) => (isFirstRunBusy(query.state.data) ? POLL_MS : false),
  });
}

/** Every write answers with the whole first run, which replaces the cached one. */
function useFirstRunWrite<Body>(
  session: Session,
  path: string,
  method: "PUT" | "POST",
  after?: () => void,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Body) =>
      apiRequest<FirstRun>(session, `${FIRST_RUN_PATH}${path}`, { method, body: body ?? undefined }),
    onSuccess: (next) => {
      client.setQueryData(firstRunKey(session.orgSlug), next);
      after?.();
    },
  });
}

export function useSaveJob(session: Session) {
  return useFirstRunWrite<{ jobs: FirstRunJob[]; language_primary: string; languages_extra: string[] }>(
    session,
    "/job",
    "PUT",
  );
}

export function useSaveBrief(session: Session) {
  return useFirstRunWrite<{ brief: string }>(session, "/brief", "PUT");
}

export function useSaveAnswers(session: Session) {
  const client = useQueryClient();
  return useFirstRunWrite<FirstRunAnswers>(session, "/answers", "POST", () => {
    void client.invalidateQueries({ queryKey: businessProfileKeys.mine(session.orgSlug) });
  });
}

export function useBuildAgent(session: Session) {
  const client = useQueryClient();
  return useFirstRunWrite<null>(session, "/build", "POST", () => {
    void client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) });
  });
}

export function useRenameAgent(session: Session) {
  const client = useQueryClient();
  return useFirstRunWrite<{ name: string }>(session, "/name", "PUT", () => {
    void client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) });
    // The agent's own page caches its name under the detail key, a different family.
    void client.invalidateQueries({ queryKey: agentKeys.allDetails(session.orgSlug) });
  });
}

export function useFinishFirstRun(session: Session) {
  return useFirstRunWrite<null>(session, "/finish", "POST");
}

export function useDismissFirstRun(session: Session) {
  return useFirstRunWrite<null>(session, "/dismiss", "POST");
}

/** The knowledge reads a new upload changes (`kb.ts`'s own invalidation, for the two it
 *  shares with this screen). */
function invalidateKnowledge(client: ReturnType<typeof useQueryClient>, session: Session): void {
  void client.invalidateQueries({ queryKey: ["kb-uploads", session.orgSlug] });
  void client.invalidateQueries({ queryKey: knowsKey(session.orgSlug) });
}

/**
 * Add one file beside the brief (D-918). The file goes through the knowledge upload
 * (`POST /v1/kb/uploads`), so it is read, reviewed and metered like any upload and every
 * agent uses it; then the first run records it as one of its documents.
 */
export function useAddDocument(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, onProgress }: { file: File; onProgress?: (progress: UploadProgress) => void }) => {
      const form = new FormData();
      form.set("file", file);
      const upload = await apiUpload<KbUpload>(session, "/v1/kb/uploads", form, { onProgress });
      return apiRequest<FirstRun>(session, `${FIRST_RUN_PATH}/documents`, {
        method: "POST",
        body: { upload_id: upload.id },
      });
    },
    onSuccess: (next) => client.setQueryData(firstRunKey(session.orgSlug), next),
    // On a refused link too: the upload itself may have landed in the knowledge base.
    onSettled: () => invalidateKnowledge(client, session),
  });
}

/** Stop using one file for the brief. It stays in the knowledge base. */
export function useRemoveDocument(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (uploadId: string) =>
      apiRequest<FirstRun>(session, `${FIRST_RUN_PATH}/documents/${uploadId}`, { method: "DELETE" }),
    onSuccess: (next) => client.setQueryData(firstRunKey(session.orgSlug), next),
  });
}

/** Upload one spoken piece of the brief; the worker hears it and deletes the audio. */
export function useRecordBrief(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ audio, language }: { audio: Blob; language: string }) => {
      const form = new FormData();
      const extension = audio.type.includes("mp4") ? "m4a" : "webm";
      form.append("file", audio, `brief.${extension}`);
      form.append("language", language);
      return apiUpload<FirstRunRecording>(session, `${FIRST_RUN_PATH}/recordings`, form);
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: firstRunKey(session.orgSlug) }),
  });
}

export function isRecordingBusy(status: string | undefined): boolean {
  return status === "queued" || status === "hearing";
}

export function useRecording(session: Session, id: string | null): UseQueryResult<FirstRunRecording> {
  return useQuery({
    queryKey: ["first-run-recording", session.orgSlug, id],
    queryFn: () => apiRequest<FirstRunRecording>(session, `${FIRST_RUN_PATH}/recordings/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => (isRecordingBusy(query.state.data?.status) ? POLL_MS : false),
  });
}
