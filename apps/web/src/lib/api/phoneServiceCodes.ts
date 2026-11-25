/**
 * The two answers a press can get while the phone service is not answering, and the words
 * the console shows for them. No hooks here, so the shared notice and toast code can read
 * them without pulling in a query (`phoneService.ts` holds the read).
 */

import { ApiProblem } from "./client";

/** A test call refused because the phone service is not answering (`engine/outage.py`). */
export const PHONE_SERVICE_DOWN_CODE = "phone_service_down";
/** A save that was kept and goes live by itself once the phone service answers. */
export const SAVED_GOES_LIVE_LATER_CODE = "saved_goes_live_later";

/** The one line beside a test-call button while test calls are paused. */
export const TEST_CALLS_PAUSED = "Test calls are paused: our phone service is not answering.";
/** What follows "Saved" when a save was kept and goes live by itself. */
export const SAVED_GOES_LIVE_LATER_DETAIL =
  "It goes live when the phone service answers again, usually within minutes.";
/** The same, as one line. */
export const SAVED_GOES_LIVE_LATER = `Saved. ${SAVED_GOES_LIVE_LATER_DETAIL}`;

export function isPhoneServiceDown(error: unknown): boolean {
  return error instanceof ApiProblem && error.code === PHONE_SERVICE_DOWN_CODE;
}

export function isSavedGoesLiveLater(error: unknown): boolean {
  return error instanceof ApiProblem && error.code === SAVED_GOES_LIVE_LATER_CODE;
}
