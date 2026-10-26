"use client";

/**
 * The phone swipe's actions and the desktop ⋯ menu's (D-869). The API side,
 * `apps/api/crm/swipe.py`, says which existing route each other action uses.
 *
 * - Swipe right, "Call back now": `useCallLead` (`hooks.ts`), unchanged.
 * - Lead status (won / lost / follow-up): `useMarkLeadStatus`. Its UNDO sends the previous
 *   status with `expectedStatus` set to the one being undone; the server answers 409
 *   `INVALID_STATUS_TRANSITION` if a colleague moved the lead since, and nothing changes.
 *   The lead statuses are fixed (`new contacted interested hot won lost`); the swipe's
 *   "follow-up" is `interested`.
 * - Call mark (resolved / needs you): `useMarkCallFollowUp`; undo with `expectedState`.
 * - "Call back later": `useScheduleCallback`, between 09:00 and 21:00 IST. Undo is the
 *   existing cancel, `DELETE /v1/callbacks/{id}` (`callbacks.ts`).
 * - WhatsApp follow-up: `useWhatsAppOptions` (can it be sent, which approved messages) and
 *   `useSendWhatsApp`.
 *
 * The two that ring a phone or send a message hold ONE `Idempotency-Key` per attempt
 * across retries, as `useCallLead` does, so a double tap is answered rather than done twice.
 * A `blocked` status is an answer with `blocked_reason` / `reason` to show, not an error.
 */

import { useRef } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import { queryKeys } from "./hooks";
import { invalidateEditedLead } from "./leads";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CallFollowUp = Schemas["CallFollowUpOut"];
export type CallFollowUpState = NonNullable<Schemas["CallFollowUpIn"]["state"]>;
export type ScheduledCallbackResult = Schemas["ScheduleCallbackOut"];
export type WhatsAppOptions = Schemas["WhatsAppOptionsOut"];
export type WhatsAppSendResult = Schemas["WhatsAppSendOut"];
export type LeadStatus = NonNullable<Schemas["LeadUpdateIn"]["status"]>;
type Lead = Schemas["LeadOut"];

/** The swipe's three lead outcomes, as the fixed statuses they are stored as. */
export const SWIPE_LEAD_STATUS = {
  won: "won",
  lost: "lost",
  followUp: "interested",
} as const satisfies Record<string, LeadStatus>;

export const swipeKeys = {
  whatsapp: (org: string, leadId: string) => ["lead-whatsapp", org, leadId] as const,
};

function useHeldKeys() {
  const held = useRef(new Map<string, string>());
  return {
    keyFor(attempt: string): string {
      const key = held.current.get(attempt) ?? crypto.randomUUID();
      held.current.set(attempt, key);
      return key;
    },
    done(attempt: string) {
      held.current.delete(attempt);
    },
  };
}

export function useMarkLeadStatus(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      leadId,
      status,
      expectedStatus,
    }: {
      leadId: string;
      status: LeadStatus;
      /** For an undo: the status the lead must hold now. */
      expectedStatus?: LeadStatus;
    }) =>
      apiRequest<Lead>(session, `/v1/leads/${leadId}`, {
        method: "PATCH",
        body: { status, expected_status: expectedStatus },
      }),
    onSettled: (_lead, _err, { leadId }) => invalidateEditedLead(client, session.orgSlug, leadId),
  });
}

export function useMarkCallFollowUp(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      callId,
      state,
      expectedState,
    }: {
      callId: string;
      state: CallFollowUpState | null;
      /** For an undo: the mark the call must hold now (`null` = no mark). */
      expectedState?: CallFollowUpState | null;
    }) =>
      apiRequest<CallFollowUp>(session, `/v1/calls/${callId}/follow-up`, {
        method: "PUT",
        body:
          expectedState === undefined ? { state } : { state, expected_state: expectedState },
      }),
    onSettled: (_out, _err, { callId }) => {
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
      // The calls screen's log renders the follow-up mark too, under its own family.
      void client.invalidateQueries({ queryKey: queryKeys.callsLog(session.orgSlug) });
      void client.invalidateQueries({ queryKey: queryKeys.call(session.orgSlug, callId) });
    },
  });
}

export function useScheduleCallback(session: Session) {
  const client = useQueryClient();
  const keys = useHeldKeys();
  const attemptOf = (leadId: string, at: string, note?: string, agentId?: string) =>
    JSON.stringify([leadId, at, note ?? null, agentId ?? null]);
  return useMutation({
    mutationFn: ({
      leadId,
      at,
      note,
      agentId,
    }: {
      leadId: string;
      /** ISO with its offset, e.g. "2026-10-25T16:00:00+05:30"; 09:00-21:00 IST. */
      at: string;
      note?: string;
      /** Left out: the lead's agent if it places calls, else the account's first that does. */
      agentId?: string;
    }) =>
      apiRequest<ScheduledCallbackResult>(session, `/v1/leads/${leadId}/callbacks`, {
        method: "POST",
        body: { at, note, agent_id: agentId },
        idempotencyKey: keys.keyFor(attemptOf(leadId, at, note, agentId)),
      }),
    onSuccess: (_out, { leadId, at, note, agentId }) => {
      keys.done(attemptOf(leadId, at, note, agentId));
      void client.invalidateQueries({ queryKey: ["callbacks", session.orgSlug] });
    },
  });
}

export function useWhatsAppOptions(
  session: Session,
  leadId: string | undefined,
): UseQueryResult<WhatsAppOptions> {
  return useQuery({
    queryKey: swipeKeys.whatsapp(session.orgSlug, leadId ?? ""),
    queryFn: () => apiRequest<WhatsAppOptions>(session, `/v1/leads/${leadId}/whatsapp`),
    enabled: Boolean(leadId),
  });
}

export function useSendWhatsApp(session: Session) {
  const client = useQueryClient();
  const keys = useHeldKeys();
  const attemptOf = (leadId: string, templateId: string, values: string[]) =>
    JSON.stringify([leadId, templateId, values]);
  return useMutation({
    mutationFn: ({
      leadId,
      templateId,
      values,
      agentId,
    }: {
      leadId: string;
      templateId: string;
      /** One per blank of the template, in order. */
      values: string[];
      agentId?: string;
    }) =>
      apiRequest<WhatsAppSendResult>(session, `/v1/leads/${leadId}/whatsapp`, {
        method: "POST",
        body: { template_id: templateId, values, agent_id: agentId },
        idempotencyKey: keys.keyFor(attemptOf(leadId, templateId, values)),
      }),
    onSuccess: (_out, { leadId, templateId, values }) => {
      keys.done(attemptOf(leadId, templateId, values));
      void client.invalidateQueries({ queryKey: swipeKeys.whatsapp(session.orgSlug, leadId) });
    },
  });
}
