"use client";

/**
 * Re-read the voice platform's own voice list (D-590, D-687).
 *
 *   POST  /v1/ops/voices/refresh  `ops:manage`, realm ADMIN
 *
 * Nothing here is org-scoped: one vendor account serves every tenant and its voice list is the
 * same list for all of them, so every request mints an `adminSession()` and no key carries a
 * slug (`tests/queryKeys.test.ts`).
 */

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** What one refresh did; `note` is the server's sentence for the operator. */
export type VoiceRefresh = Schemas["VoiceCatalogueRefreshOut"];

export const OPS_VOICES_REFRESH_PATH = "/v1/ops/voices/refresh";

/**
 * Re-read the voice platform's catalogue into the cache, then reload what reads it.
 *
 * The response is REPORTED to the operator (a partial or refused sync is a fact they have to
 * see) but never used as the rows: the lists are re-read, so the screen never shows a list
 * assembled out of two different answers.
 */
export function useRefreshVoiceCatalogue(): UseMutationResult<VoiceRefresh, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<VoiceRefresh>(adminSession(), OPS_VOICES_REFRESH_PATH, { method: "POST" }),
    onSuccess: () =>
      Promise.all([
        // A prefix of every Voices-page key (`opsHostedVoices.ts`).
        client.invalidateQueries({ queryKey: ["admin", "ops", "voices"] }),
        client.invalidateQueries({ queryKey: ["engine-catalogue"] }),
      ]),
  });
}
