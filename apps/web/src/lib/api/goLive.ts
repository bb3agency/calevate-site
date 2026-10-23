"use client";

/**
 * The go-live guide after the first payment (D-859): `/v1/go-live`.
 *
 * The server holds where the owner stands: its agents' move into the account's own calling
 * set-up (row by row, as the worker moves them), the business check, the number and whether any
 * agent is taking calls. The move is polled while it runs, so the checklist ticks as each agent
 * lands; nothing on the screen is timed for effect.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type GoLive = Schemas["GoLiveOut"];
export type GoLiveAgentMove = Schemas["AgentMoveOut"];
export type GoLiveStep = GoLive["current"];

export const GO_LIVE_PATH = "/v1/go-live";

/** Each agent's move is one republish, seconds apart; a slower poll would tick them in a lump. */
const MOVE_POLL_MS = 3_000;
/** A business check or a number approval is done by people or the phone network: minutes. */
const REVIEW_POLL_MS = 20_000;

export function goLiveKey(slug: string) {
  return ["go-live", slug] as const;
}

export function isMoving(guide: GoLive | undefined): boolean {
  return guide?.move.state === "moving" || guide?.move.state === "waiting_for_account";
}

/** How often to read the guide again: while agents move, and while a check is out. */
export function pollMs(guide: GoLive | undefined): number | false {
  // An account owed no guide (it has not paid) has nothing moving; nor does a finished one.
  if (guide === undefined || guide.owed_at === null || (guide.finished_at ?? null) !== null) return false;
  if (isMoving(guide)) return MOVE_POLL_MS;
  if (guide.verify === "in_review" || guide.number === "waiting_approval") return REVIEW_POLL_MS;
  return false;
}

export function useGoLive(session: Session, enabled = true): UseQueryResult<GoLive> {
  return useQuery({
    queryKey: goLiveKey(session.orgSlug),
    queryFn: () => apiRequest<GoLive>(session, GO_LIVE_PATH),
    enabled,
    refetchInterval: (query) => pollMs(query.state.data),
  });
}

function useGoLiveMark(session: Session, marker: "finish" | "dismiss") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<GoLive>(session, `${GO_LIVE_PATH}/${marker}`, { method: "POST" }),
    onSuccess: (next) => client.setQueryData(goLiveKey(session.orgSlug), next),
  });
}

export function useFinishGoLive(session: Session) {
  return useGoLiveMark(session, "finish");
}

export function useDismissGoLive(session: Session) {
  return useGoLiveMark(session, "dismiss");
}
