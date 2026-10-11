"use client";

/**
 * The shared free-trial number (D-697): the number set now, and the platform-held numbers
 * that may be it — held in our developer workspace and recorded against no client, read
 * live from the voice platform. The choice itself is written through the ordinary config
 * write (`trial_caller_number`), which checks it against the same list.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession, confirmedAdminRequest, TRIAL_LINE_CONFIRMATION } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

export type TrialNumber = components["schemas"]["TrialNumberOut"];

export const TRIAL_NUMBER_KEY = "trial_caller_number";

export function useTrialNumber(): UseQueryResult<TrialNumber> {
  return useQuery({
    queryKey: ["ops", "trial-number"],
    queryFn: () => apiRequest<TrialNumber>(adminSession(), "/v1/ops/trial-number"),
  });
}

export type TrialLine = components["schemas"]["TrialLineOut"];

/** Make (or repair) the shared number's never-answering line and its message (D-742). */
export function useSetUpTrialLine() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      confirmedAdminRequest<TrialLine>(
        "/v1/ops/trial-number/line",
        { method: "POST", confirmAction: TRIAL_LINE_CONFIRMATION },
        "Setting up the shared trial number.",
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ops", "trial-number"] }),
  });
}
