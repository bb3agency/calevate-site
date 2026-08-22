"use client";

/**
 * ONE CLIENT'S DEFAULT LANGUAGE MODEL, FROM THE OPERATOR CONSOLE — the admin realm's read
 * and write, and the rules its screen refuses a draft by before the click.
 *
 *   GET  /v1/admin/organizations/{org_id}/llm-defaults
 *   PUT  /v1/admin/organizations/{org_id}/llm-defaults   `null` = clear, back to ours
 *
 * ## Why this module exists beside `llmModels.ts` rather than inside it
 *
 * `lib/api/llmModels.ts` is the CLIENT realm's half of this feature: it reads
 * `/v1/organization/llm-defaults` with the client's own session and no id in the path,
 * because a client can only ever be looking at themselves. This is the same decision seen
 * from the console, and the two differ in the only three ways that matter — a different
 * path, a different credential, and an id the operator supplies. Merging them would mean
 * one hook that takes a session AND an org id and decides which realm it is in, which is
 * the "one bad conditional away from an admin token on a client surface" shape
 * `lib/api/admin.ts` exists to prevent (TRD §11, D-177).
 *
 * WHAT IS SHARED IS VOCABULARY, NEVER SESSION LOGIC, and that is the arrangement
 * `lib/api/admin.ts` already has with `kyc.ts`, `holds.ts` and `firstCampaign.ts`: the
 * wire SHAPES (`OrganizationLlmDefaults`, `SetOrganizationLlmDefaultIn`) and the pure
 * catalogue reads (`modelOption`, `platformDefaultOption`) are imported from the
 * client-realm module so that an operator and a client are looking at the same document
 * with the same field names; the session each hook presents is built here, from
 * `adminSession()`.
 *
 * This file briefly carried its own `platformDefaultOption`, written before that module
 * grew one. Two spellings of one rule is the drift "one way per problem" is about, and the
 * copy that survives is the one in the module both realms already import — so this one is
 * gone rather than kept in step. Note its signature: it takes the OPTION LIST, not the
 * whole document.
 *
 * The rupee comparisons come from `lib/llmRates.ts` for the same reason — it is realm-free
 * decimal arithmetic on the digits the server sent, and a second copy of it here would be
 * the one that rounds (hard rule 7).
 *
 * ## The wire types are the generated ones, and they are imported rather than restated
 *
 * This paragraph used to say `pnpm gen:api` had not run against the endpoint yet and that
 * the aliases would move to `llmModels.ts` when it did. It has run, they did, and this
 * file was already unchanged by it — which is what the arrangement was for. Nothing here
 * asserts onto a wire type (`as`), in `src/` or in `tests/`, so a generated shape that
 * differs from what was agreed fails the build rather than compiling over the difference
 * (`tests/wireFixtureGuard.test.ts`).
 *
 * ## Where the route landed, against the contract this was built to
 *
 * `apps/api/agents/llm_routes.py` mounts both verbs at the path below, on `admin:tenants`,
 * and it answers BOTH with the full `LlmDefaultsOut`. Two deltas from the four-field
 * contract this lane was handed, and both are honoured rather than noted:
 *
 * 1. **`PUT` returns the document**, so the result is typed rather than `unknown`. The
 *    screen still re-reads instead of painting from it — see `useSetAdminLlmDefault`.
 * 2. **Each option carries `is_available` / `unavailable_reason`.** A model this platform
 *    has no deployment for is refused with `llm_model_not_deployed`, and the route's own
 *    comment says a screen must show the row DISABLED with the reason rather than hide it.
 *    `adminLlmDefaultBlockReason` refuses it before the click for that reason: a control
 *    whose only outcome is a 422 is the failure `app/admin/access.ts` exists to remove.
 *    The CLIENT realm reads the same field through `llmModels.unavailableReason`, which is
 *    where the `=== false` rule (an older build reports `undefined`, and `undefined`
 *    disables nothing) is written down once for both realms.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import {
  modelOption,
  platformDefaultOption,
  type OrganizationLlmDefaults,
  type SetOrganizationLlmDefaultIn,
} from "./llmModels";

/**
 * The endpoint, spelled once.
 *
 * The `/v1` prefix is not part of the skew noted above and is not optional: `API_BASE`
 * carries no prefix and every route this console reaches is mounted under `/v1`, so the
 * contract's `/admin/organizations/…` is the shorthand `llmModels.ts` records for its own
 * path. The id is the ORGANIZATION's, which is exactly what the `[tenantId]` route segment
 * already holds — `TenantSummary.id` is the `organizations` row — so the console needs no
 * second read to call this.
 */
export function adminLlmDefaultsPath(orgId: string): string {
  return `/v1/admin/organizations/${orgId}/llm-defaults`;
}

/**
 * Admin-realm, so it is NOT org-slug-scoped in the client-realm sense — but it does hold
 * one client's row, so the org id is in the key. Deliberately distinct from
 * `llmModelKeys.organizationDefaults`: that entry is filled by a CLIENT session reading
 * its own account, and one `QueryClient` survives an operator following "View as client"
 * into a tenant and back out (D-22). Two credentials must never share a cache entry.
 */
export function adminLlmDefaultsQueryKey(orgId: string): [string, string, string] {
  return ["admin", "llm-defaults", orgId];
}

/**
 * What this client is on, what the platform is on, and what every option costs them.
 *
 * `adminSession()` with the org in the PATH, never `viewAsSession(slug)`: this is an
 * operational decision ABOUT a client rather than a document they hold, and the write
 * below carries `admin:tenants`, which is in `MUTATING_PERMISSIONS` and would be correctly
 * refused through an impersonating session (D-22). It also means the screen needs no slug
 * and can render before the tenant read lands — the same shape as `useFeatureFlags`.
 *
 * No `refetchInterval` and no `staleTime`. This moves only when somebody writes it, the
 * write invalidates this key, and the screen's whole job is to show what is on file at the
 * moment an operator decides — a poll would refetch under a form being filled in, and a
 * stale window would let two operators overwrite each other from a cached reading.
 */
export function useAdminLlmDefaults(orgId: string): UseQueryResult<OrganizationLlmDefaults> {
  return useQuery({
    queryKey: adminLlmDefaultsQueryKey(orgId),
    queryFn: () => apiRequest<OrganizationLlmDefaults>(adminSession(), adminLlmDefaultsPath(orgId)),
    enabled: Boolean(orgId),
  });
}

/**
 * Set this client's default model, or clear it back to the platform's.
 *
 * PUT states the WHOLE field — `caps.ts`'s argument, and `llmModels.ts` repeats it: `null`
 * is a real choice ("use whatever Calevate runs by default, whatever that becomes") rather
 * than "leave this alone", and a partial verb would need a third state JSON makes easy to
 * send by accident.
 *
 * **No `X-Confirm-Action`, because the contract names none**, and the credits screen puts
 * the rule plainly: a header the API ignores is a confirmation of nothing. So the
 * confirmation this act gets is the one the console can actually enforce — the typed model
 * name on the form (`adminLlmDefaultBlockReason`). If the route later publishes a
 * confirmation string it is added here, and the screen's write failures move to
 * `WriteFailure`, which is where every write that DOES send one renders them.
 *
 * No `Idempotency-Key`: the body states the whole field, so a duplicate stores the same
 * value. NOT optimistic, for `llmModels.ts`'s reason: the server may refuse this, and an
 * optimistic write shows the new price for as long as it takes to be told no — on a money
 * control, the wrong way round.
 */
export function useSetAdminLlmDefault(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SetOrganizationLlmDefaultIn) =>
      apiRequest<OrganizationLlmDefaults>(adminSession(), adminLlmDefaultsPath(orgId), {
        method: "PUT",
        body,
      }),
    // INVALIDATE rather than `setQueryData(response)`, even though the route hands back
    // the whole document. The screen has one panel of record and it should have exactly
    // one writer: a cache seeded from a mutation and then refetched anyway is two paths to
    // the same pixels, and the one that is wrong is the one nobody re-reads. `llmModels.ts`
    // invalidates for the same reason and additionally clears the agent reads, which this
    // hook cannot do — those live under a CLIENT session's keys, and an admin screen must
    // not reach into them (D-177).
    onSuccess: () => client.invalidateQueries({ queryKey: adminLlmDefaultsQueryKey(orgId) }),
  });
}

/* --- reading the three facts apart -------------------------------------------------- */

/**
 * This client's stored choice names a model the platform no longer offers.
 *
 * The feature-flag screen's "left over from an older release", pointed at a model: the row
 * is real, the console cannot price it, and hiding it is how a client stays pinned to
 * something nobody can see. Having NO choice is not this state and must not read as it.
 */
export function isRetiredChoice(defaults: OrganizationLlmDefaults): boolean {
  const chosen = defaults.default_llm_model;
  return chosen !== null && modelOption(defaults.available, chosen) === undefined;
}

/**
 * What this client will be RUNNING ON if `draft` is saved — the outcome, not the input.
 *
 * `null` only when the draft clears the choice and the platform names no default, which is
 * the one case where the console genuinely cannot say what happens next.
 */
export function projectedModel(
  draft: SetOrganizationLlmDefaultIn,
  defaults: OrganizationLlmDefaults,
): string | null {
  if (draft.default_llm_model !== null) return draft.default_llm_model;
  return platformDefaultOption(defaults.available)?.model ?? null;
}

/* --- the confirmation, and the refusal given before the click ----------------------- */

/**
 * The exact string an operator types to confirm — the model the client ENDS UP ON.
 *
 * The house idiom is a typed confirmation that names the ACT: `HALT` on the big red
 * switch, the target load-shed mode, the payment's own reference on a top-up. The credits
 * screen records why a VARIABLE string beats a fixed one — "`CREDIT` becomes muscle memory
 * within a week, and a reference is different every time, so it cannot be typed past" —
 * and that holds here with a second thing on top: the mistake available on this screen is
 * picking the wrong ROW, so transcribing the outcome double-keys the one field that
 * decides both what the client's agents think with and what their minutes cost.
 *
 * It is the OUTCOME rather than the selection, so clearing the override confirms the model
 * the client falls BACK onto rather than the word "inherit". An operator who cannot name
 * what they are falling back to has not read the screen — which is the whole point of
 * asking.
 *
 * `null` when the outcome cannot be stated, and the caller must then refuse the write
 * rather than accept a confirmation of nothing.
 */
export function adminLlmDefaultConfirmation(
  draft: SetOrganizationLlmDefaultIn,
  defaults: OrganizationLlmDefaults,
): string | null {
  return projectedModel(draft, defaults);
}

/**
 * Why this draft cannot be sent yet, or `null` when it can.
 *
 * A PREVIEW of the refusal, never the enforcement: the route validates again and the
 * screen still renders its problem+json. What this buys is that the operator is told
 * before the click instead of by a 422 — the same arrangement `flagBlockReason` has with
 * `apps/api/flags/routes.py`.
 */
export function adminLlmDefaultBlockReason(
  draft: SetOrganizationLlmDefaultIn,
  typed: string,
  defaults: OrganizationLlmDefaults,
): string | null {
  if (draft.default_llm_model === defaults.default_llm_model) {
    return draft.default_llm_model === null
      ? "This client has no choice of their own to clear — they already follow the platform default."
      : "That is already this client's own default — nothing would change.";
  }
  const picked = modelOption(defaults.available, draft.default_llm_model);
  if (draft.default_llm_model !== null && picked === undefined) {
    return "That model is not one this platform offers, so it cannot be set for a client.";
  }
  // `=== false`, never `!picked?.is_available`: an API build predating these two fields
  // reports NEITHER, and `undefined` is "this deployment does not say" — refusing on it
  // would disable every option on an older server. Only an explicit false is a refusal.
  if (picked?.is_available === false) {
    return (
      picked.unavailable_reason ??
      "This platform has no deployment behind that model yet, so it cannot be set for a client."
    );
  }
  const confirmation = adminLlmDefaultConfirmation(draft, defaults);
  if (confirmation === null) {
    return "This platform names no default model, so nobody can say what this client would fall back to. Choose a model explicitly instead.";
  }
  if (typed.trim() !== confirmation) {
    // Deliberately NOT a second copy of the field's own label ("Type X to confirm"): the
    // two sit inches apart, and one sentence printed twice reads as a rendering fault
    // rather than as a refusal. This one says what is missing and where to put it.
    return `Not confirmed yet — type ${confirmation} in the field above.`;
  }
  return null;
}
