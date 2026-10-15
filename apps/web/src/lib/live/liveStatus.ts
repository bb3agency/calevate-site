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

import { ALL_LIVE_FAMILIES, familyOf } from "./topics";

/** The slow poll that stays on under a healthy stream: what a lost note can cost at most. */
export const LIVE_SAFETY_POLL_MS = 5 * 60_000;

let healthy = false;

export function setLiveHealthy(next: boolean): void {
  healthy = next;
}

/** How long an answer counts as fresh when no healthy stream vouches for it. */
export const BASE_STALE_MS = 10_000;

/**
 * Every query's `staleTime` (`app/providers.tsx`): the safety poll's period for a live
 * family while the stream is healthy, `BASE_STALE_MS` otherwise.
 *
 * Staleness is what makes TanStack refetch when a screen mounts and when the tab regains
 * focus. Under a healthy stream a live family's answer is not stale at ten seconds — any
 * change since has already invalidated it — so at that bound every page change re-sent
 * the reads the shell and the last screen had just made, and every tab switch re-sent all
 * of them (sixteen on the client dashboard). A family no topic covers, or a stream that is
 * down, keeps the short bound, and a lost note costs at most the safety period, as with
 * `livePoll`.
 */
export function liveStaleTime(query: { queryKey: readonly unknown[] }): number {
  if (!healthy) return BASE_STALE_MS;
  const family = familyOf(query.queryKey);
  return family !== null && ALL_LIVE_FAMILIES.has(family) ? LIVE_SAFETY_POLL_MS : BASE_STALE_MS;
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
