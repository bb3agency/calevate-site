"use client";

/**
 * THE VOICES THIS PLATFORM HAS ADDED — the Voices page's reads and its two writes (D-590).
 *
 *   GET   /v1/ops/voices          `ops:manage`, realm ADMIN — the decided voices + the form
 *   POST  /v1/ops/voices          `ops:manage`, realm ADMIN — ADD one voice by its facts
 *   PATCH /v1/ops/voices          `ops:manage`, realm ADMIN — move ONE voice's state
 *   POST  /v1/ops/voices/refresh  `ops:manage`, realm ADMIN — re-read the platform's list
 *
 * ## What this screen does, which changed on 11 Sep 2026
 *
 * ⚠ **IT USED TO SAY A NEW VOICE COULD NOT BE ADDED FROM HERE.** The premise was right —
 * the voice platform's API is read-only, and nothing here can clone or import a voice ON
 * THAT PLATFORM — and the conclusion was wrong: adding a voice to THIS product's catalogue
 * needs only the operator's facts and one read to check them. So the primary action is now
 * the Add form, and the server verifies every field against the platform's own list before
 * the voice is accepted. `CLONE_FIRST` below is the sentence that says where the facts come
 * from; it is no longer a substitute for a button.
 *
 * ## The refresh is a SECOND call, deliberately
 *
 * `POST /v1/ops/voices/refresh` re-reads the vendor and replaces the cache; it does not
 * return the table. So Refresh runs it and then invalidates this module's list key rather
 * than reading the refresh response as the new table — one source for the rows, which is
 * what stops the screen from showing a list assembled out of two different answers.
 *
 * ## Nothing here is org-scoped, and `tests/queryKeys.test.ts` checks that it is not
 *
 * Every `queryFn` mints an `adminSession()`. One vendor account serves every tenant and its
 * voice list is the same list for all of them, so a slug in the key would claim a tenancy
 * the data does not have.
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
import type { components } from "./schema";

type Schemas = components["schemas"];

/** One row of the Voices table: the voice, what an operator decided, and what it costs us. */
export type CuratedVoice = Schemas["CuratedVoiceOut"];

/** The whole cached catalogue plus the two counts and the sentence that reads it. */
export type CuratedVoices = Schemas["CuratedVoicesOut"];

/** `enabled` | `disabled` | `archived` — the server's own vocabulary, never re-declared. */
export type CurationState = CuratedVoice["state"];

export type SetCurationIn = Schemas["SetCurationIn"];
export type SetCurationOut = Schemas["SetCurationOut"];

/** The facts an operator types for ONE voice — every one of them checked on the server. */
export type AddVoiceIn = Schemas["AddVoiceIn"];
export type AddVoiceOut = Schemas["AddVoiceOut"];

/** The form's options, composed on the server — see `AddVoiceFormOut` there for why. */
export type AddVoiceForm = Schemas["AddVoiceFormOut"];
export type VoiceProviderOption = Schemas["VoiceProviderOptionOut"];

/** `operator` (typed here and verified) or `synced` (read off the platform's list). */
export type VoiceOrigin = CuratedVoice["origin"];

/** `decided` (the default) or `all` — which rows the list returns. */
export type VoiceScope = CuratedVoices["scope"];

/** What one refresh did — `VoiceCatalogueRefreshOut`, already on the wire for the ops page. */
export type VoiceRefresh = Schemas["VoiceCatalogueRefreshOut"];

export const OPS_VOICES_PATH = "/v1/ops/voices";
export const OPS_VOICES_REFRESH_PATH = "/v1/ops/voices/refresh";

/** Global, not org-scoped — see the module docstring. */
export const opsVoiceKeys = {
  list: ["admin", "ops", "voices"] as const,
  /** One key per scope: the two lists are different answers and must not share a cache. */
  scoped: (scope: VoiceScope) => ["admin", "ops", "voices", scope] as const,
};

/**
 * The table.
 *
 * NO POLL. The subject is a vendor's voice list and an operator's own decisions: it changes
 * when somebody presses a button on this screen or clones a voice on the other product, and
 * both of those are followed by a Refresh. The same judgement `useEngineLatency` makes, and
 * the opposite of the one `useHeldTenants` makes about a shared queue.
 *
 * `enabled` exists for ONE caller and one state: the screen has established that this admin
 * session does NOT hold `ops:manage`, so the request can only come back 403. It is spelled
 * `!access.refused` at the call site rather than `access.allowed`, because
 * `app/admin/access.ts`'s rule is that navigation fails open and the API is the enforcement.
 */
export function useCuratedVoices(
  enabled = true,
  scope: VoiceScope = "decided",
): UseQueryResult<CuratedVoices> {
  return useQuery({
    queryKey: opsVoiceKeys.scoped(scope),
    queryFn: () =>
      apiRequest<CuratedVoices>(adminSession(), `${OPS_VOICES_PATH}?scope=${scope}`),
    enabled,
  });
}

/**
 * ADD ONE VOICE. The screen's primary action.
 *
 * Every refusal it can return is a PROBLEM the page renders verbatim — an id the platform
 * does not list, a name that is not the platform's own, a language it is not listed under,
 * an ElevenLabs clone this product cannot price. Each names the field to fix, so nothing
 * here interprets them; `ProblemNotice` prints `detail` and `remediation` as written.
 *
 * It invalidates the CLIENT-REALM catalogue too, for `useSetVoiceCuration`'s reason: an
 * added voice changes what every client's picker offers, and an operator who adds a voice
 * and then opens a client's agent to set it would otherwise be shown the pre-add list.
 */
export function useAddVoice(): UseMutationResult<AddVoiceOut, Error, AddVoiceIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AddVoiceIn) =>
      apiRequest<AddVoiceOut>(adminSession(), OPS_VOICES_PATH, { method: "POST", body }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: opsVoiceKeys.list }),
        client.invalidateQueries({ queryKey: ["agent-voices"] }),
      ]),
  });
}

/**
 * Move one voice to a state. The three buttons are ONE mutation with three destinations.
 *
 * Three hooks would be three cache-invalidation lists and three places for the vocabulary
 * to drift from the server's `CurationState`; the server takes one route for the same
 * reason.
 *
 * **IT INVALIDATES THE CLIENT-REALM VOICE CATALOGUE TOO**, and that is the half a reviewer
 * should check. Enabling a voice here changes what every client's picker offers
 * (`GET /v1/agents/voices`, cached under `voiceKeys.catalogue` with a 30-minute stale
 * window), and an operator who enables a voice and then opens a client's agent to set it
 * would otherwise be shown the pre-enable list for half an hour. The key is imported rather
 * than retyped so the two cannot drift.
 */
export function useSetVoiceCuration(): UseMutationResult<SetCurationOut, Error, SetCurationIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SetCurationIn) =>
      apiRequest<SetCurationOut>(adminSession(), OPS_VOICES_PATH, { method: "PATCH", body }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: opsVoiceKeys.list }),
        client.invalidateQueries({ queryKey: ["agent-voices"] }),
      ]),
  });
}

/**
 * Re-read the voice platform's own catalogue into the cache, then reload the table.
 *
 * The response is REPORTED to the operator (it carries `note`, and a partial or refused
 * sync is a fact they have to see) but it is never used as the rows — see the module
 * docstring.
 */
export function useRefreshVoiceCatalogue(): UseMutationResult<VoiceRefresh, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<VoiceRefresh>(adminSession(), OPS_VOICES_REFRESH_PATH, { method: "POST" }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: opsVoiceKeys.list }),
        client.invalidateQueries({ queryKey: ["agent-voices"] }),
      ]),
  });
}

/**
 * WHERE A NEW VOICE ACTUALLY COMES FROM — the sentence this page prints where another
 * console would put an "Add voice" button.
 *
 * It is copy rather than a comment because the operator reading the screen is the person
 * who needs it, and because the alternative is them concluding the feature is missing. Both
 * routes named are the voice platform's own documented flows: import by voice id (with an
 * optional connected-account toggle for a voice created on your own provider account), or
 * clone from a 1-2 minute audio sample.
 *
 * It names no vendor product page and no URL: this console names the vendor
 * (`publicVendorNames.test.ts` exempts `src/app/admin` on purpose — an operator installs
 * that key and reads that invoice), but a URL in copy is a thing that rots silently.
 */
export const CLONE_FIRST =
  "Clone or import the voice in the voice platform's Voice Lab first — that is where its " +
  "voice id and its name come from. Then type them here: we check every field against " +
  "that platform's own list before the voice is added, so a voice that would fail on a " +
  "call is refused on this screen instead.";

/**
 * The five fields, with WHERE IN THE VOICE LAB each value is found.
 *
 * Hints rather than placeholders: a placeholder disappears the moment the operator types,
 * which is exactly when they are least sure they typed the right thing. The `provider` and
 * `languages` options are NOT here — they come from the server's `form`, because which
 * providers exist and which languages this product sells are facts with one source.
 */
export const ADD_FIELD_HINTS = {
  provider: "Who you cloned the voice on. Pick the same one you chose in the Voice Lab.",
  tts_model: "The speech model this product runs for that provider. Usually only one.",
  engine_voice_id:
    "The voice's ID in the Voice Lab — the provider-specific identifier, not its name. " +
    "For a cloned voice this is a long generated string.",
  label:
    "The NAME the Voice Lab shows for it, exactly. This travels to the engine on every " +
    "publish, so it has to match character for character (case and spacing are forgiven).",
  languages:
    "Which of this product's languages the voice should be offered for. We check each " +
    "one against the languages the platform lists it under.",
} as const;

/** The three verbs, in the order the table offers them. Labels live with the state. */
export const CURATION_ACTIONS: readonly { state: CurationState; label: string }[] = [
  { state: "enabled", label: "Enable" },
  { state: "disabled", label: "Disable" },
  { state: "archived", label: "Archive" },
];

/**
 * What each state MEANS, for the badge's accessible name and the row's explanation.
 *
 * A table rather than a ternary chain because there are three states and two readers of
 * each (the badge and the confirmation sentence), and because a fourth state added on the
 * server should fail loudly here — `lookup` returns `undefined` and the row prints the bare
 * wire value rather than mislabelling it as one of these three.
 */
export const CURATION_MEANING: Record<string, string> = {
  enabled: "Offered — clients and admins can choose this voice for an agent.",
  disabled: "Not offered — nobody can choose this voice for an agent.",
  archived: "Archived — not offered, and filed away from the working list.",
};

/**
 * The sentence beside a voice the platform has stopped listing.
 *
 * A different fact from any curation state and it must read as one: this is the VENDOR's
 * statement about their own account, nothing on this console restores it, and the row is
 * kept only so the operator's decision survives if the voice comes back.
 */
export const WITHDRAWN_MEANING =
  "The voice platform no longer lists this voice on our account, so it cannot be offered " +
  "whatever state it is in here. Nothing on this page restores it; it returns if the " +
  "platform lists it again.";
