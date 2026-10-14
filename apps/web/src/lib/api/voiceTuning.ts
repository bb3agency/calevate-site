"use client";

/**
 * How a Studio voice sounds on one agent: the operator's settings (13 Oct 2026, admin only).
 *
 *   GET   /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning           `admin:tenants`
 *   PATCH /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning           `agents:write`, audited
 *   POST  /v1/admin/tenants/{tid}/agents/{aid}/voice-tuning/preview   the audio, unsaved
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
import { apiRequest } from "./client";
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
