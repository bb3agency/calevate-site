import { ApiProblem, TransportProblem } from "./client";

/**
 * The app-wide retry policy for reads (`app/providers.tsx`), kept here so it can be tested.
 *
 * A refusal the server marks retryable may carry `Retry-After` — a rate-limited read
 * (`core/ratelimit.py`, `too_many_requests`) does. TanStack's default backoff (1 s, 2 s)
 * ignores it, so two more requests landed inside the same limiter window and the refusal
 * reached the screen later for it. A wait the server names is honoured; one longer than a
 * person will sit through is not waited out at all, and the screen shows the refusal (with
 * its own Try again) instead.
 *
 * A read that never reached the server (`TransportProblem`: a dropped connection, the API
 * restarting during a deploy) gets more tries than a refusal the server sent. The default
 * two are spent inside three seconds, which a restart outlasts, so one dropped read showed
 * as "This did not load" on a box the owner needed. Four on the same doubling backoff wait
 * out about fifteen seconds, with the screen in its loading state meanwhile. Only a GET or
 * HEAD gets them: a query read through a POST may not be safe to repeat, and mutations never
 * retry at all (`providers.tsx`), since a write's outcome is unknown.
 */
export const MAX_QUERY_RETRIES = 2;
export const MAX_TRANSPORT_RETRIES = 4;
const READS = new Set(["GET", "HEAD"]);
export const MAX_RETRY_AFTER_SECONDS = 10;

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof TransportProblem && READS.has(error.request.method)) {
    return failureCount < MAX_TRANSPORT_RETRIES;
  }
  if (failureCount >= MAX_QUERY_RETRIES) return false;
  if (!(error instanceof ApiProblem)) return true;
  if (!error.retryable) return false;
  const wait = error.retryAfterSeconds;
  return wait === undefined || wait <= MAX_RETRY_AFTER_SECONDS;
}

export function queryRetryDelay(failureCount: number, error: unknown): number {
  if (error instanceof ApiProblem && error.retryAfterSeconds !== undefined) {
    return Math.max(0, error.retryAfterSeconds) * 1000;
  }
  // TanStack's own default.
  return Math.min(1000 * 2 ** failureCount, 30_000);
}

/**
 * Whether a query's last read was refused for a reason no repeat can fix: a 403, a 404, a
 * 422, any problem the server marked not retryable.
 *
 * A `refetchInterval` keeps firing through errors, so a poll whose condition read "no
 * answer yet" (`data === undefined`) or "still moving" (the last good answer) asked every
 * few seconds for as long as the page stayed open: an upload deleted from another tab, a
 * test call that is not this account's. Polls stop on this; a later success (a focus
 * refetch, a remount) puts them back on their interval, because TanStack re-reads the
 * interval after every fetch.
 */
export function refusedForGood(query: unknown): boolean {
  const state = (query as { state?: { status?: string; error?: unknown } } | null | undefined)
    ?.state;
  return state?.status === "error" && state.error instanceof ApiProblem && !state.error.retryable;
}

type PollInterval<Q> = number | false | undefined | ((query: Q) => number | false | undefined);

/** `interval`, or `false` once the read has been refused for good (`refusedForGood`). */
export function untilRefused<Q>(
  interval: PollInterval<Q>,
): (query: Q) => number | false | undefined {
  return (query) => {
    if (refusedForGood(query)) return false;
    return typeof interval === "function" ? interval(query) : interval;
  };
}
