"use client";

/**
 * The client's own caller-notice draft (LEGAL-SURFACE F-8, D-179).
 *
 * `GET /v1/compliance/caller-notice` shipped complete — mounted, permissioned, response-
 * modelled, generated into `schema.d.ts` — and reachable by nothing. DPDP Rule 3 requires
 * a client to tell their callers, ITEM BY ITEM, what is collected and how long it is
 * kept; for a Calevate account that list is their extraction schema, their retention
 * settings and their announcement toggles, and all three live in OUR database. So the one
 * party who owes the notice is the one party who cannot see the facts it has to state.
 * Leaving the endpoint uncalled meant a client wrote that notice from memory, or did not
 * write it.
 *
 * ## A `useQuery`, unlike everything on `dataRights.ts`
 *
 * The rights endpoints next door are POSTs because the identifier IS personal data and a
 * GET writes it into access logs, proxies and browser history (hard rule 6). This one is
 * the exact opposite case and the endpoint's own docstring says so: the response is about
 * the ACCOUNT's configuration — field labels the client wrote themselves, retention days,
 * agent names — and carries no caller's number, transcript or extracted value. Nothing
 * here may become a cache key that a phone number could reach, and nothing does.
 *
 * ## `org:read`, so a support session can open it
 *
 * The endpoint deliberately asks for `org:read` rather than `org:manage`: reading your own
 * configuration back is not changing it, and `org:manage` is in `MUTATING_PERMISSIONS`,
 * which a read-only "view as client" session (D-22) cannot hold. Support is in exactly
 * that session when a client rings asking how to write their privacy notice, so this
 * module deliberately does NOT gate on `useWriteAccess` — there is nothing to write.
 *
 * ## The prose is the server's, and it is not rebuilt here
 *
 * `notice_markdown` arrives rendered. Re-deriving the wording from `collected` and
 * `retention` on the client would put the part counsel reviews outside the thing that was
 * reviewed, and would give two spellings of one legal document — the drift this repo
 * refuses. The screen renders the STRUCTURE into its own layout and hands over the
 * server's markdown verbatim for the copy.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CallerNotice = Schemas["CallerNoticeOut"];
export type CollectedItem = Schemas["CollectedItemOut"];
export type RetentionLine = Schemas["RetentionLineOut"];

export const callerNoticeKeys = {
  draft: (org: string) => ["caller-notice", org] as const,
};

/**
 * The draft, for the signed-in account.
 *
 * `staleTime` is deliberately short rather than zero: the draft is derived from settings a
 * client edits on other screens in the same sitting (an extraction field, a retention
 * window, an announcement toggle), and a notice that still describes the configuration
 * they just changed is the one failure mode that matters on a legal surface. Refetching on
 * focus is what makes "I turned that off, why does it still say that" not happen.
 */
export function useCallerNotice(
  session: Session,
): UseQueryResult<CallerNotice> {
  return useQuery({
    queryKey: callerNoticeKeys.draft(session.orgSlug),
    queryFn: () =>
      apiRequest<CallerNotice>(session, "/v1/compliance/caller-notice"),
    staleTime: 30_000,
  });
}
