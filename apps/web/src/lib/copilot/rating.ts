"use client";

/**
 * Thumbs on one Pip answer (D-937): `PUT /v1/copilot/turns/{id}/vote` and its admin twin.
 * The server keeps one vote per answer, the asker's own, changeable; `null` takes it back.
 * A reason explains a thumbs down only, and the short note explains `other` only.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import { conversationKey } from "./conversation";

export type AnswerVote = NonNullable<components["schemas"]["CopilotVoteIn"]["vote"]>;
export type VoteReason = NonNullable<components["schemas"]["CopilotVoteIn"]["reason"]>;
export type VoteOut = components["schemas"]["CopilotVoteOut"];

export interface VoteChoice {
  vote: AnswerVote | null;
  reason?: VoteReason | null;
  note?: string | null;
}

/** The reasons a person can pick, in the order shown. Short words, no blame. */
export const VOTE_REASONS: readonly { value: VoteReason; label: string }[] = [
  { value: "wrong", label: "Wrong" },
  { value: "not_done", label: "Didn't do it" },
  { value: "too_slow", label: "Too slow" },
  { value: "misunderstood", label: "Didn't understand" },
  { value: "other", label: "Other" },
];

/** The server's `CopilotVoteIn.note` ceiling. */
export const MAX_NOTE = 120;

export function votePath(realm: "client" | "admin", turnId: string): string {
  const base = realm === "admin" ? "/v1/admin/copilot/turns" : "/v1/copilot/turns";
  return `${base}/${encodeURIComponent(turnId)}/vote`;
}

/** The body the server accepts: no reason on a thumbs up, no note without `other`. */
export function voteBody(choice: VoteChoice): components["schemas"]["CopilotVoteIn"] {
  const reason = choice.vote === "down" ? (choice.reason ?? null) : null;
  const note = reason === "other" ? (choice.note ?? "").trim().slice(0, MAX_NOTE) || null : null;
  return { vote: choice.vote, reason, note };
}

export function useRateAnswer(session: Session, realm: "client" | "admin", turnId: string) {
  const client = useQueryClient();
  return useMutation<VoteOut, unknown, VoteChoice>({
    mutationFn: (choice) =>
      apiRequest<VoteOut>(session, votePath(realm, turnId), {
        method: "PUT",
        body: voteBody(choice),
      }),
    // The stored page carries each answer's vote, so a reload shows what was chosen.
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: conversationKey(session.orgSlug, realm) }),
  });
}
