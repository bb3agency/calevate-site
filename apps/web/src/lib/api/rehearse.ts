"use client";

/**
 * Rehearse (W3.2) and What it is told (W3.15) on a campaign's or an inbound line's Script tab:
 * `POST /v1/{campaigns|inbound-lines}/{id}/rehearse` types a caller's line at the holder's
 * SAVED script (its test setup, or its engine agent while it is on calls), and
 * `GET /v1/{campaigns|inbound-lines}/{id}/script/told` reads the owner's part of what the
 * agent is told. Nothing reaches a person; a reply is inside the AI allowance.
 */

import { useMutation, useQuery } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";
import { savedMark, type ScriptHolder } from "./scriptChecks";

export type Rehearsed = components["schemas"]["RehearseOut"];
export type RehearsedAction = components["schemas"]["RehearsedActionOut"];
export type ReplyFlag = components["schemas"]["ReplyFlagOut"];
export type Told = components["schemas"]["ToldOut"];

const base = (holder: ScriptHolder) =>
  holder.kind === "campaign"
    ? `/v1/campaigns/${encodeURIComponent(holder.id)}`
    : `/v1/inbound-lines/${encodeURIComponent(holder.id)}`;

export function useRehearse(session: Session, holder: ScriptHolder) {
  return useMutation({
    mutationFn: ({ message, chatSession }: { message: string; chatSession: string | null }) =>
      apiRequest<Rehearsed>(session, `${base(holder)}/rehearse`, {
        method: "POST",
        body: { message, session: chatSession },
      }),
  });
}

export const toldKey = (org: string, holder: ScriptHolder, saved: string) =>
  ["script-told", org, holder.kind, holder.id, saved] as const;

/** Read only when `open`: the view composes the holder's config on the server. */
export function useTold(session: Session, holder: ScriptHolder, script: unknown, open: boolean) {
  return useQuery({
    queryKey: toldKey(session.orgSlug, holder, savedMark(script)),
    queryFn: () => apiRequest<Told>(session, `${base(holder)}/script/told`),
    enabled: open && script != null,
  });
}
