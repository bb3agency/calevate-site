"use client";

/**
 * The voice catalogue and the one write that uses it (one Bulbul v3 quality; personas).
 *
 *   GET   /v1/agents/voices                                     `agents:read`, realm ANY
 *   PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice `agents:write`, realm ADMIN
 *
 *   PATCH /v1/agents/{agent_id}/voice                          `agents:write`, realm ANY
 *
 * ⚠ **THIS DOCSTRING USED TO SAY "there is deliberately no client-realm setter here"**,
 * on D-21's ground that only we may change a voice. D-586 withdrew that ground for this
 * setting: a voice is delivery on the client's own phone line, the account's owner and
 * their staff hold `agents:write` for it, and the write re-publishes a live agent in the
 * same transaction so the screen never claims a voice the platform is not speaking. The
 * admin route stays — it is the ONBOARDING door, used before a client has ever signed in,
 * and it calls the same server-side writer.
 *
 * **The read half is not client-facing YET, and this docstring used to say it was.** It
 * justified the client-realm route as existing so "a client may HEAR what their agent
 * sounds like" — the right eventual reason (which voice speaks Telugu well is an EAR
 * TEST, not a spec fact: BRD §6 R-10, TRD §10.1, OPERATIONS §2 gate 3) attached to a
 * capability that is neither wired nor representable. No client screen reads the
 * catalogue, and `Voice` carries no sample or preview URL of any kind, so there is
 * nothing for a client to hear. Listening needs a field on the API's `Voice` model — a
 * signed sample URL — before it needs a screen, so the client-realm hook is NOT sitting
 * here unwired waiting for one (see below).
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

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession, viewAsSession } from "./admin";
import { apiRequest, type Session } from "./client";
import { publishingKeys, usePublishingRefresh } from "./publishing";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One catalogue entry: the id we send the engine, plus what an operator needs to choose. */
export type Voice = Schemas["Voice"];

/**
 * A catalogue row AS THE LISTING ANSWERS IT — `Voice` plus this deployment's verdict on it,
 * including `tier_label`, the tier's client-facing name ("Clear", "Studio") and the only
 * name of a voice quality a human may read (founder, 7 Sep 2026; see the tier section at
 * the foot of this module).
 *
 * It is a SUPERSET of `Voice` on the wire, not an envelope, so anything that renders a
 * `Voice` renders one of these unchanged. The two are kept apart because they answer
 * different questions: `Voice` is the voice an agent IS configured with (`AgentVoiceOut`,
 * `SetVoiceOut`), where offerability is meaningless — a stored voice is already chosen —
 * and this is a voice a client MAY choose, which on the Cartesia tier depends on a key and
 * an attested price that can both be missing (D-547).
 *
 * `tier_label` is REQUIRED on the wire: `apps/api/agents/voice_routes.py::OfferedVoiceOut`
 * fills it from `billing/rates.voice_tier_label(provider)`, which is total over the two
 * providers. This module briefly declared it optional while that field was a handoff; the
 * local extension is gone now that the generated type carries it, because two spellings of
 * one wire field is how the two drift. The picker still refuses to fall back to `provider`
 * if a name is ever missing at runtime — never by the vendor's name, which is the one name
 * it may not print.
 */
export type OfferedVoice = Schemas["OfferedVoiceOut"];

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

/**
 * The catalogue from a client's own session — every voice, each with its verdict.
 *
 * ⚠ **A HOOK OF THIS NAME WAS DELETED ONCE FOR BEING UNWIRED**, and the note that replaced
 * it said it would come back "when there is a screen and something to put on it". D-586 is
 * that screen: `c/[slug]/agents/panels/delivery.tsx` renders this list as a picker and
 * writes the choice with `useSetMyAgentVoice`. It is exported because it is called, and it
 * shares ONE options builder with the console's hook so the URL, the key and the stale
 * window cannot drift between the two realms.
 *
 * `unavailable_reason` on a row arrives in the CLIENT's language on this session and in the
 * OPERATOR's on the console's — the server picks from the caller's realm
 * (`agents/voice_routes.py::_reason_audience`), so neither surface has to know which
 * sentence it is rendering.
 */
export function useVoiceCatalogue(session: Session): UseQueryResult<VoiceCatalogue> {
  return useQuery(catalogueOptions(session));
}

/** The same catalogue from the console, through the impersonation session (see above). */
export function useTenantVoiceCatalogue(slug: string): UseQueryResult<VoiceCatalogue> {
  return useQuery({ ...catalogueOptions(viewAsSession(slug)), enabled: Boolean(slug) });
}

/**
 * Set the voice on one of the CALLER'S OWN agents — client realm, no tenant anywhere
 * (D-586). The owner and their staff; an operator reaches it by viewing as them.
 *
 * The refusals are the product here and none of them is pre-empted client-side:
 *
 * - an id outside the catalogue comes back as `unknown_voice` with the list in its
 *   remediation;
 * - a catalogue voice this deployment cannot put a client on comes back as
 *   `voice_not_available` with the actual ground in the CLIENT's language — the tier's
 *   client-facing name and the one action they have, never a vendor or one of our
 *   settings. That is the same verdict `GET /v1/agents/voices` renders as
 *   `offerable: false`, from the same function, so the picker and the write cannot
 *   disagree;
 * - a vendor refusal on the re-publish comes back as a `dependency` problem, and nothing
 *   was saved.
 *
 * All four render through `ProblemNotice` verbatim. A membership or availability check
 * duplicated on this side would be a second copy of a server rule, and the second copy is
 * the one that goes stale.
 */
export function useSetMyAgentVoice(
  session: Session,
  agentId: string,
): UseMutationResult<SetVoiceOut, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (voiceId: string) =>
      apiRequest<SetVoiceOut>(session, `/v1/agents/${agentId}/voice`, {
        method: "PATCH",
        body: { voice_id: voiceId } satisfies SetVoiceIn,
      }),
    // The pending read is where `voice.configured` and `voice.live` live, and the roster
    // row carries the agent's published state. Awaited rather than fired-and-forgotten,
    // for `publishing.ts::useAfterPublish`'s reason: a paint from the stale cache would
    // contradict the choice the client just made.
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({
          queryKey: publishingKeys.pending(session.orgSlug, agentId),
        }),
        client.invalidateQueries({ queryKey: ["agents", session.orgSlug] }),
      ]),
  });
}

/**
 * Set an agent's voice — admin realm, admin session, tenant named in the PATH.
 *
 * THE ONBOARDING DOOR, not the client one. Since D-586 a client edits their own agent's
 * voice on `PATCH /v1/agents/{agent_id}/voice` (`useSetMyAgentVoice` above); this route
 * stays because the wizard sets a voice before the client has ever signed in, and there is
 * no client session in that flow to carry it. Both call one server-side writer, so the
 * catalogue check, the offerability verdict and the in-transaction re-publish are the same
 * on either path.
 *
 * The tenant is in the URL rather than inferred from a session because an admin principal
 * has no tenant of its own. It USED TO ride
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

/* ---------------------------------------------------------------------------------------
 * THE TWO VOICE TIERS: what a human is allowed to read, and what a minute of one costs.
 *
 * D-547 gave the catalogue a second tier. Two rules govern everything below, and both are
 * about not inventing a fact the server has not sent.
 *
 * 1. **NO CLIENT-FACING SURFACE NAMES A VENDOR AS A TIER** (founder, 7 Sep 2026). `sarvam`
 *    and `cartesia` are the WIRE's vocabulary — they name the vendor, they key the lot
 *    columns and the metering, and they must keep doing so. The name a human reads is the
 *    tier LABEL ("Clear", "Studio"), defined once in Python
 *    (`apps/api/billing/rates.py::VOICE_TIER_LABELS`, read 7 Sep 2026) and carried to the
 *    browser BY THE API. A lookup table on this side would be a second definition of a
 *    client-visible name, and the day one of them changes a client meets both. So a screen
 *    that has no label renders NO tier name at all rather than falling back to the vendor.
 *
 * 2. **A RATE BELONGS TO A CREDIT LOT, NOT TO THE PRODUCT.** Under D-547 a minute is priced
 *    at the rate frozen on the purchase it draws from, and an account can hold several open
 *    lots at several rates, spent oldest-first. So there is no constant to import and no
 *    figure to derive: the rate is the OLDEST OPEN lot's rate for that tier, it is a fact
 *    about ONE account at ONE moment, and it can only arrive from the API. Absent, a screen
 *    prints nothing — a stale or invented per-minute price is the money defect hard rule 7
 *    exists for.
 * ------------------------------------------------------------------------------------- */

/** The wire's name for a voice tier: the VENDOR. Keys money and metering; never rendered. */
export type VoiceProvider = Voice["provider"];

/**
 * One voice tier as THIS account currently gets it — `VoiceTierRateOut`, generated.
 *
 * `label` is the only string here a human may see. `inr_per_min` is the rate frozen on the
 * account's oldest OPEN credit lot — the next minute's price — as the server's exact
 * decimal digits, never a number (hard rule 7); `null` is "we cannot say", which is a
 * different claim from any figure and renders as nothing at all. `further_open_lots` is how
 * many lots sit BEHIND that one, each at its own rates, so a screen can say the price
 * changes later without pretending to know when.
 *
 * **THIS WAS A LOCAL INTERFACE PLUS A `readVoiceTierRates(unknown)` VALIDATOR, AND BOTH ARE
 * GONE.** They existed while the lots API was another lane's work in flight: the field was
 * read POSITIONALLY off the pending payload and every value checked by hand, so this build
 * would compile and render correctly against a server that did not send it yet. It sends it
 * — `PendingOut.voice_tier_rates` is generated and REQUIRED — so the hand validator now
 * re-checks only what the compiler already guarantees, and two spellings of one wire
 * contract is how the weaker one comes to be believed. Callers read
 * `pending.voice_tier_rates` off the typed response.
 */
export type VoiceTierRate = Schemas["VoiceTierRateOut"];

export type VoiceTierRates = readonly VoiceTierRate[];

/** The tier row for a voice's provider, or `undefined` — the one join between the two. */
export function voiceTierRate(
  rates: VoiceTierRates | undefined,
  provider: VoiceProvider | string | null | undefined,
): VoiceTierRate | undefined {
  if (!rates || !provider) return undefined;
  return rates.find((rate) => rate.provider === provider);
}
