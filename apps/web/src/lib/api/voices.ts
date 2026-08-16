"use client";

/**
 * The voice catalogue and the one write that uses it (D-36's premium/value ladder).
 *
 *   GET   /v1/agents/voices                                     `agents:read`, realm ANY
 *   PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice `agents:write`, realm ADMIN
 *
 * That split is D-21's and it decides the shape of this module. Which voice speaks Telugu
 * well is an EAR TEST, not a spec fact (BRD §6 R-10, TRD §10.1, OPERATIONS §2 gate 3), so
 * a client may HEAR what their agent sounds like and only we may change it. There is
 * therefore deliberately no client-realm setter here — the same rule `agents.ts` and
 * `publishing.ts` already follow: a button that could only ever 403 is worse than no
 * button.
 *
 * ## The catalogue read needs a tenant even from the console
 *
 * `list_voices` is `realm="any"`, which resolves through `current_any` — and `current_any`
 * consults the admin realm ONLY when `X-Impersonate-Org` is present (core/auth.py),
 * falling through to the client verifier otherwise. So an admin session with no
 * impersonation header is rejected on a `/v1/agents/...` path even though the data is
 * static and tenant-independent. The console therefore reads it through `viewAsSession`,
 * exactly as `publishing.ts` reads `/v1/agents/lanes`. `agents:read` is not in
 * `MUTATING_PERMISSIONS`, so D-22 leaves the read alone.
 *
 * ## Where an agent's CURRENT voice is read — not here
 *
 * `GET /v1/agents/{agent_id}/pending` carries it, as `voice.configured` and `voice.live`
 * (see `publishing.ts`). It is not on `AgentOut` and not on a second admin read, and the
 * argument is in `agents/publishing_routes.py`: a voice is TWO facts, the one configured
 * and the one the engine is holding, and that is the question the pending read already
 * answers for the script and the call cap. The picker in this module therefore reads its
 * pre-selection from `usePendingChanges`/`useTenantPending` rather than from a voice
 * endpoint of its own — one read, one cache, one answer.
 *
 * ## Setting a voice does not reach the engine
 *
 * `set_agent_voice` writes our row and stops. `publish_agent` re-reads `tts_voice` when it
 * next runs, so a LIVE agent keeps its old voice until someone publishes — which is why
 * the response carries `republish_required` and `next_step` and why callers print them
 * instead of implying the change is live. That is a deliberate divergence from the prompt
 * path, argued at length in `agents/voice_routes.py`: re-voicing a running client's phone
 * line on an ear test we have not done is not a safe default.
 *
 * That is also why the write invalidates the PENDING read: a voice change moves
 * `voice.configured` and deliberately leaves `voice.live` alone, so a screen that did not
 * refetch would keep showing the previous configuration beside the new one.
 */

import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession, viewAsSession } from "./admin";
import { apiRequest, type Session } from "./client";
import { usePublishingRefresh } from "./publishing";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One catalogue entry: the id we send the engine, plus what an operator needs to choose. */
export type Voice = Schemas["Voice"];
export type VoiceTier = Voice["tier"];

/**
 * The catalogue AND whether it may be chosen from (D-93).
 *
 * Every field is REQUIRED on the wire — none carries a Pydantic default — and that is
 * deliberate: an optional `selectable` would arrive `undefined`, read as falsy, and hide
 * the picker on a perfectly capable engine. `control` says who owns the TTS leg; when it
 * is the engine's, `voices` is empty BY DESIGN rather than by failure, and `note` is the
 * sentence to print verbatim in either state.
 */
export type VoiceCatalogue = Schemas["VoiceCatalogueOut"];

export type SetVoiceIn = Schemas["SetVoiceIn"];
export type SetVoiceOut = Schemas["SetVoiceOut"];

export const VOICES_PATH = "/v1/agents/voices";

/** One key for the whole catalogue: it is static data and identical for every tenant. */
export const voiceKeys = { catalogue: ["agent-voices"] as const };

function catalogueOptions(session: Session) {
  return {
    queryKey: voiceKeys.catalogue,
    queryFn: () => apiRequest<VoiceCatalogue>(session, VOICES_PATH),
    // Static per deployment — `list_voices` touches no database and makes no network
    // call; the capability it reads is a declared attribute of the selected adapter.
    staleTime: 30 * 60_000,
  };
}

/** The catalogue, client realm. */
export function useVoiceCatalogue(session: Session): UseQueryResult<VoiceCatalogue> {
  return useQuery(catalogueOptions(session));
}

/** The same catalogue from the console, through the impersonation session (see above). */
export function useTenantVoiceCatalogue(slug: string): UseQueryResult<VoiceCatalogue> {
  return useQuery({ ...catalogueOptions(viewAsSession(slug)), enabled: Boolean(slug) });
}

/**
 * Set an agent's voice — admin realm, admin session, tenant named in the PATH.
 *
 * The tenant is in the URL rather than inferred from a session because an admin principal
 * has no tenant of its own, and the one way it could get one — impersonation — is refused
 * for every mutation by D-22 (`agents/voice_routes.py` argues it in full). It USED TO ride
 * in the body, on `PATCH /v1/agents/{agent_id}/voice`: the same tenant, named in the one
 * place the admin console does not name it anywhere else, on the only admin-realm route
 * that lived in the client path space. Moving it cost this module a template literal and
 * bought the route the `/v1/admin` rate-limit profile plus an audit trail readable from
 * the URL.
 *
 * Breaking change with no alias, and this file is why that is safe: the endpoint is
 * admin-realm, so its only reachable caller is this console, which is generated from the
 * server's own schema and deployed with it.
 *
 * An id outside the catalogue comes back as `unknown_voice` problem+json with the list in
 * its remediation, so no client-side membership check is duplicated here.
 */
export function useSetAgentVoice(target: { tenantId: string; agentId: string; slug: string }) {
  // `usePublishingRefresh` rather than a second hand-written invalidation list: the
  // pending read is where `voice.configured` lives, it is keyed by org SLUG, and the
  // same helper already invalidates it for Apply, Undo and the call cap. Two lists of
  // cache keys for one set of screens is where the drift starts — the second one is
  // always the one that forgets a key.
  const refresh = usePublishingRefresh(target);
  return useMutation({
    mutationFn: (voiceId: string) =>
      apiRequest<SetVoiceOut>(
        adminSession(),
        `/v1/admin/tenants/${target.tenantId}/agents/${target.agentId}/voice`,
        {
          method: "PATCH",
          body: { voice_id: voiceId } satisfies SetVoiceIn,
        },
      ),
    onSuccess: refresh,
  });
}
