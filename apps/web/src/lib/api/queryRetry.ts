import { ApiProblem } from "./client";

/**
 * The app-wide retry policy for reads (`app/providers.tsx`), kept here so it can be tested.
 *
 * A refusal the server marks retryable may carry `Retry-After` — a rate-limited read
 * (`core/ratelimit.py`, `too_many_requests`) does. TanStack's default backoff (1 s, 2 s)
 * ignores it, so two more requests landed inside the same limiter window and the refusal
 * reached the screen later for it. A wait the server names is honoured; one longer than a
 * person will sit through is not waited out at all, and the screen shows the refusal (with
 * its own Try again) instead.
 */
export const MAX_QUERY_RETRIES = 2;
export const MAX_RETRY_AFTER_SECONDS = 10;

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
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
