"use client";

/**
 * `POST /v1/copilot/confirm` — the one call in this console that carries out a change the
 * assistant proposed.
 *
 * ## Why this lives here and `stream.ts` does not
 *
 * The ask route is a stream, so it cannot go through `apiRequest` (which reads a whole
 * body and resolves once); `lib/copilot/stream.ts` opens it through `openEventStream`
 * in `lib/api/client.ts` instead. Confirm is an
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

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { needsReauthentication } from "@/lib/authn/problems";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { withActionCode } from "@/lib/authn/stepUpPrompt";
import { lookup } from "@/lib/lookup";

import { undoCopilotConfirmation } from "./admin";
import { apiRequest, type Session } from "./client";
import { DNC_DEPENDENT_KEYS } from "./dnc";
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
 * - `dnc_add` / `dnc_remove` → `DNC_DEPENDENT_KEYS` (`lib/api/dnc.ts`), the list the
 *   screen's own add, remove and restore use: the lead surfaces, whose dial actions a
 *   suppressed number changes, and the campaign reads, whose launch check counts only
 *   unlisted contacts and whose progress the recall D-428(b) enqueues moves.
 * - `campaign_pause` → `usePauseCampaign`: the campaign and the list that carries status.
 *
 * Keyed by a WIRE STRING, so it is read through `lookup` (UX-DOCTRINE §10) — and the miss
 * is not silent. A tool this browser has not learned about has still changed something,
 * and the honest response to "I do not know what moved" is to refetch everything on
 * screen rather than to leave a stale figure that looks authoritative.
 */
const INVALIDATES: Record<string, readonly (readonly string[])[]> = {
  lead_set_status: [["leads"], ["lead"], ["lead-timeline"], ["lead-facets"], ["dashboard"]],
  agent_create: [["agents"], ["agent"], ["dashboard"]],
  agent_rename: [["agents"], ["agent"]],
  // D-854: the first-agent card reads these from the agents list and the knowledge read.
  agent_edit: [["agents"], ["agent"]],
  agent_capture_fields_set: [["agents"], ["agent"]],
  knowledge_facts_pin: [["kb-knows"], ["kb"]],
  // D-893 lane L5: the answer lands as a fact and closes the topic's gaps.
  knowledge_question_settle: [
    ["teach-questions"],
    ["knowledge-gaps"],
    ["kb-knows"],
    ["kb"],
    ["readiness"],
    ["script-tests"],
    ["dashboard"],
  ],
  knowledge_fact_change: [["kb-knows"], ["kb"], ["teach-questions"], ["script-tests"]],
  agent_tests_run: [["script-tests"], ["readiness"]],
  agent_test_add: [["agent-test-cases"], ["script-tests"]],
  dnc_add: DNC_DEPENDENT_KEYS,
  dnc_remove: DNC_DEPENDENT_KEYS,
  campaign_pause: [["campaign"], ["campaigns"], ["attention"], ["dashboard"]],
  // D-893: plans refresh these once they finish (`lib/copilot/plans.refreshAfterPlan`).
  leads_bulk_update: [["leads"], ["lead"], ["lead-facets"], ["dashboard"]],
  // The launch check names a missing consent provenance.
  campaign_consent_set: [["campaign"], ["campaign-check"]],
  // As `useAddContacts`: the launch check counts the contacts.
  campaign_add_leads: [["campaign"], ["campaigns"], ["campaign-check"], ["attention"]],
  callbacks_book_bulk: [["callbacks"], ["leads"], ["calls-log"]],
  calls_place_bulk: [["campaigns"], ["campaign"], ["calls-log"], ["dashboard"]],
  callback_book: [["callbacks"], ["leads"], ["calls-log"]],
  callback_reschedule: [["callbacks"], ["calls-log"]],
  // D-893 L1: each the keys its call-page, ⋯ menu or Call-backs button refreshes.
  call_back: [["calls-log"], ["calls"], ["call"], ["callback-check"], ["lead"]],
  call_follow_up_set: [["calls-log"], ["calls"], ["call"], ["leads"]],
  call_translate: [["call"]],
  lead_whatsapp_send: [["lead-whatsapp"], ["lead-timeline"], ["lead"]],
  callbacks_change_bulk: [["callbacks"], ["calls-log"], ["leads"], ["lead"]],
  // D-893 lane L2.
  dnc_restore: DNC_DEPENDENT_KEYS,
  lead_source_mapping: [["lead-sources"]],
  lead_view_save: [["lead-views"]],
  // An export changes nothing on screen; the file is the result.
  leads_export: [],
  calls_export: [],
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
/**
 * The action string a confirm sends as `X-Confirm-Action`: an admin step-up string as it
 * comes, or a client emailed-code template with `{org}` filled in with this account's slug
 * (D-893 F4: the code the console button for the same act asks for).
 */
export function confirmActionFor(session: Session, template: string | null): string | null {
  return template === null ? null : template.replaceAll("{org}", session.orgSlug);
}

/** One confirm, as the card's mutation and the plan card both send it. */
export function confirmProposal(
  session: Session,
  realm: "client" | "admin",
  template: string | null,
  token: string,
): Promise<CopilotConfirmOut> {
  const path = realm === "admin" ? ADMIN_COPILOT_CONFIRM_PATH : COPILOT_CONFIRM_PATH;
  const body = { token } satisfies CopilotConfirmIn;
  const confirmAction = confirmActionFor(session, template);
  if (confirmAction === null) {
    return apiRequest<CopilotConfirmOut>(session, path, { method: "POST", body });
  }
  // An action whose console button asks for step-up or an emailed code asks for it here
  // too (D-694, D-893). Retrying after the code is safe: the server checks it BEFORE it
  // burns the proposal token.
  return withActionCode(
    confirmAction,
    `Confirming what ${ASSISTANT_NAME} proposed.`,
    () => apiRequest<CopilotConfirmOut>(session, path, { method: "POST", body, confirmAction }),
    needsReauthentication,
  );
}

export function useConfirmProposal(
  session: Session,
  realm: "client" | "admin" = "client",
  confirmAction: string | null = null,
) {
  const client = useQueryClient();
  return useMutation<CopilotConfirmOut, unknown, string>({
    mutationFn: (token: string) => confirmProposal(session, realm, confirmAction, token),
    onSuccess: (result) => {
      // Only when something MOVED. `applied: false` means the row was already in that
      // state, so there is nothing on screen that has gone stale, and refetching the
      // leads table to learn that would be a round trip for no change.
      if (result.applied) refreshAfterConfirm(client, session.orgSlug, result.tool);
    },
  });
}

/** The admin realm's confirm door (D-694): admin actions, with the button's step-up. */
export const ADMIN_COPILOT_CONFIRM_PATH = "/v1/admin/copilot/confirm";

export type CopilotUndoOut = Schemas["CopilotUndoOut"];
export type CopilotJobOut = Schemas["CopilotJobOut"];

/** Where an Undo goes, per realm. */
export function undoPath(realm: "client" | "admin", actionId: string): string {
  const base = realm === "admin" ? "/v1/admin/copilot/actions" : "/v1/copilot/actions";
  return `${base}/${encodeURIComponent(actionId)}/undo`;
}

/**
 * Take back one action the assistant ran without a click (D-694).
 *
 * Not retried, for `useConfirmProposal`'s reason: a second post after the first landed is
 * answered "already undone", a refusal about our own retry. A `409` names why it could not
 * be undone — usually that somebody changed the record since — and is shown as it comes.
 */
export function useUndoAction(session: Session, realm: "client" | "admin") {
  const client = useQueryClient();
  return useMutation<CopilotUndoOut, unknown, string>({
    mutationFn: (actionId: string) => {
      if (realm === "client") {
        return apiRequest<CopilotUndoOut>(session, undoPath(realm, actionId), { method: "POST" });
      }
      // The admin realm's undo takes step-up (D-731), bound to the action.
      const confirmAction = undoCopilotConfirmation(actionId);
      return withActionCode(
        confirmAction,
        `Undoing something ${ASSISTANT_NAME} did.`,
        () =>
          apiRequest<CopilotUndoOut>(session, undoPath(realm, actionId), {
            method: "POST",
            confirmAction,
          }),
        needsReauthentication,
      );
    },
    onSuccess: (result) => refreshAfterConfirm(client, session.orgSlug, result.tool),
  });
}

/** How often a background job card re-reads its job while it runs. */
export const JOB_POLL_MS = 2_000;

/**
 * One background job, polled while it is queued or running and left alone once it has
 * finished (D-694). Polling rather than the job's event stream: the panel already polls
 * nothing else, and one small read every two seconds while a job runs is the D-24 shape.
 */
export function useCopilotJob(session: Session, jobId: string) {
  return useQuery<CopilotJobOut>({
    queryKey: ["copilot-job", session.orgSlug, jobId],
    queryFn: () =>
      apiRequest<CopilotJobOut>(session, `/v1/copilot/jobs/${encodeURIComponent(jobId)}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === undefined || status === "queued" || status === "running"
        ? JOB_POLL_MS
        : false;
    },
  });
}
