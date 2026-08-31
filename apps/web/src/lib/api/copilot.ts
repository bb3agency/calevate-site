"use client";

/**
 * `POST /v1/copilot/confirm` — the one call in this console that carries out a change the
 * assistant proposed.
 *
 * ## Why this lives here and `stream.ts` does not
 *
 * The ask route is a stream, so it cannot go through `apiRequest` (which reads a whole
 * body and resolves once) and `lib/copilot/stream.ts` says so at its top. Confirm is an
 * ordinary POST with an ordinary JSON answer, so it takes the ordinary door: `apiRequest`,
 * the generated types, one refusal shape the console already renders. A second hand-rolled
 * `fetch` beside the first would have been the drift the convention exists to stop.
 *
 * ## The body is ONE FIELD, and that is the security property
 *
 * Every parameter of the change — the account, the person, the tool, the lead or campaign
 * id, the target status — is inside the token's signature (`apps/api/copilot/
 * write_tools.py`). So there is nothing here for a browser to edit and nothing for this
 * module to compose: it passes back the string it was given. A mutation that also sent the
 * target would be a mutation that could disagree with the sentence the person read.
 *
 * ## No `Idempotency-Key`, deliberately
 *
 * The server burns the proposal's `jti` in Redis BEFORE executing, which is the stronger
 * guarantee: the header stops one client retrying one request, the burn stops one DECISION
 * being submitted twice by any means — a second tab holding the same token included. A key
 * here would be ceremony over a guard that already holds.
 */

import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CopilotConfirmIn = Schemas["CopilotConfirmIn"];
export type CopilotConfirmOut = Schemas["CopilotConfirmOut"];

export const COPILOT_CONFIRM_PATH = "/v1/copilot/confirm";

/**
 * What each write tool has just changed, in the cache keys the EQUIVALENT BUTTON already
 * invalidates.
 *
 * Copied from the mutation beside each button rather than re-reasoned, for the same reason
 * the server's executors call the console's own service functions: a confirmed change and
 * a clicked one alter the same rows, so a screen that refreshed for one and not the other
 * would be this console disagreeing with itself about what just happened.
 *
 * - `lead_set_status` → `useEditLead` (`lib/api/leads.ts`): the list, the dashboard, the
 *   lead and its timeline. The single lead's key is `["lead", org, id]`, and a prefix
 *   invalidation on `["lead", org]` covers it without this module having to trust that
 *   `object_id` is the lead — it is, but the prefix is free and does not depend on it.
 * - `dnc_add` → `useAddDncNumbers`, plus the lead surfaces: a suppressed number changes
 *   what the leads screen may dial, and the recall D-428(b) enqueues moves the campaign
 *   progress a person is watching.
 * - `campaign_pause` → `usePauseCampaign`: the campaign and the list that carries status.
 *
 * Keyed by a WIRE STRING, so it is read through `lookup` (UX-DOCTRINE §10) — and the miss
 * is not silent. A tool this browser has not learned about has still changed something,
 * and the honest response to "I do not know what moved" is to refetch everything on
 * screen rather than to leave a stale figure that looks authoritative.
 */
const INVALIDATES: Record<string, readonly string[][]> = {
  lead_set_status: [["leads"], ["lead"], ["lead-timeline"], ["lead-facets"], ["dashboard"]],
  dnc_add: [["dnc"], ["leads"], ["lead"], ["campaign"], ["campaigns"]],
  campaign_pause: [["campaign"], ["campaigns"], ["dashboard"]],
};

export function refreshAfterConfirm(
  client: QueryClient,
  orgSlug: string,
  tool: string,
): void {
  const keys = lookup(INVALIDATES, tool);
  if (keys === undefined) {
    void client.invalidateQueries();
    return;
  }
  for (const key of keys) {
    void client.invalidateQueries({ queryKey: [...key, orgSlug] });
  }
}

/**
 * Confirm one proposal. Takes the token and nothing else; returns what the change did.
 *
 * `applied: false` with a 200 is a REAL ANSWER and not a failure — the world was already
 * in the requested state, and `detail` says which of the two happened. The card renders
 * that sentence rather than deciding for itself what "success" looked like.
 *
 * The mutation is deliberately NOT retried: `retry` defaults to 0 for mutations in
 * TanStack Query, and it must stay there. A retry would re-post a token whose `jti` the
 * first attempt may already have burned, so the second attempt's answer would be
 * "already confirmed" — a refusal about our own retry, shown to a person whose change
 * actually succeeded.
 */
export function useConfirmProposal(session: Session) {
  const client = useQueryClient();
  return useMutation<CopilotConfirmOut, unknown, string>({
    mutationFn: (token: string) =>
      apiRequest<CopilotConfirmOut>(session, COPILOT_CONFIRM_PATH, {
        method: "POST",
        body: { token } satisfies CopilotConfirmIn,
      }),
    onSuccess: (result) => {
      // Only when something MOVED. `applied: false` means the row was already in that
      // state, so there is nothing on screen that has gone stale, and refetching the
      // leads table to learn that would be a round trip for no change.
      if (result.applied) refreshAfterConfirm(client, session.orgSlug, result.tool);
    },
  });
}
