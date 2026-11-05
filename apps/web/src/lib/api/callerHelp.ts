"use client";

/**
 * Whether one agent's callers follow along on their own phone, judged from what the agent does
 * (founder, 5 Nov 2026): its script, its small steps and its campaigns.
 *
 *   GET  /v1/agents/{agent_id}/caller-help            `agents:read`; queues a first judgement
 *   POST /v1/agents/{agent_id}/caller-help/dismiss    `org:manage`, "Not now" on the Overview
 *
 * It suggests two settings that already exist, the screen guide (`PATCH .../caller-screen`,
 * D-906) and "Give callers time" (`POST .../call-handling/give-callers-time`, D-907), and
 * switches neither on. `useTurnOnCallerHelp` is the Overview's one button for both.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { agentKeys } from "./agents";
import { callHandlingKeys, callerHelpKeys } from "./callHandling";
import { apiRequest, type Session } from "./client";
import { publishingKeys } from "./publishing";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CallerHelp = Schemas["CallerHelpOut"];
export type CallerHelpItem = Schemas["CallerHelpItemOut"];

/** While a judgement is being made the read is asked again on this interval, then stops. */
const JUDGING_POLL_MS = 5000;

function judging(data: CallerHelp | undefined): boolean {
  return data?.state === "queued" || data?.state === "running";
}

export function useCallerHelp(
  session: Session,
  agentId: string,
  { enabled = true }: { enabled?: boolean } = {},
): UseQueryResult<CallerHelp> {
  return useQuery({
    queryKey: callerHelpKeys.agent(session.orgSlug, agentId),
    queryFn: () => apiRequest<CallerHelp>(session, `/v1/agents/${agentId}/caller-help`),
    enabled: enabled && Boolean(agentId),
    refetchInterval: (q) => (judging(q.state.data) ? JUDGING_POLL_MS : false),
  });
}

export function useDismissCallerHelp(
  session: Session,
  agentId: string,
): UseMutationResult<CallerHelp, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<CallerHelp>(session, `/v1/agents/${agentId}/caller-help/dismiss`, {
        method: "POST",
      }),
    onSuccess: (data) => client.setQueryData(callerHelpKeys.agent(session.orgSlug, agentId), data),
  });
}

/** Which of the two settings one press turns on. */
export interface CallerHelpTurnOn {
  screenGuide: boolean;
  giveTime: boolean;
}

/**
 * Turn on what the Overview suggests, through each setting's own write so each is audited and
 * reaches the line as it does from Settings. The screen guide goes first: "Give callers time"
 * asks "Can you see it?" only of an agent whose callers follow along on a screen
 * (`give_callers_time.nudge_phrase_for`), so the order decides the question the agent asks.
 */
export function useTurnOnCallerHelp(
  session: Session,
  agentId: string,
): UseMutationResult<void, Error, CallerHelpTurnOn> {
  const client = useQueryClient();
  const org = session.orgSlug;
  return useMutation({
    mutationFn: async ({ screenGuide, giveTime }: CallerHelpTurnOn) => {
      if (screenGuide) {
        await apiRequest(session, `/v1/agents/${agentId}/caller-screen`, {
          method: "PATCH",
          body: { enabled: true },
        });
      }
      if (giveTime) {
        await apiRequest(session, `/v1/agents/${agentId}/call-handling/give-callers-time`, {
          method: "POST",
        });
      }
    },
    // Settled, not success: when the second write fails the first one still happened.
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: agentKeys.all(org) }),
        client.invalidateQueries({ queryKey: agentKeys.one(org, agentId) }),
        client.invalidateQueries({ queryKey: callHandlingKeys.agent(org, agentId) }),
        client.invalidateQueries({ queryKey: callHandlingKeys.organization(org) }),
        client.invalidateQueries({ queryKey: publishingKeys.pending(org, agentId) }),
        client.invalidateQueries({ queryKey: callerHelpKeys.agent(org, agentId) }),
      ]),
  });
}
