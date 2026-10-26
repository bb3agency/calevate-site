"use client";

/**
 * THE VOICES A HOSTING VOICE PLATFORM SPEAKS, AS CURATED HERE (D-687) — admin realm,
 * `ops:manage`.
 *
 *   GET    /v1/ops/voices/hosted?scope=added|all   the hosted voices; `available:false` on
 *                                                   an engine that hosts no voices
 *   POST   /v1/ops/voices/hosted                   add one synced voice (arrives disabled)
 *   PATCH  /v1/ops/voices/hosted                   enable | disable | archive one
 *   GET    /v1/ops/voices/hosted/agents            the agents set to one voice
 *   PATCH  /v1/ops/voices/hosted/display-name      the name clients see
 *   PATCH  /v1/ops/voices/hosted/person-clone      mark a cloned voice of a real person (step-up)
 *   POST   /v1/ops/voices/hosted/clone-consent     record that person's consent (step-up)
 *   GET    /v1/ops/voices/hosted/clone-consent/document  the signed consent
 *   POST   /v1/ops/voices/clones                   clone from a recording (step-up)
 *   DELETE /v1/ops/voices/clones                   delete one of our clones (step-up)
 *   POST   /v1/ops/voices/hosted/preview           upload a preview clip
 *   POST   /v1/ops/voices/hosted/preview/fetch     store the platform's own preview
 *   GET    /v1/ops/voices/studio-voices           Studio readiness and its client workspaces
 *   POST   /v1/ops/voices/studio-voices/enable    Studio ready: switch our key on (step-up, D-727)
 *   GET    /v1/ops/voices/own-model               our own model: readiness, workspaces (D-764)
 *   POST   /v1/ops/voices/own-model/enable        our Google key into one client workspace (step-up)
 *   POST   /v1/ops/voices/own-model/developer     our Google key into our developer workspace (step-up)
 *
 * The Voices page reads the hosted list and branches on `available`: an engine that hosts no
 * voices of its own (the fake engine in tests) answers `available: false`, and the server, not
 * this bundle, says which engine this is.
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

import { needsReauthentication } from "@/lib/authn/problems";
import { withActionCode } from "@/lib/authn/stepUpPrompt";

import { adminSession, confirmedAdminRequest } from "./admin";
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
export type StudioVoices = Schemas["StudioVoicesOut"];
export type StudioEnableIn = Schemas["StudioEnableIn"];
export type OwnModel = Schemas["OwnModelOut"];
export type OwnModelEnableIn = Schemas["OwnModelEnableIn"];
export type FetchPreviewIn = Schemas["FetchPreviewIn"];
export type HostedVoiceAgents = Schemas["HostedVoiceAgentsOut"];
export type CloneConsentRecord = Schemas["CloneConsentOut"];

export const OPS_HOSTED_PATH = "/v1/ops/voices/hosted";
export const OPS_CLONES_PATH = "/v1/ops/voices/clones";
export const OPS_PREVIEW_UPLOAD_PATH = "/v1/ops/voices/hosted/preview";
export const OPS_PREVIEW_FETCH_PATH = "/v1/ops/voices/hosted/preview/fetch";
export const OPS_HOSTED_AGENTS_PATH = "/v1/ops/voices/hosted/agents";
export const OPS_DISPLAY_NAME_PATH = "/v1/ops/voices/hosted/display-name";
export const OPS_PERSON_CLONE_PATH = "/v1/ops/voices/hosted/person-clone";
export const OPS_CLONE_CONSENT_PATH = "/v1/ops/voices/hosted/clone-consent";
export const OPS_CLONE_CONSENT_DOCUMENT_PATH = "/v1/ops/voices/hosted/clone-consent/document";
export const OPS_STUDIO_VOICES_PATH = "/v1/ops/voices/studio-voices";
export const OPS_STUDIO_ENABLE_PATH = "/v1/ops/voices/studio-voices/enable";

/** The confirmations the API names for its step-up writes. */
export const CLONE_CONFIRMATION = "clone_voice";
export const STUDIO_ENABLE_CONFIRMATION = "enable_studio_voices";
export const OPS_OWN_MODEL_PATH = "/v1/ops/voices/own-model";
export const OPS_OWN_MODEL_ENABLE_PATH = "/v1/ops/voices/own-model/enable";
export const OWN_MODEL_ENABLE_CONFIRMATION = "enable_own_model_workspace";
export const OPS_OWN_MODEL_DEVELOPER_PATH = "/v1/ops/voices/own-model/developer";
export const OWN_MODEL_DEVELOPER_CONFIRMATION = "enable_own_model_developer";
export const deleteCloneConfirmation = (voiceId: string) => `delete_voice_clone:${voiceId}`;
export const consentConfirmation = (voiceId: string) => `record_voice_consent:${voiceId}`;
export const personCloneConfirmation = (voiceId: string) => `set_voice_person_clone:${voiceId}`;

/** What every consent record covers (the server stores the same sentence on each). */
export const CONSENT_SCOPE = "Calls made by Calevate clients' agents.";

/** The size the clone and preview routes accept (the API's own request limit). */
export const MAX_SAMPLE_BYTES = 2 * 1024 * 1024;

/** Global, not org-scoped: one vendor account serves every tenant. */
export const hostedVoiceKeys = {
  all: ["admin", "ops", "voices", "hosted"] as const,
  scoped: (scope: HostedScope) => ["admin", "ops", "voices", "hosted", scope] as const,
  studio: ["admin", "ops", "voices", "studio-voices"] as const,
  ownModel: ["admin", "ops", "voices", "own-model"] as const,
  agents: (voiceId: string) => ["admin", "ops", "voices", "hosted", "agents", voiceId] as const,
};

/** The agents set to one voice, across every account; read when its detail opens. */
export function useHostedVoiceAgents(voiceId: string | null): UseQueryResult<HostedVoiceAgents> {
  return useQuery({
    queryKey: hostedVoiceKeys.agents(voiceId ?? ""),
    queryFn: () =>
      apiRequest<HostedVoiceAgents>(
        adminSession(),
        `${OPS_HOSTED_AGENTS_PATH}?voice_id=${encodeURIComponent(voiceId ?? "")}`,
      ),
    enabled: voiceId !== null,
  });
}

export function useSetDisplayName(): UseMutationResult<
  HostedVoiceWrite,
  Error,
  { voice_id: string; display_label: string | null }
> {
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<HostedVoiceWrite>(adminSession(), OPS_DISPLAY_NAME_PATH, { method: "PATCH", body }),
    onSuccess: invalidate,
  });
}

/** Mark or unmark a cloned voice of a real person (step-up; unmarking deletes its consent). */
export function useSetPersonClone(): UseMutationResult<
  HostedVoiceWrite,
  Error,
  { voice_id: string; person_clone: boolean }
> {
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (body) =>
      confirmedAdminRequest<HostedVoiceWrite>(
        OPS_PERSON_CLONE_PATH,
        { method: "PATCH", body, confirmAction: personCloneConfirmation(body.voice_id) },
        "Changing whether this voice is a real person's.",
      ),
    onSuccess: invalidate,
  });
}

export interface CloneConsentInput {
  voiceId: string;
  speakerName: string;
  statement: string;
  /** `YYYY-MM-DD`, the day the speaker consented (IST). */
  consentedOn: string;
  document: File | null;
}

/** Record the speaker's consent (step-up). Marks the voice as a person's clone too. */
export function useRecordConsent(): UseMutationResult<HostedVoiceWrite, Error, CloneConsentInput> {
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (input) => {
      const form = new FormData();
      form.set("voice_id", input.voiceId);
      form.set("speaker_name", input.speakerName);
      form.set("statement", input.statement);
      form.set("consented_on", input.consentedOn);
      if (input.document) form.set("document", input.document);
      const confirmAction = consentConfirmation(input.voiceId);
      return withActionCode(
        confirmAction,
        "Recording the speaker's consent for this voice.",
        () =>
          apiUpload<HostedVoiceWrite>(adminSession(), OPS_CLONE_CONSENT_PATH, form, {
            confirmAction,
          }),
        needsReauthentication,
      );
    },
    onSuccess: invalidate,
  });
}

/** The signed consent document, as a file the browser saves. */
export async function downloadConsentDocument(voiceId: string, label: string): Promise<void> {
  const blob = await apiRequest<Blob>(
    adminSession(),
    `${OPS_CLONE_CONSENT_DOCUMENT_PATH}?voice_id=${encodeURIComponent(voiceId)}`,
    { responseType: "blob" },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  const ext = blob.type === "application/pdf" ? "pdf" : blob.type === "image/png" ? "png" : "jpg";
  link.download = `${label.replace(/[^A-Za-z0-9 _-]/g, "").trim() || "voice"} consent.${ext}`;
  link.click();
  URL.revokeObjectURL(url);
}

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

export function useStudioVoices(enabled: boolean): UseQueryResult<StudioVoices> {
  return useQuery({
    queryKey: hostedVoiceKeys.studio,
    queryFn: () => apiRequest<StudioVoices>(adminSession(), OPS_STUDIO_VOICES_PATH),
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
      return withActionCode(
        CLONE_CONFIRMATION,
        "Cloning a voice.",
        () =>
          apiUpload<CloneOut>(adminSession(), OPS_CLONES_PATH, form, {
            confirmAction: CLONE_CONFIRMATION,
          }),
        needsReauthentication,
      );
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
      confirmedAdminRequest<DeleteCloneOut>(
        `${OPS_CLONES_PATH}?voice_id=${encodeURIComponent(voiceId)}&confirm=${confirm}`,
        { method: "DELETE", confirmAction: deleteCloneConfirmation(voiceId) },
        "Deleting a cloned voice.",
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

/**
 * Studio ready (D-717): the server holds our Cartesia key in the developer workspace with its
 * switch off and, given `tenant_id`, switches Studio on in that client's own workspace (its
 * Clear agents kept off first). The Studio voices it then reads change every picker, so the
 * lists are invalidated too.
 */
export function useEnableStudioVoices(): UseMutationResult<StudioVoices, Error, StudioEnableIn> {
  const client = useQueryClient();
  const invalidate = useInvalidateVoices();
  return useMutation({
    mutationFn: (body) =>
      confirmedAdminRequest<StudioVoices>(
        OPS_STUDIO_ENABLE_PATH,
        { method: "POST", body, confirmAction: STUDIO_ENABLE_CONFIRMATION },
        "Switching Studio voices.",
      ),
    onSuccess: (data) => {
      client.setQueryData(hostedVoiceKeys.studio, data);
      return invalidate();
    },
  });
}

/**
 * Each curation state as the switch names it, and what it means. The switch's label IS the
 * state, so "Offered to clients" is never captioned "Archived".
 */
export const HOSTED_STATE: Record<string, { label: string; meaning: string }> = {
  enabled: { label: "Offered to clients", meaning: "Clients can choose it for their agents." },
  disabled: {
    label: "Not offered",
    meaning: "Clients cannot choose it. Agents already on it keep speaking it.",
  },
  archived: {
    label: "Archived",
    meaning: "Not offered, and kept out of the list. An agent still on it keeps speaking it until moved.",
  },
};

/** The rung's name as the console prints it. The wire value is the key. */
export const RUNG_LABEL: Record<string, string> = { clear: "Clear", studio: "Studio" };

/**
 * The voice platform's own price band for one of its voices. Vendor words, on admin screens
 * only: only the band the server names as `clear_band` can be added and sold as Clear. Always
 * "ThinnestAI … band", never a bare "Studio", which is OUR tier (D-717).
 */
export const BAND_LABEL: Record<string, string> = {
  standard: "ThinnestAI Standard band",
  premium: "ThinnestAI Premium band",
  studio: "ThinnestAI Studio band",
};

/** Our own model (D-764): whether agents can answer on our Google key, and where it is on. */
export function useOwnModel(enabled: boolean): UseQueryResult<OwnModel> {
  return useQuery({
    queryKey: hostedVoiceKeys.ownModel,
    queryFn: () => apiRequest<OwnModel>(adminSession(), OPS_OWN_MODEL_PATH),
    enabled,
  });
}

export type CallCacheShares = Schemas["CallCacheSharesOut"];

/**
 * How much of each listed call's input was served from the provider's cache, for calls that
 * ran on our own model (D-839). Only the calls on our model come back; `retry: false`, because
 * an operator without `ops:manage` is refused and the list simply shows no share.
 */
export function useCallCacheShares(tenantId: string, callIds: string[]): UseQueryResult<CallCacheShares> {
  const query = new URLSearchParams({ tenant_id: tenantId });
  for (const id of callIds) query.append("call_id", id);
  return useQuery({
    queryKey: [...hostedVoiceKeys.ownModel, "cache-shares", tenantId, callIds],
    queryFn: () => apiRequest<CallCacheShares>(adminSession(), `${OPS_OWN_MODEL_PATH}/cache-shares?${query.toString()}`),
    enabled: callIds.length > 0,
    retry: false,
  });
}

/** Installs our Google key in one paying client's own workspace now (step-up). */
export function useEnableOwnModelWorkspace(): UseMutationResult<OwnModel, Error, OwnModelEnableIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      confirmedAdminRequest<OwnModel>(
        OPS_OWN_MODEL_ENABLE_PATH,
        { method: "POST", body, confirmAction: OWN_MODEL_ENABLE_CONFIRMATION },
        "Installing our model key in this client's workspace.",
      ),
    onSuccess: (data) => {
      client.setQueryData(hostedVoiceKeys.ownModel, data);
    },
  });
}

/** Installs our Google key in our developer workspace, where free-trial agents live (D-834). */
export function useEnableOwnModelDeveloper(): UseMutationResult<OwnModel, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      confirmedAdminRequest<OwnModel>(
        OPS_OWN_MODEL_DEVELOPER_PATH,
        { method: "POST", confirmAction: OWN_MODEL_DEVELOPER_CONFIRMATION },
        "Installing our model key in the developer workspace.",
      ),
    onSuccess: (data) => {
      client.setQueryData(hostedVoiceKeys.ownModel, data);
    },
  });
}
