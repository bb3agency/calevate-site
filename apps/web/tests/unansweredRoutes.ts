/**
 * Requests the harness could not answer, collected per test and checked in `setup.ts`.
 *
 * Its own module rather than part of `harness.tsx` because `setup.ts` runs in every test
 * file, including pure unit tests, and `harness.tsx` imports the app's providers.
 *
 * WHY AN UNANSWERED READ FAILS THE TEST. The stub throws for it, the app renders the
 * throw as a transport failure, and that failure is a `role="alert"` the test did not ask
 * for. A test that then finds "the" alert passes or fails on which of two failures
 * painted first — the flake that failed CI on `dashboard.test.tsx` — or passes on the
 * wrong alert outright, as the do-not-call refusals did. A test that MEANS to exercise a
 * request with no reply says so with `noReply()` as the route's answer, or, where the
 * request cannot be named in advance, `allowUnansweredRoutes()`.
 */
const unanswered: string[] = [];
let allowed = false;

export function recordUnanswered(request: string): void {
  unanswered.push(request);
}

/** Opt this test out of the check. Prefer `noReply()` on the specific route. */
export function allowUnansweredRoutes(): void {
  allowed = true;
}

/** What this test left unanswered, and whether it opted out; resets for the next test. */
export function takeUnanswered(): { requests: string[]; allowed: boolean } {
  const result = { requests: unanswered.splice(0), allowed };
  allowed = false;
  return result;
}
