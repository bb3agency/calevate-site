/**
 * The voice platform's OWN voices and models, each with whether it may be chosen today.
 *
 *   GET /v1/agents/engine-catalogue    `agents:read`, realm ANY
 *
 * Only an engine that speaks its own voices publishes one (ThinnestAI, D-678); on any other
 * engine (the fake one in tests) the answer is `available: false`. The refusal sentences
 * arrive in the reader's audience — an operator's on the
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

/**
 * With `agentId`, the list also carries that agent's own voice when it is no longer on offer
 * (`standing` `kept` or `unavailable`, D-880), so its picker shows the voice it speaks.
 */
function catalogueOptions(session: Session, audienceKey: string, agentId?: string, enabled = true) {
  const path = agentId
    ? `${ENGINE_CATALOGUE_PATH}?agent_id=${encodeURIComponent(agentId)}`
    : ENGINE_CATALOGUE_PATH;
  return {
    // Keyed by audience as well as path: the refusal sentences differ by realm.
    queryKey: ["engine-catalogue", audienceKey, agentId ?? "all"] as const,
    queryFn: () => apiRequest<EngineCatalogue>(session, path),
    // A live read of the platform's list and of the attested rates; five minutes is fresh
    // enough for a picker and spares the platform a request on every render.
    staleTime: 5 * 60_000,
    enabled,
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

/**
 * The agent's own voice when the shared list does not hold it: a voice an operator stopped
 * offering, or one the platform withdrew (D-880). Asked only then, so every agent on an
 * offered voice costs one shared read, not one per agent. Null until known, or when the
 * voice is not in our catalogue at all.
 */
export function useHeldVoice(
  session: Session,
  audienceKey: string,
  agentId: string | undefined,
  voiceId: string | null,
  catalogue: EngineCatalogue | undefined,
): EngineCatalogueVoice | null {
  const missing = Boolean(
    agentId && voiceId && catalogue?.available && !catalogue.voices.some((entry) => entry.voice_id === voiceId),
  );
  const read = useQuery(catalogueOptions(session, audienceKey, agentId, missing));
  if (!missing) return null;
  return read.data?.voices.find((entry) => entry.voice_id === voiceId && entry.standing !== "offered") ?? null;
}
