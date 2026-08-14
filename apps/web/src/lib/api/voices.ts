"use client";

/**
 * The voice catalogue and the one write that uses it (D-36's premium/value ladder).
 *
 *   GET   /v1/agents/voices          `agents:read`, realm ANY
 *   PATCH /v1/agents/{agent_id}/voice `agents:write`, realm ADMIN
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
 * ## What the catalogue does NOT tell you
 *
 * **There is no read of an agent's CURRENT voice.** `AgentOut` carries name, language,
 * disclosure line, status and extraction fields — not `tts_voice`, and no other endpoint
 * exposes it either. So a picker cannot show which entry is in force; it can only set one
 * and report what the write returned. That gap is stated on the screen rather than papered
 * over with a plausible default, and is reported for the backend to close (adding
 * `tts_voice` to `AgentOut`, or an admin agent read that carries it).
 *
 * ## Setting a voice does not reach the engine
 *
 * `set_agent_voice` writes our row and stops. `publish_agent` re-reads `tts_voice` when it
 * next runs, so a LIVE agent keeps its old voice until someone publishes — which is why
 * the response carries `republish_required` and `next_step` and why callers print them
 * instead of implying the change is live. That is a deliberate divergence from the prompt
 * path, argued at length in `agents/voice_routes.py`: re-voicing a running client's phone
 * line on an ear test we have not done is not a safe default.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession, viewAsSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One catalogue entry: the id we send the engine, plus what an operator needs to choose. */
export type Voice = Schemas["Voice"];
export type VoiceTier = Voice["tier"];
export type SetVoiceIn = Schemas["SetVoiceIn"];
export type SetVoiceOut = Schemas["SetVoiceOut"];

export const VOICES_PATH = "/v1/agents/voices";

/** One key for the whole catalogue: it is static data and identical for every tenant. */
export const voiceKeys = { catalogue: ["agent-voices"] as const };

function catalogueOptions(session: Session) {
  return {
    queryKey: voiceKeys.catalogue,
    queryFn: () => apiRequest<Voice[]>(session, VOICES_PATH),
    // Static per deployment — `list_voices` touches no database and no engine.
    staleTime: 30 * 60_000,
  };
}

/** The catalogue, client realm. */
export function useVoiceCatalogue(session: Session): UseQueryResult<Voice[]> {
  return useQuery(catalogueOptions(session));
}

/** The same catalogue from the console, through the impersonation session (see above). */
export function useTenantVoiceCatalogue(slug: string): UseQueryResult<Voice[]> {
  return useQuery({ ...catalogueOptions(viewAsSession(slug)), enabled: Boolean(slug) });
}

/**
 * Set an agent's voice — admin realm, admin session, tenant named in the BODY.
 *
 * The tenant rides in the body rather than the path because that is the route's shape
 * (`agents/voice_routes.py` explains why: an admin principal has no tenant of its own, and
 * the one way it could get one — impersonation — is refused for every mutation by D-22).
 * Nothing here infers it from a session, and there is no session on this call that HAS
 * one.
 *
 * An id outside the catalogue comes back as `unknown_voice` problem+json with the list in
 * its remediation, so no client-side membership check is duplicated here.
 */
export function useSetAgentVoice(target: { tenantId: string; agentId: string; slug: string }) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (voiceId: string) =>
      apiRequest<SetVoiceOut>(adminSession(), `/v1/agents/${target.agentId}/voice`, {
        method: "PATCH",
        body: { tenant_id: target.tenantId, voice_id: voiceId } satisfies SetVoiceIn,
      }),
    // The agent roster carries `status`/`published`, which this write echoes back and a
    // future read of the voice would live on. Nothing else on either screen moves.
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ["agents", target.slug] }),
        client.invalidateQueries({ queryKey: ["admin", "agents", target.slug] }),
      ]),
  });
}
