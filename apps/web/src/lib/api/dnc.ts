"use client";

/**
 * Do-not-call hooks (SEC-COMP §3, hard rule 5).
 *
 * The API's shapes here are compliance decisions, not defaults, and this module keeps
 * them intact rather than smoothing them into something more convenient:
 *
 * - **Adding returns COUNTS, never numbers.** `AddNumbersOut` is three integers. There
 *   is no per-number result to render and there is not meant to be — who asked us to
 *   stop calling them is itself sensitive, so the response, the log line and the audit
 *   row all carry counts only (`compliance/dnc.py`).
 * - **Checking is a MUTATION, not a query.** The endpoint is a POST because the phone
 *   number IS the personal data and a GET writes it into access logs, proxies and
 *   browser history. A `useQuery` would undo half of that by putting the number in a
 *   cache key that outlives the answer, so the check is a mutation with a result the
 *   screen holds only as long as it is on screen.
 * - **`removable` comes from the server.** `is_removable()` is the ONE definition of
 *   "may this be undone here" (global entries: no; consumer opt-outs: no). The screen
 *   renders that flag rather than re-deriving the rule, so the list can never grow a
 *   button the endpoint refuses.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type DncEntry = Schemas["DncEntryOut"];
export type DncAddResult = Schemas["AddNumbersOut"];
export type DncCheckResult = Schemas["CheckOut"];
export type DncSource = Schemas["AddNumbersIn"]["source"];

/** Mirrors `dnc.MAX_NUMBERS_PER_ADD`; over it the API answers 422, so we stop first. */
export const MAX_NUMBERS_PER_ADD = 2000;

/**
 * Mirrors `dnc.MAX_LIST` — and it is the CEILING, not a page size: the endpoint clamps
 * to it (`min(limit, MAX_LIST)`) and there is no offset, so a list that comes back this
 * long may be a truncation rather than the whole account.
 *
 * Exported because the screen has to say which of those it is looking at. Counting the
 * rows and calling the answer "how many numbers you have suppressed" is the same defect
 * the Leads table fixed when its stage tally counted the loaded page: a number that is a
 * statement about our query, read as a statement about the client's business.
 */
export const DNC_LIST_LIMIT = 500;

export const dncKeys = {
  list: (org: string) => ["dnc", org] as const,
};

export function useDncList(session: Session): UseQueryResult<DncEntry[]> {
  return useQuery({
    queryKey: dncKeys.list(session.orgSlug),
    queryFn: () => apiRequest<DncEntry[]>(session, `/v1/dnc?limit=${DNC_LIST_LIMIT}`),
    // Suppression is not a live feed — it changes when someone adds to it, and the
    // mutations below invalidate this key when they do.
    staleTime: 60_000,
  });
}

export function useAddDncNumbers(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ numbers, source }: { numbers: string[]; source: DncSource }) =>
      apiRequest<DncAddResult>(session, "/v1/dnc", {
        method: "POST",
        body: { numbers, source },
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: dncKeys.list(session.orgSlug) }),
  });
}

/**
 * A mutation on purpose — see the module note. The answer is returned to the caller
 * and deliberately not cached against the number that produced it.
 */
export function useCheckDncNumber(session: Session) {
  return useMutation({
    mutationFn: (phone: string) =>
      apiRequest<DncCheckResult>(session, "/v1/dnc/check", { method: "POST", body: { phone } }),
  });
}

/**
 * 204, with nothing read back — and on this endpoint that is a compliance property, not
 * a convenience. The row being deleted holds a phone number, and the response to "please
 * forget this" is the last place to repeat it; the `{"status": "removed"}` it used to
 * return said nothing a 2xx on a DELETE did not. The list is invalidated instead.
 */
export function useRemoveDncEntry(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) =>
      apiRequest<void>(session, `/v1/dnc/${entryId}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: dncKeys.list(session.orgSlug) }),
  });
}

/**
 * A pasted list → the array the API expects.
 *
 * Bulk paste is the real workflow: someone has a column from a spreadsheet, a WhatsApp
 * message from the front desk, or a comma-separated line. So split on line breaks,
 * commas, semicolons and tabs — and deliberately NOT on spaces, because `+91 98765
 * 43210` is one number and splitting it would report three malformed ones.
 *
 * Values are otherwise passed through UNTOUCHED: `normalize_phone` on the server is
 * the one authority on what a number is, and a browser that "fixes" a country code is
 * a browser that guesses. Exact duplicates are collapsed so the count on screen means
 * "distinct numbers you pasted".
 */
export function parsePastedNumbers(text: string): string[] {
  const seen = new Set<string>();
  for (const raw of text.split(/[\n\r,;\t]+/)) {
    const value = raw.trim();
    if (value) seen.add(value);
  }
  return [...seen];
}
