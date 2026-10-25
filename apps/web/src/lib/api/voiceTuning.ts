"use client";

/**
 * How an agent's voice sounds. Operators set every field; a client sets speed, loudness and
 * emotion on its own agents and hears a capped sample (D-843, 21 Oct 2026). Speed applies on
 * any voice, in the range and step `options` gives for the voice in use (D-884); the rest,
 * and the sample, only on a Studio voice.
 *
 *   GET   /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning           `admin:tenants`
 *   PATCH /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning           `agents:write`, audited
 *   POST  /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning/preview   the audio, unsaved
 *   GET   /v1/agents/{aid}/voice-tuning                               `agents:read`
 *   PATCH /v1/agents/{aid}/voice-tuning                               `org:manage`, audited
 *   POST  /v1/agents/{aid}/voice-tuning/preview                       a fixed sample, capped per day
 *
 * Speed and volume arrive as decimal strings (NUMERIC on the server) and go back as numbers.
 * A field left out of a save is kept; null clears it.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type VoiceTuning = Schemas["VoiceTuningOut"];
export type VoiceTuningIn = Schemas["VoiceTuningIn"];
export type VoiceTuningPreviewIn = Schemas["VoiceTuningPreviewIn"];

const PATH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice-tuning" satisfies keyof paths;
const PREVIEW_PATH =
  "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice-tuning/preview" satisfies keyof paths;

export function voiceTuningPath(tenantId: string, agentId: string): string {
  return PATH.replace("{tenant_id}", tenantId).replace("{agent_id}", agentId);
}

export function voiceTuningPreviewPath(tenantId: string, agentId: string): string {
  return PREVIEW_PATH.replace("{tenant_id}", tenantId).replace("{agent_id}", agentId);
}

export const voiceTuningKey = (tenantId: string, agentId: string) =>
  ["voice-tuning", tenantId, agentId] as const;

/** A held speed or volume as a number, or null; the server sends decimals as strings. */
export function tuningNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function useVoiceTuning(tenantId: string, agentId: string): UseQueryResult<VoiceTuning> {
  return useQuery({
    queryKey: voiceTuningKey(tenantId, agentId),
    queryFn: () => apiRequest<VoiceTuning>(adminSession(), voiceTuningPath(tenantId, agentId)),
    enabled: Boolean(tenantId) && Boolean(agentId),
  });
}

export function useSetVoiceTuning(
  tenantId: string,
  agentId: string,
): UseMutationResult<VoiceTuning, Error, VoiceTuningIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: VoiceTuningIn) =>
      apiRequest<VoiceTuning>(adminSession(), voiceTuningPath(tenantId, agentId), {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: (data) => {
      client.setQueryData(voiceTuningKey(tenantId, agentId), data);
    },
  });
}

/** One spoken line with the settings sent, as audio. Charged per character: on a press only. */
export function useVoiceTuningPreview(
  tenantId: string,
  agentId: string,
): UseMutationResult<Blob, Error, VoiceTuningPreviewIn> {
  return useMutation({
    mutationFn: (payload: VoiceTuningPreviewIn) =>
      apiRequest<Blob>(adminSession(), voiceTuningPreviewPath(tenantId, agentId), {
        method: "POST",
        body: payload,
        responseType: "blob",
      }),
  });
}

/* ------------------------------------------------------------------- client realm */

export type ClientVoiceTuning = Schemas["ClientVoiceTuningOut"];
export type ClientVoiceTuningIn = Schemas["ClientVoiceTuningIn"];

const CLIENT_PATH = "/v1/agents/{agent_id}/voice-tuning" satisfies keyof paths;
const CLIENT_PREVIEW_PATH = "/v1/agents/{agent_id}/voice-tuning/preview" satisfies keyof paths;

/**
 * Keyed by the agent's configured voice too: choosing another voice changes whether these
 * apply (`studio`) and may start the emotion on calm, so a new voice reads afresh.
 */
export const clientVoiceTuningKey = (orgSlug: string, agentId: string, voiceId: string | null) =>
  ["voice-tuning", "client", orgSlug, agentId, voiceId] as const;

export function useClientVoiceTuning(
  session: Session,
  agentId: string,
  voiceId: string | null,
): UseQueryResult<ClientVoiceTuning> {
  return useQuery({
    queryKey: clientVoiceTuningKey(session.orgSlug, agentId, voiceId),
    queryFn: () =>
      apiRequest<ClientVoiceTuning>(session, CLIENT_PATH.replace("{agent_id}", agentId)),
    enabled: Boolean(agentId),
  });
}

export function useSetClientVoiceTuning(
  session: Session,
  agentId: string,
  voiceId: string | null,
): UseMutationResult<ClientVoiceTuning, Error, ClientVoiceTuningIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ClientVoiceTuningIn) =>
      apiRequest<ClientVoiceTuning>(session, CLIENT_PATH.replace("{agent_id}", agentId), {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: (data) => {
      client.setQueryData(clientVoiceTuningKey(session.orgSlug, agentId, voiceId), data);
    },
  });
}

/** One fixed sample line with the settings sent, as audio; each press uses one of the day's. */
export function useClientVoiceTuningPreview(
  session: Session,
  agentId: string,
  voiceId: string | null,
): UseMutationResult<Blob, Error, ClientVoiceTuningIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ClientVoiceTuningIn) =>
      apiRequest<Blob>(session, CLIENT_PREVIEW_PATH.replace("{agent_id}", agentId), {
        method: "POST",
        body: payload,
        responseType: "blob",
      }),
    // The count of samples left moved either way (a refusal past the cap included).
    onSettled: () =>
      client.invalidateQueries({
        queryKey: clientVoiceTuningKey(session.orgSlug, agentId, voiceId),
      }),
  });
}
