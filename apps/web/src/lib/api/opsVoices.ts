"use client";

/**
 * WHICH VOICES THIS PLATFORM OFFERS — the Voices page's reads and its one write (D-588).
 *
 *   GET   /v1/ops/voices          `ops:manage`, realm ADMIN — every synced voice + state
 *   PATCH /v1/ops/voices          `ops:manage`, realm ADMIN — move ONE voice's state
 *   POST  /v1/ops/voices/refresh  `ops:manage`, realm ADMIN — re-read the platform's list
 *
 * ## What this screen can and cannot do, which is the whole reason it reads the way it does
 *
 * **A NEW VOICE CANNOT BE ADDED FROM HERE, AND NOT BECAUSE NOBODY BUILT IT.** The voice
 * platform's API is READ-ONLY — two GET routes, no create, update or delete for a voice
 * anywhere in it. A voice is added in that platform's own Playground, by importing a voice
 * id or cloning a 1-2 minute sample. So this module offers a Refresh and three curation
 * verbs, and `ADD_A_VOICE` below is the sentence the page prints instead of an Add button:
 * an operator hunting for one is an operator we sent to the wrong product.
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

/** What one refresh did — `VoiceCatalogueRefreshOut`, already on the wire for the ops page. */
export type VoiceRefresh = Schemas["VoiceCatalogueRefreshOut"];

export const OPS_VOICES_PATH = "/v1/ops/voices";
export const OPS_VOICES_REFRESH_PATH = "/v1/ops/voices/refresh";

/** Global, not org-scoped — see the module docstring. */
export const opsVoiceKeys = { list: ["admin", "ops", "voices"] as const };

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
export function useCuratedVoices(enabled = true): UseQueryResult<CuratedVoices> {
  return useQuery({
    queryKey: opsVoiceKeys.list,
    queryFn: () => apiRequest<CuratedVoices>(adminSession(), OPS_VOICES_PATH),
    enabled,
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
export const ADD_A_VOICE =
  "New voices are added in the voice platform's own Playground — import one by its voice " +
  "id, or clone one from a 1-2 minute audio sample. Then press Refresh here and enable it.";

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
