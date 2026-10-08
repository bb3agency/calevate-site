"use client";

/**
 * A voice's PREVIEW CLIP, as bytes, for the play buttons (D-687).
 *
 *   GET /v1/agents/engine-catalogue/preview?voice_id=…   `agents:read`, realm ANY
 *       — a client for a voice on offer; the console's view-as session for that tenant.
 *   GET /v1/ops/voices/hosted/preview?voice_id=…         `ops:manage`, realm ADMIN
 *       — the Voices page, which has no tenant to view as and so cannot use the first.
 *
 * The clip is served by Calevate, never as a vendor link, so it is read through
 * `apiRequest` like everything else (the session cookie, the view-as grant, problem+json on
 * a 404) and handed to an `<audio>` element as an object URL. It is fetched only when
 * somebody presses play: a picker of twenty voices must not download twenty clips.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { operations, paths } from "./schema";

// Held to the generated route table, so a renamed route breaks the build, not a play button.
export const CLIENT_PREVIEW_PATH =
  "/v1/agents/engine-catalogue/preview" satisfies keyof paths;
export const OPS_PREVIEW_PATH = "/v1/ops/voices/hosted/preview" satisfies keyof paths;

/** The two GETs the buttons call, as the generated client names them. */
export type ClientPreviewQuery = operations["engine_voice_preview_v1_agents_engine_catalogue_preview_get"]["parameters"]["query"];
export type OpsPreviewQuery = operations["hosted_voice_preview_v1_ops_voices_hosted_preview_get"]["parameters"]["query"];

/** The query string both routes take. Voice ids carry `:` and vendor alphabets. */
export function previewUrl(path: string, voiceId: string): string {
  const query: ClientPreviewQuery & OpsPreviewQuery = { voice_id: voiceId };
  return `${path}?voice_id=${encodeURIComponent(query.voice_id)}`;
}

/**
 * The clip, once `enabled` (the first press). Keyed by the account as well as the voice:
 * what a client may hear is decided per audience, and an operator moving between tenants
 * keeps one query cache. Never stale within a page's life — the bytes for one id only
 * change when an operator replaces them, and the Voices page invalidates on that write.
 */
export function useVoicePreview(
  session: Session,
  path: string,
  voiceId: string,
  enabled: boolean,
): UseQueryResult<Blob> {
  return useQuery({
    queryKey: ["voice-preview", session.orgSlug, path, voiceId] as const,
    queryFn: () =>
      apiRequest<Blob>(session, previewUrl(path, voiceId), { responseType: "blob" }),
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
}
