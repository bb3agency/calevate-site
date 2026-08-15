"use client";

/**
 * The PLATFORM-WIDE do-not-call list — `/v1/ops/dnc/global` (SEC-COMP §3, hard rule 5).
 *
 * The client-realm twin is `./dnc.ts`, and the constants it already mirrors from the
 * server (`MAX_NUMBERS_PER_ADD`, `DNC_LIST_LIMIT`, `parsePastedNumbers`) are IMPORTED
 * here rather than restated: `compliance/dnc.py` applies one ceiling to both routes and
 * `GlobalSuppressIn.numbers` is declared `max_length=dnc.MAX_NUMBERS_PER_ADD` against
 * the same constant, so a second copy here would be a second thing to keep in step with
 * one server fact. Two ways to say one number is a defect even while they agree.
 *
 * WHAT MAKES THIS SURFACE DIFFERENT FROM THE CLIENT'S, and why it is a separate module:
 *
 * - **It is a CROSS-TENANT write.** D-107 made `scope='global'` rows visible to every
 *   tenant and honoured by every tenant's compliance gate, so one POST here changes what
 *   every client's campaign may dial. It runs on the admin realm's own session
 *   (`adminSession()`, no tenant), exactly as the platform switches do.
 * - **Both writes carry a step-up header, and the two are DIFFERENT strings.** Adding is
 *   `suppress_number_platform_wide`; lifting is `release_number_platform_wide`. The API
 *   binds them separately so a header captured for a suppression cannot release one
 *   (`national_dnd_routes.py`), and `runbooks/dnc-complaint.md` §6 prints both verbatim
 *   for the console-is-down fallback — which is why they are exported constants pinned
 *   by a test rather than string literals at the call site.
 * - **Nothing here ever holds a phone number the server did not mask.** The list route
 *   answers with `phone_masked` and the add route answers with three counts; the only
 *   full number in this module is the one an operator typed, on its way out.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import { DNC_LIST_LIMIT } from "./dnc";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** One platform-wide suppression as the console may know it — masked, never the number. */
export type GlobalDncEntry = Schemas["GlobalEntryOut"];
/** Counts, never numbers — `compliance/dnc.py` argues why the API answers this way. */
export type GlobalDncAddResult = Schemas["GlobalSuppressOut"];
/** `regulator` (an instruction from outside) or `platform_block` (our own decision). */
export type GlobalDncSource = Schemas["GlobalSuppressIn"]["source"];

export const OPS_DNC_GLOBAL_PATH = "/v1/ops/dnc/global";
export const OPS_DNC_GLOBAL_QUERY_KEY = ["admin", "ops", "dnc-global"] as const;

/**
 * Copied VERBATIM from `apps/api/compliance/national_dnd_routes.py`, like every other
 * confirmation in this console. Two constants and not one function, because the API
 * declares two constants: the direction is the part of this act an operator could get
 * wrong by replaying a header they already had, and it is the direction that decides
 * whether somebody who asked not to be called gets called.
 */
export const SUPPRESS_GLOBALLY_CONFIRMATION = "suppress_number_platform_wide";
export const RELEASE_GLOBALLY_CONFIRMATION = "release_number_platform_wide";

/**
 * Every platform-wide suppression, masked and newest first.
 *
 * Asked for at the endpoint's own ceiling, which is a CLAMP and not a page size (there is
 * no offset — see `DNC_LIST_LIMIT`), so a response this long may be a truncation. The
 * screen says which of the two it is looking at rather than calling the row count a
 * total.
 */
export function useGlobalDncList(): UseQueryResult<GlobalDncEntry[]> {
  return useQuery({
    queryKey: OPS_DNC_GLOBAL_QUERY_KEY,
    queryFn: () =>
      apiRequest<GlobalDncEntry[]>(adminSession(), `${OPS_DNC_GLOBAL_PATH}?limit=${DNC_LIST_LIMIT}`),
    // Not a live feed: it changes when an operator changes it, and both mutations below
    // invalidate this key when they do.
    staleTime: 60_000,
  });
}

export interface GlobalSuppressInput {
  numbers: string[];
  source: GlobalDncSource;
  /** WHY, in the operator's own words. Not a column — it travels into the audit stream. */
  reason: string;
}

export function useSuppressGlobally() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ numbers, source, reason }: GlobalSuppressInput) =>
      apiRequest<GlobalDncAddResult>(adminSession(), OPS_DNC_GLOBAL_PATH, {
        method: "POST",
        body: { numbers, source, reason },
        confirmAction: SUPPRESS_GLOBALLY_CONFIRMATION,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_DNC_GLOBAL_QUERY_KEY }),
  });
}

/**
 * Lift one platform-wide suppression: 204, with nothing read back.
 *
 * The row being deleted holds a phone number and the response to "stop suppressing this"
 * is the last place to repeat it — the same property `DELETE /v1/dnc/{id}` holds on the
 * client surface. The list is invalidated instead, so what the operator sees afterwards
 * is what the server now holds rather than an optimistic edit of what it used to.
 */
export function useReleaseGlobally() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) =>
      apiRequest<void>(adminSession(), `${OPS_DNC_GLOBAL_PATH}/${encodeURIComponent(entryId)}`, {
        method: "DELETE",
        confirmAction: RELEASE_GLOBALLY_CONFIRMATION,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_DNC_GLOBAL_QUERY_KEY }),
  });
}
