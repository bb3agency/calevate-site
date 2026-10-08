"use client";

/**
 * THE VOICES A HOSTING VOICE PLATFORM SPEAKS, AS CURATED HERE (D-687) — admin realm,
 * `ops:manage`.
 *
 *   GET    /v1/ops/voices/hosted?scope=added|all   the hosted voices; `available:false` on
 *                                                   an engine whose voices are our catalogue
 *   POST   /v1/ops/voices/hosted                   add one synced voice (arrives disabled)
 *   PATCH  /v1/ops/voices/hosted                   enable | disable | archive one
 *   POST   /v1/ops/voices/clones                   clone from a recording (step-up)
 *   DELETE /v1/ops/voices/clones                   delete one of our clones (step-up)
 *   POST   /v1/ops/voices/hosted/preview           upload a preview clip
 *   POST   /v1/ops/voices/hosted/preview/fetch     store the platform's own preview
 *   GET    /v1/ops/voices/studio-workspace         the Studio workspace and its voice key
 *   POST   /v1/ops/voices/studio-workspace         set it up (step-up)
 *
 * The Voices page reads the hosted list FIRST and branches on `available`: the Pipecat
 * catalogue (`opsVoices.ts`) is what an engine that does not host voices is curated with,
 * and the server, not this bundle, says which engine this is.
 *
 * Every write invalidates the client-realm engine catalogue too: enabling a voice here
 * changes what every client's picker offers.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, apiUpload } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type HostedVoice = Schemas["HostedVoiceOut"];
export type HostedVoices = Schemas["HostedVoicesOut"];
export type HostedScope = HostedVoices["scope"];
export type HostedState = HostedVoice["state"];
export type HostedVoiceWrite = Schemas["HostedVoiceWriteOut"];
export type CloneOut = Schemas["CloneOut"];
export type DeleteCloneOut = Schemas["DeleteCloneOut"];
export type StudioWorkspace = Schemas["StudioWorkspaceOut"];
export type StudioSetupIn = Schemas["StudioSetupIn"];
export type FetchPreviewIn = Schemas["FetchPreviewIn"];

export const OPS_HOSTED_PATH = "/v1/ops/voices/hosted";
export const OPS_CLONES_PATH = "/v1/ops/voices/clones";
export const OPS_PREVIEW_UPLOAD_PATH = "/v1/ops/voices/hosted/preview";
export const OPS_PREVIEW_FETCH_PATH = "/v1/ops/voices/hosted/preview/fetch";
export const OPS_STUDIO_WORKSPACE_PATH = "/v1/ops/voices/studio-workspace";

/** The confirmations the API names for its step-up writes. */
export const CLONE_CONFIRMATION = "clone_voice";
export const STUDIO_SETUP_CONFIRMATION = "setup_studio_workspace";
export const deleteCloneConfirmation = (voiceId: string) => `delete_voice_clone:${voiceId}`;

/** The size the clone and preview routes accept (the API's own request limit). */
export const MAX_SAMPLE_BYTES = 2 * 1024 * 1024;

/** Global, not org-scoped: one vendor account serves every tenant. */
export const hostedVoiceKeys = {
  all: ["admin", "ops", "voices", "hosted"] as const,
  scoped: (scope: HostedScope) => ["admin", "ops", "voices", "hosted", scope] as const,
  studio: ["admin", "ops", "voices", "studio-workspace"] as const,
};

export function useHostedVoices(
  enabled: boolean,
  scope: HostedScope = "added",
): UseQueryResult<HostedVoices> {
  return useQuery({
    queryKey: hostedVoiceKeys.scoped(scope),
    queryFn: () => apiRequest<HostedVoices>(adminSession(), `${OPS_HOSTED_PATH}?scope=${scope}`),
    enabled,
  });
}

export function useStudioWorkspace(enabled: boolean): UseQueryResult<StudioWorkspace> {
  return useQuery({
    queryKey: hostedVoiceKeys.studio,
    queryFn: () => apiRequest<StudioWorkspace>(adminSession(), OPS_STUDIO_WORKSPACE_PATH),
    enabled,
  });
}

/** After any write: the admin lists, every picker's engine catalogue, and stored previews. */
function useInvalidateVoices() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: hostedVoiceKeys.all }),
      client.invalidateQueries({ queryKey: ["engine-catalogue"] }),
    ]);
}

export function useAddHostedVoice(): UseMutationResult<HostedVoiceWrite, Error, string> {
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (voiceId: string) =>
      apiRequest<HostedVoiceWrite>(adminSession(), OPS_HOSTED_PATH, {
        method: "POST",
        body: { voice_id: voiceId },
      }),
    onSuccess: invalidate,
  });
}

export function useSetHostedState(): UseMutationResult<
  HostedVoiceWrite,
  Error,
  { voice_id: string; state: HostedState }
> {
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<HostedVoiceWrite>(adminSession(), OPS_HOSTED_PATH, { method: "PATCH", body }),
    onSuccess: invalidate,
  });
}

/** What the clone form sends. The two consents are the operator's own attestations. */
export interface CloneVoiceInput {
  sample: File;
  name: string;
  description: string;
  language: string;
  removeNoise: boolean;
  consentOwnVoice: boolean;
  consentNoImpersonation: boolean;
}

export function useCloneVoice(): UseMutationResult<CloneOut, Error, CloneVoiceInput> {
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (input: CloneVoiceInput) => {
      const form = new FormData();
      form.set("sample", input.sample);
      form.set("name", input.name);
      if (input.description) form.set("description", input.description);
      if (input.language) form.set("language", input.language);
      form.set("remove_noise", String(input.removeNoise));
      form.set("consent_own_voice", String(input.consentOwnVoice));
      form.set("consent_no_impersonation", String(input.consentNoImpersonation));
      return apiUpload<CloneOut>(adminSession(), OPS_CLONES_PATH, form, {
        confirmAction: CLONE_CONFIRMATION,
      });
    },
    onSuccess: invalidate,
  });
}

/** `confirm` is sent only after the server has named the live agents a delete would move. */
export function useDeleteClone(): UseMutationResult<
  DeleteCloneOut,
  Error,
  { voiceId: string; confirm: boolean }
> {
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: ({ voiceId, confirm }) =>
      apiRequest<DeleteCloneOut>(
        adminSession(),
        `${OPS_CLONES_PATH}?voice_id=${encodeURIComponent(voiceId)}&confirm=${confirm}`,
        { method: "DELETE", confirmAction: deleteCloneConfirmation(voiceId) },
      ),
    onSuccess: invalidate,
  });
}

export function useUploadPreview(): UseMutationResult<
  HostedVoiceWrite,
  Error,
  { voiceId: string; sample: File }
> {
  const client = useQueryClient();
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: ({ voiceId, sample }) => {
      const form = new FormData();
      form.set("voice_id", voiceId);
      form.set("sample", sample);
      return apiUpload<HostedVoiceWrite>(adminSession(), OPS_PREVIEW_UPLOAD_PATH, form);
    },
    onSuccess: () =>
      Promise.all([invalidate(), client.invalidateQueries({ queryKey: ["voice-preview"] })]),
  });
}

export function useFetchPreview(): UseMutationResult<HostedVoiceWrite, Error, FetchPreviewIn> {
  const client = useQueryClient();
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<HostedVoiceWrite>(adminSession(), OPS_PREVIEW_FETCH_PATH, {
        method: "POST",
        body,
      }),
    onSuccess: () =>
      Promise.all([invalidate(), client.invalidateQueries({ queryKey: ["voice-preview"] })]),
  });
}

export function useSetupStudioWorkspace(): UseMutationResult<StudioWorkspace, Error, StudioSetupIn> {
  const client = useQueryClient();
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<StudioWorkspace>(adminSession(), OPS_STUDIO_WORKSPACE_PATH, {
        method: "POST",
        body,
        confirmAction: STUDIO_SETUP_CONFIRMATION,
      }),
    onSuccess: (data) => {
      client.setQueryData(hostedVoiceKeys.studio, data);
      return invalidate();
    },
  });
}

/** What each curation state means, for the toggle's description. */
export const HOSTED_STATE_MEANING: Record<string, string> = {
  enabled: "Offered — clients can choose this voice for their agents.",
  disabled: "Not offered — nobody can choose it. Agents already on it keep speaking it.",
  archived: "Archived — not offered, and filed away. Agents already on it keep speaking it.",
};

/** The rung's name as the console prints it. The wire value is the key. */
export const RUNG_LABEL: Record<string, string> = { clear: "Clear", studio: "Studio" };
