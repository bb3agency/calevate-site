"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type CallDetail, type Session } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";

type CallTranslation = components["schemas"]["CallTranslationOut"];

/**
 * "Try again" for a call's English (`POST /v1/calls/{id}/translation`).
 *
 * The server is idempotent on the call's own state, so a double press queues one job and
 * no `Idempotency-Key` is needed. The answer is written straight into the cached call, so
 * the screen shows "English is being prepared" at once and `useCall`'s poll takes over.
 */
export function useRetryEnglish(session: Session, callId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<CallTranslation>(session, `/v1/calls/${callId}/translation`, { method: "POST" }),
    onSuccess: (answer) => {
      client.setQueryData<CallDetail>(queryKeys.call(session.orgSlug, callId), (call) =>
        call ? { ...call, translation_state: answer.translation_state } : call,
      );
      void client.invalidateQueries({ queryKey: queryKeys.call(session.orgSlug, callId) });
    },
  });
}

/** Which words the page shows: as they were spoken, or in English. */
export type CallView = "original" | "english";

/**
 * Where the page opens: the words as they were spoken, in the call's own language, with
 * English one press away (founder, 25 Oct 2026, D-887). Opening on English put the caller's
 * Telugu into English on a reviewer's first read, so a translation stood in for what was
 * said. The summary follows the same switch, so it opens in the call's language too, and
 * says so where only an English one exists. Nothing is stored: a reader's choice holds for
 * the visit, and the next call opens as spoken again.
 */
export function initialView(): CallView {
  return "original";
}
