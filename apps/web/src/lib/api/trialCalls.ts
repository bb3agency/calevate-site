"use client";

/**
 * The client's free-trial panel and its test calls (D-697).
 *
 * `GET /v1/trial` says whether this account is on a free trial and, if so, its days and
 * minutes left and today's test calls against the daily cap. `POST /v1/trial/calls` places
 * one test call from an agent to a number the client types.
 */

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TrialPanel = Schemas["TrialPanelOut"];
export type TrialCallResult = Schemas["TrialCallOut"];

export function trialPanelKey(slug: string) {
  return ["trial", slug];
}

export function useTrialPanel(session: Session, enabled = true): UseQueryResult<TrialPanel> {
  return useQuery({
    queryKey: trialPanelKey(session.orgSlug),
    queryFn: () => apiRequest<TrialPanel>(session, "/v1/trial"),
    enabled,
  });
}

/**
 * Place one test call. ONE `Idempotency-Key` PER ATTEMPT, held until an answer, the rule
 * `useCallLead` follows: a second press after a lost response is answered from the first
 * rather than ringing the person a second time.
 */
export function usePlaceTrialCall(session: Session) {
  const client = useQueryClient();
  const held = useRef(new Map<string, string>());
  const attemptOf = (agentId: string, number: string) => JSON.stringify([agentId, number]);
  return useMutation({
    mutationFn: ({ agentId, number }: { agentId: string; number: string }) => {
      const attempt = attemptOf(agentId, number);
      const key = held.current.get(attempt) ?? crypto.randomUUID();
      held.current.set(attempt, key);
      return apiRequest<TrialCallResult>(session, "/v1/trial/calls", {
        method: "POST",
        body: { agent_id: agentId, number },
        idempotencyKey: key,
      });
    },
    onSuccess: (_result, { agentId, number }) => {
      held.current.delete(attemptOf(agentId, number));
      void client.invalidateQueries({ queryKey: trialPanelKey(session.orgSlug) });
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
    },
  });
}
