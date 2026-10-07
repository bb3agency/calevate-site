/**
 * The voice platform's OWN voices and models, each with whether it may be chosen today.
 *
 *   GET /v1/agents/engine-catalogue    `agents:read`, realm ANY
 *
 * Only an engine that speaks its own voices publishes one (ThinnestAI, D-678); on every other
 * engine the answer is `available: false` and the picker at `/v1/agents/voices` is the one
 * that matters. The refusal sentences arrive in the reader's audience — an operator's on the
 * console's view-as session, a client's on their own — so this module composes none.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { viewAsSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type EngineCatalogue = components["schemas"]["EngineCatalogueOut"];
export type EngineCatalogueVoice = components["schemas"]["EngineCatalogueVoiceOut"];
export type EngineCatalogueModel = components["schemas"]["EngineCatalogueModelOut"];

export const ENGINE_CATALOGUE_PATH = "/v1/agents/engine-catalogue";

function catalogueOptions(session: Session, audienceKey: string) {
  return {
    // Keyed by audience as well as path: the refusal sentences differ by realm.
    queryKey: ["engine-catalogue", audienceKey] as const,
    queryFn: () => apiRequest<EngineCatalogue>(session, ENGINE_CATALOGUE_PATH),
    // A live read of the platform's list and of the attested rates; five minutes is fresh
    // enough for a picker and spares the platform a request on every render.
    staleTime: 5 * 60_000,
  };
}

/** From a client's own session. */
export function useEngineCatalogue(session: Session): UseQueryResult<EngineCatalogue> {
  return useQuery(catalogueOptions(session, "client"));
}

/** From the console, through the impersonation session for that tenant. */
export function useTenantEngineCatalogue(slug: string): UseQueryResult<EngineCatalogue> {
  return useQuery({
    ...catalogueOptions(viewAsSession(slug), `operator:${slug}`),
    enabled: Boolean(slug),
  });
}
