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
 * Where the page opens: English when the call's English is ready, because the owner reads
 * English and the summary has always opened in it (founder decision 4); otherwise the words
 * as spoken, which are complete and need nothing to arrive.
 */
export function initialView(call: Pick<CallDetail, "translation_state">): CallView {
  return call.translation_state === "ready" ? "english" : "original";
}
