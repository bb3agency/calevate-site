"use client";

/**
 * Whether the phone service is answering, for the client console (`GET /v1/phone-service`).
 *
 * One query, shared by the banner over every screen and by each test-call button, so a
 * screen never shows the banner beside an enabled button or the other way round. The server
 * decides; this module only reads it. The refusal codes a pressed button can meet are in
 * `phoneServiceCodes.ts`.
 */

import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";
import type { components } from "./schema";

export {
  PHONE_SERVICE_DOWN_CODE,
  SAVED_GOES_LIVE_LATER,
  SAVED_GOES_LIVE_LATER_CODE,
  SAVED_GOES_LIVE_LATER_DETAIL,
  TEST_CALLS_PAUSED,
  isPhoneServiceDown,
  isSavedGoesLiveLater,
} from "./phoneServiceCodes";

export type PhoneService = components["schemas"]["PhoneServiceOut"];

export const PHONE_SERVICE_PATH = "/v1/phone-service";
export const PHONE_SERVICE_QUERY_KEY = ["client", "phone-service"] as const;

/**
 * Polled every 30 seconds while down, so the banner and the buttons come back soon after it
 * answers; every two minutes while answering, which is the ordinary day.
 */
export function usePhoneService(session: Session): UseQueryResult<PhoneService> {
  return useQuery({
    queryKey: [...PHONE_SERVICE_QUERY_KEY, session.orgSlug],
    queryFn: () => apiRequest<PhoneService>(session, PHONE_SERVICE_PATH),
    refetchInterval: untilRefused((query) =>
      query.state.data?.state === "not_answering" ? 30_000 : 120_000,
    ),
    retry: false,
  });
}

/** True only when the server said so; loading or an unreadable answer is "answering". */
export function usePhoneServiceDown(session: Session): boolean {
  return usePhoneService(session).data?.state === "not_answering";
}

/**
 * Refresh the phone-service read after a press found it down, so the banner and every
 * test-call button switch at once instead of at the next poll.
 */
export function useRefreshPhoneService(): () => void {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: PHONE_SERVICE_QUERY_KEY });
  };
}
