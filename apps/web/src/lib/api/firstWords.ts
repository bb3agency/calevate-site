"use client";

/**
 * A work's first words, heard without a phone (W1.3).
 *
 *   GET  /v1/agents/{aid}/first-words?line_id|campaign_id   `agents:read`   the words, can they be heard
 *   POST /v1/agents/{aid}/first-words  {line_id|campaign_id}  `org:manage`  the same, with the audio
 *
 * The read spends nothing, so the screen shows the play button only where a press can play.
 * A press gets the audio in parts, played one after another; together they say the words.
 */

import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type FirstWords = Schemas["FirstWordsOut"];
export type FirstWordsPart = Schemas["FirstWordsPartOut"];

const PATH = "/v1/agents/{agent_id}/first-words" satisfies keyof paths;

export interface FirstWordsWork {
  kind: "line" | "campaign";
  id: string;
}

function workField(work: FirstWordsWork): "line_id" | "campaign_id" {
  return work.kind === "line" ? "line_id" : "campaign_id";
}

/** The words and whether they can be heard here. Keyed by what the work says first now, so a
 *  rewritten script is read again. */
export function useFirstWords(
  session: Session,
  agentId: string,
  work: FirstWordsWork | null,
  version: string | null,
): UseQueryResult<FirstWords> {
  return useQuery({
    queryKey: ["first-words", session.orgSlug, agentId, work?.kind ?? null, work?.id ?? null, version] as const,
    queryFn: () => {
      const query = new URLSearchParams({ [workField(work!)]: work!.id });
      return apiRequest<FirstWords>(session, `${PATH.replace("{agent_id}", agentId)}?${query.toString()}`);
    },
    enabled: work !== null && agentId !== "",
  });
}

/** The audio, on a press. Each press that speaks something new uses one of the day's samples. */
export function useSpeakFirstWords(
  session: Session,
  agentId: string,
  work: FirstWordsWork | null,
): UseMutationResult<FirstWords, Error, void> {
  return useMutation({
    mutationFn: () =>
      apiRequest<FirstWords>(session, PATH.replace("{agent_id}", agentId), {
        method: "POST",
        body: { [workField(work!)]: work!.id },
      }),
  });
}

/** One part's audio as a playable blob. */
export function partBlob(part: FirstWordsPart): Blob {
  const bytes = Uint8Array.from(atob(part.audio), (char) => char.charCodeAt(0));
  return new Blob([bytes], { type: part.content_type });
}
