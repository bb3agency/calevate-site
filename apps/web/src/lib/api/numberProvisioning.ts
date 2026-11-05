"use client";

/**
 * A number the client holds: which agent answers it (`POST /v1/numbers/{id}/assign`).
 *
 * Clients buy numbers in their own business name, in their own workspace (D-693, the
 * phone-number screen's own-numbers flow), so the routes that browsed and bought through
 * Calevate are retired and nothing here buys.
 */

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { agentKeys } from "./agents";
import { agreementsKey } from "./agreements";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

/** THE ONE PLACE A ROUTE IS SPELLED — `router = APIRouter(prefix="/v1/numbers")`. */
export const PATHS = {
  assign: (numberId: string) => `/v1/numbers/${numberId}/assign`,
} as const;

/** Held, and not usable until the holder's identity is verified. */
export const NOT_ACTIVATED_CODE = "number_not_activated";

/** What a number is for, when it is given to an agent. */
export type CallDirection = "inbound" | "outbound" | "both";

/** What the voice platform was TOLD, so a binding that failed is not reported as one that worked. */
export type NumberAssigned = components["schemas"]["AssignOut"];

/**
 * Point a number at an agent, or at nobody — and tell the voice platform in the same
 * request.
 *
 * This binding is what makes a number the line an agent answers and the caller ID a
 * campaign dials from, so a campaign whose number is bound elsewhere is refused at
 * launch: every campaign check is invalidated with it, broadly rather than by campaign,
 * because this module cannot know which of them dials from this number.
 *
 * The readiness screen goes with it, so the agreements screen opened next never shows the
 * account as it stood before the binding.
 */
export function useAssignNumber(
  session: Session,
): UseMutationResult<
  NumberAssigned,
  Error,
  { numberId: string; agentId: string | null; direction: CallDirection | null }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ numberId, agentId, direction }) =>
      apiRequest<NumberAssigned>(session, PATHS.assign(numberId), {
        method: "POST",
        body: { agent_id: agentId, direction },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign-numbers", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["campaign-check", session.orgSlug] });
      void client.invalidateQueries({ queryKey: agreementsKey(session.orgSlug) });
      // The roster's "Answers N numbers" and each agent's own number count.
      void client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) });
      void client.invalidateQueries({ queryKey: agentKeys.allDetails(session.orgSlug) });
    },
  });
}
