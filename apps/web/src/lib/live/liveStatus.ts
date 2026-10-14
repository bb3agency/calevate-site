/**
 * Whether this tab's live change stream is healthy, and what that does to polling (D-774).
 *
 * POLLING IS THE FLOOR, NOT A FALLBACK THAT HAS TO BE SWITCHED ON. Every feed keeps its
 * `refetchInterval`; `livePoll` stretches it to `LIVE_SAFETY_POLL_MS` while the stream is
 * up, and returns it unchanged the moment the stream is down. TanStack re-reads a function
 * interval after every fetch, so a dropped stream puts each feed back on its own interval
 * within one safety period at most — and `useLiveUpdates` refetches everything on screen
 * when the stream drops, so nobody waits that long in practice.
 *
 * A module store rather than React context: the intervals are read inside TanStack's
 * scheduler, outside any render.
 */

/** The slow poll that stays on under a healthy stream: what a lost note can cost at most. */
export const LIVE_SAFETY_POLL_MS = 5 * 60_000;

let healthy = false;
const listeners = new Set<(healthy: boolean) => void>();

export function isLiveHealthy(): boolean {
  return healthy;
}

export function setLiveHealthy(next: boolean): void {
  if (next === healthy) return;
  healthy = next;
  for (const listener of listeners) listener(next);
}

export function onLiveHealth(listener: (healthy: boolean) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

type Interval<Q> = number | false | undefined | ((query: Q) => number | false | undefined);

/**
 * A feed's `refetchInterval`, stretched to the safety poll while the stream is healthy.
 * `false` stays `false`: a query that stopped polling (a finished job) stays stopped.
 */
export function livePoll<Q>(interval: Interval<Q>): (query: Q) => number | false | undefined {
  return (query) => {
    const base = typeof interval === "function" ? interval(query) : interval;
    if (base === false || base === undefined) return base;
    return healthy ? Math.max(base, LIVE_SAFETY_POLL_MS) : base;
  };
}
