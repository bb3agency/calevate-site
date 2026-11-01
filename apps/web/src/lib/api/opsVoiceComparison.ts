/**
 * The blind voice comparison (D-946) — admin realm, `ops:manage`. No client is affected.
 *
 *   GET  /v1/ops/voice-comparison/setup                 Sarvam key, workspace, Cartesia ready
 *   POST /v1/ops/voice-comparison/setup                 set up Sarvam voices (step-up)
 *   GET  /v1/ops/voice-comparison/voices                the candidates of each provider
 *   GET  /v1/ops/voice-comparison/sentences             the default Telugu sentences
 *   GET  /v1/ops/voice-comparison/rounds                the latest rounds
 *   POST /v1/ops/voice-comparison/rounds                start a round
 *   GET  /v1/ops/voice-comparison/rounds/{id}           a round, blind
 *   POST /v1/ops/voice-comparison/rounds/{id}/finish    close it
 *   GET  /v1/ops/voice-comparison/rounds/{id}/summary   the reveal, once finished
 *   GET  /v1/ops/voice-comparison/rounds/{id}/export    CSV, once finished
 *   GET  /v1/ops/voice-comparison/trials/{id}/audio     one side of one pair
 *   PUT  /v1/ops/voice-comparison/trials/{id}           rate one pair
 *
 * The round as this bundle receives it names no voice and no provider: the server keeps the
 * pairing, so nothing here can leak it before the round is finished.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession, confirmedAdminRequest } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ComparisonSetup = Schemas["VoiceComparisonSetupOut"];
export type ComparisonVoices = Schemas["VoiceComparisonVoicesOut"];
export type ComparisonCandidate = Schemas["VoiceComparisonCandidateOut"];
export type ComparisonSentences = Schemas["VoiceComparisonSentencesOut"];
export type ComparisonRoundIn = Schemas["VoiceComparisonRoundIn"];
export type ComparisonRound = Schemas["VoiceComparisonRoundOut"];
export type ComparisonRounds = Schemas["VoiceComparisonRoundsOut"];
export type ComparisonTrial = Schemas["VoiceComparisonBlindTrialOut"];
export type ComparisonRateIn = Schemas["VoiceComparisonRateIn"];
export type ComparisonSummary = Schemas["VoiceComparisonSummaryOut"];

export const VOICE_COMPARISON_PATH = "/v1/ops/voice-comparison";
export const COMPARISON_SETUP_PATH = `${VOICE_COMPARISON_PATH}/setup`;
export const COMPARISON_VOICES_PATH = `${VOICE_COMPARISON_PATH}/voices`;
export const COMPARISON_SENTENCES_PATH = `${VOICE_COMPARISON_PATH}/sentences`;
export const COMPARISON_ROUNDS_PATH = `${VOICE_COMPARISON_PATH}/rounds`;
export const roundPath = (id: string) => `${COMPARISON_ROUNDS_PATH}/${id}`;
export const trialPath = (id: string) =>
  `${VOICE_COMPARISON_PATH}/trials/${id}`;

/** The confirmation the API names for the set-up (`voice_comparison_routes.py`). */
export const SETUP_CONFIRMATION = "set_up_sarvam_voices";
/** The server's limits (`ops/voice_comparison.py`), restated for the form's own hints. */
export const MAX_VOICES_PER_PROVIDER = 3;
export const MAX_PAIRS = 120;

export const voiceComparisonKeys = {
  all: ["admin", "ops", "voice-comparison"] as const,
  setup: ["admin", "ops", "voice-comparison", "setup"] as const,
  voices: ["admin", "ops", "voice-comparison", "voices"] as const,
  sentences: ["admin", "ops", "voice-comparison", "sentences"] as const,
  rounds: ["admin", "ops", "voice-comparison", "rounds"] as const,
  round: (id: string) =>
    ["admin", "ops", "voice-comparison", "rounds", id] as const,
  summary: (id: string) =>
    ["admin", "ops", "voice-comparison", "rounds", id, "summary"] as const,
  clip: (trial: string, side: "a" | "b") =>
    ["admin", "ops", "voice-comparison", "clip", trial, side] as const,
};

function get<T>(path: string): Promise<T> {
  return apiRequest<T>(adminSession(), path);
}

export function useComparisonSetup(
  enabled: boolean,
): UseQueryResult<ComparisonSetup> {
  return useQuery({
    queryKey: voiceComparisonKeys.setup,
    queryFn: () => get<ComparisonSetup>(COMPARISON_SETUP_PATH),
    enabled,
  });
}

export function useComparisonVoices(
  enabled: boolean,
): UseQueryResult<ComparisonVoices> {
  return useQuery({
    queryKey: voiceComparisonKeys.voices,
    queryFn: () => get<ComparisonVoices>(COMPARISON_VOICES_PATH),
    enabled,
  });
}

export function useComparisonSentences(
  enabled: boolean,
): UseQueryResult<ComparisonSentences> {
  return useQuery({
    queryKey: voiceComparisonKeys.sentences,
    queryFn: () => get<ComparisonSentences>(COMPARISON_SENTENCES_PATH),
    enabled,
  });
}

export function useComparisonRounds(
  enabled: boolean,
): UseQueryResult<ComparisonRounds> {
  return useQuery({
    queryKey: voiceComparisonKeys.rounds,
    queryFn: () => get<ComparisonRounds>(COMPARISON_ROUNDS_PATH),
    enabled,
  });
}

export function useComparisonRound(
  id: string | null,
): UseQueryResult<ComparisonRound> {
  return useQuery({
    queryKey: voiceComparisonKeys.round(id ?? ""),
    queryFn: () => get<ComparisonRound>(roundPath(id ?? "")),
    enabled: id !== null,
  });
}

export function useComparisonSummary(
  id: string,
  finished: boolean,
): UseQueryResult<ComparisonSummary> {
  return useQuery({
    queryKey: voiceComparisonKeys.summary(id),
    queryFn: () => get<ComparisonSummary>(`${roundPath(id)}/summary`),
    enabled: finished,
  });
}

/** One side of one pair, read through the authenticated transport only when asked for. */
export function useComparisonClip(
  trialId: string,
  side: "a" | "b",
  enabled: boolean,
): UseQueryResult<Blob> {
  return useQuery({
    queryKey: voiceComparisonKeys.clip(trialId, side),
    queryFn: () =>
      apiRequest<Blob>(
        adminSession(),
        `${trialPath(trialId)}/audio?side=${side}`,
        {
          responseType: "blob",
        },
      ),
    enabled,
    staleTime: Infinity,
  });
}

export function useSetUpSarvam(): UseMutationResult<
  ComparisonSetup,
  Error,
  void
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      confirmedAdminRequest<ComparisonSetup>(
        COMPARISON_SETUP_PATH,
        { method: "POST", confirmAction: SETUP_CONFIRMATION },
        "Setting up Sarvam voices for the comparison.",
      ),
    onSuccess: (data) => {
      client.setQueryData(voiceComparisonKeys.setup, data);
      return client.invalidateQueries({ queryKey: voiceComparisonKeys.voices });
    },
  });
}

export function useStartRound(): UseMutationResult<
  ComparisonRound,
  Error,
  ComparisonRoundIn
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      apiRequest<ComparisonRound>(adminSession(), COMPARISON_ROUNDS_PATH, {
        method: "POST",
        body,
      }),
    onSuccess: (round) => {
      client.setQueryData(voiceComparisonKeys.round(round.id), round);
      return client.invalidateQueries({ queryKey: voiceComparisonKeys.rounds });
    },
  });
}

export function useRateTrial(
  roundId: string,
): UseMutationResult<
  ComparisonTrial,
  Error,
  { trialId: string; body: ComparisonRateIn }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ trialId, body }) =>
      apiRequest<ComparisonTrial>(adminSession(), trialPath(trialId), {
        method: "PUT",
        body,
      }),
    onSuccess: (trial) => {
      client.setQueryData<ComparisonRound>(
        voiceComparisonKeys.round(roundId),
        (round) =>
          round
            ? {
                ...round,
                rated: round.trials.filter((t) => t.rated || t.id === trial.id)
                  .length,
                trials: round.trials.map((t) =>
                  t.id === trial.id ? trial : t,
                ),
              }
            : round,
      );
    },
  });
}

export function useFinishRound(
  roundId: string,
): UseMutationResult<ComparisonRound, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<ComparisonRound>(
        adminSession(),
        `${roundPath(roundId)}/finish`,
        {
          method: "POST",
        },
      ),
    onSuccess: (round) => {
      client.setQueryData(voiceComparisonKeys.round(roundId), round);
      return client.invalidateQueries({ queryKey: voiceComparisonKeys.rounds });
    },
  });
}

/** The finished round's pairs as a CSV file the browser saves. */
export async function downloadRoundCsv(roundId: string): Promise<void> {
  const blob = await apiRequest<Blob>(
    adminSession(),
    `${roundPath(roundId)}/export`,
    {
      responseType: "blob",
    },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `voice-comparison-${roundId}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

/** Pairs a round would hold: every Cartesia voice against every Sarvam voice, per sentence. */
export function pairCount(
  cartesia: number,
  sarvam: number,
  sentences: number,
): number {
  return cartesia * sarvam * sentences;
}

/** The sentences box, one per line, as the server takes them. */
export function sentenceLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}
