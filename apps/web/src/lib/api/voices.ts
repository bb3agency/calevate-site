"use client";

/**
 * The voice catalogue and the one write that uses it (one Bulbul v3 quality; personas).
 *
 *   GET   /v1/agents/voices                                     `agents:read`, realm ANY
 *   PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice `agents:write`, realm ADMIN
 *
 * That split is D-21's and it decides the shape of this module: only we may change a
 * voice, so there is deliberately no client-realm setter here — the same rule `agents.ts`
 * and `publishing.ts` already follow, that a button which could only ever 403 is worse
 * than no button.
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

import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession, viewAsSession } from "./admin";
import { apiRequest, type Session } from "./client";
import { usePublishingRefresh } from "./publishing";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One catalogue entry: the id we send the engine, plus what an operator needs to choose. */
export type Voice = Schemas["Voice"];

/**
 * A catalogue row AS THE LISTING ANSWERS IT — `Voice` plus this deployment's verdict on it.
 *
 * It is a SUPERSET of `Voice` on the wire, not an envelope, so anything that renders a
 * `Voice` renders one of these unchanged. The two are kept apart because they answer
 * different questions: `Voice` is the voice an agent IS configured with (`AgentVoiceOut`,
 * `SetVoiceOut`), where offerability is meaningless — a stored voice is already chosen —
 * and this is a voice a client MAY choose, which on the Cartesia tier depends on a key and
 * an attested price that can both be missing (D-547).
 */
export type OfferedVoice = Schemas["OfferedVoiceOut"] & {
  /**
   * THE TIER'S CLIENT-FACING NAME — "Clear", "Studio" — and the only name of a voice
   * quality a human may read (founder, 7 Sep 2026; see the tier section at the foot of
   * this module). It is `apps/api/billing/rates.py::voice_tier_label(provider)`, sent per
   * row so this side never keeps a second copy of a client-visible name.
   *
   * ⚠ **OPTIONAL BECAUSE IT IS NOT ON THE WIRE YET**: `OfferedVoiceOut` does not carry it
   * in this build's schema, and adding it is a handoff (`agents/voice_offer.py` and the
   * response model belong to another lane). Optional is the honest type for a field an
   * older API build does not send, and the picker groups by whatever it is given — never
   * by `provider`, which names the vendor.
   */
  tier_label?: string | null;
};

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

/*
 * THERE IS NO CLIENT-REALM HOOK, and the module docstring above used to imply otherwise.
 *
 * `useVoiceCatalogue(session)` existed and nothing called it. `catalogueOptions` stays
 * because the console's `useTenantVoiceCatalogue` is built from it; the client-realm
 * wrapper is gone until there is a screen and something to put on it.
 */

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
 * One voice tier as THIS account currently gets it.
 *
 * `label` is the only string here a human may see. `inr_per_min` is the rate frozen on the
 * account's oldest OPEN credit lot — the next minute's price — as the server's exact
 * decimal digits, never a number (hard rule 7); `null` is "we cannot say", which is a
 * different claim from any figure and renders as nothing at all. `further_open_lots` is how
 * many lots sit BEHIND that one, each at its own rates, so a screen can say the price
 * changes later without pretending to know when.
 */
export type VoiceTierRate = {
  provider: VoiceProvider;
  label: string;
  inr_per_min: string | null;
  further_open_lots: number;
};

export type VoiceTierRates = readonly VoiceTierRate[];

/** The tier row for a voice's provider, or `undefined` — the one join between the two. */
export function voiceTierRate(
  rates: VoiceTierRates | undefined,
  provider: VoiceProvider | string | null | undefined,
): VoiceTierRate | undefined {
  if (!rates || !provider) return undefined;
  return rates.find((rate) => rate.provider === provider);
}

/**
 * The field this seam reads out of `GET /v1/agents/{agent_id}/pending`.
 *
 * ⚠ **NOT ON THE WIRE YET** — the lots API is another lane's, in flight as this is written,
 * and the field is reported as a handoff rather than guessed at. Read positionally and
 * VALIDATED rather than declared on `PendingState`, so that (a) this build compiles and
 * renders correctly against an API that does not send it, and (b) the moment the server
 * starts sending it every screen below lights up with no second edit — the alternative was
 * a prop nobody passes, which is the half-wired defect the quality bar names.
 */
export const VOICE_TIER_RATES_FIELD = "voice_tier_rates";

/** An exact decimal, unsigned, at most four places — `NUMERIC(12,4)` as JSON sends it.
 *  A second spelling of `rateCard.ts`'s private `MONEY_STRING`; hoisting the two into one
 *  money module is a handoff, because that file belongs to another lane this session. */
const MONEY_STRING = /^\d+(\.\d{1,4})?$/;

const PROVIDERS: readonly string[] = ["sarvam", "cartesia"];

/**
 * The tier rates carried by a pending payload, or `undefined` if it carries none we trust.
 *
 * Validated at the seam for `isRateCard`'s reason, and the stakes here are the same: every
 * value below reaches a client's screen as a PRICE. A row missing a label, or carrying a
 * rate that is not an exact decimal string, is treated exactly like an API that said
 * nothing — the whole set is dropped rather than half-rendered, because a picker showing a
 * price on one tier and a blank on the other reads as "that one is free".
 *
 * `unknown` in, not `PendingState`: the caller hands over the response body it already has
 * and this decides whether the field is there and sound, so no screen writes a cast.
 */
export function readVoiceTierRates(payload: unknown): VoiceTierRates | undefined {
  if (typeof payload !== "object" || payload === null) return undefined;
  const raw = (payload as Record<string, unknown>)[VOICE_TIER_RATES_FIELD];
  if (!Array.isArray(raw) || raw.length === 0) return undefined;
  const rates: VoiceTierRate[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) return undefined;
    const row = entry as Record<string, unknown>;
    if (typeof row.provider !== "string" || !PROVIDERS.includes(row.provider)) return undefined;
    if (typeof row.label !== "string" || row.label === "") return undefined;
    const rate = row.inr_per_min;
    if (rate !== null && (typeof rate !== "string" || !MONEY_STRING.test(rate))) return undefined;
    const behind = row.further_open_lots;
    if (typeof behind !== "number" || !Number.isInteger(behind) || behind < 0) return undefined;
    rates.push({
      provider: row.provider as VoiceProvider,
      label: row.label,
      inr_per_min: rate,
      further_open_lots: behind,
    });
  }
  return rates;
}
