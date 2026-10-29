"use client";

import { useCallback, useEffect, useRef } from "react";

/** Props a row link spreads to read its page ahead. */
export type ReadAheadProps = {
  onPointerEnter: (event: { pointerType: string }) => void;
  onPointerLeave: () => void;
  onPointerDown: () => void;
  onFocus: () => void;
};

/**
 * How long a mouse must rest on a row before its page is read. Rows on the call log and
 * the leads list are whole-row links, so a pointer crossing the list on its way somewhere
 * else enters a dozen of them; reading each would be a burst of requests nobody asked for.
 * 100 ms separates passing over from settling on (the same order as the hover-intent delay
 * menus use), and is still well inside the time before a click lands.
 */
export const HOVER_INTENT_MS = 100;

/**
 * Starts reading a row's page the moment the person shows they may open it, so the page
 * finds its answer in the cache instead of asking only after the route has loaded (TanStack
 * Query v5, "Prefetching & Router Integration": prefetch from event handlers on hover or
 * focus). A mouse settling on the row reads after `HOVER_INTENT_MS`; a finger or pen
 * pressing it, or keyboard focus reaching it, reads at once, because the open follows
 * immediately.
 *
 * `read` is expected to be idempotent against the cache (`queryClient.prefetchQuery` does
 * not re-read an answer that is still fresh).
 */
export function useReadAhead(read: (id: string) => void): (id: string) => ReadAheadProps {
  const latest = useRef(read);
  latest.current = read;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancel = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  useEffect(() => cancel, [cancel]);

  return useCallback(
    (id: string): ReadAheadProps => ({
      onPointerEnter: (event) => {
        cancel();
        if (event.pointerType !== "mouse") return;
        timer.current = setTimeout(() => {
          timer.current = null;
          latest.current(id);
        }, HOVER_INTENT_MS);
      },
      onPointerLeave: cancel,
      onPointerDown: () => {
        cancel();
        latest.current(id);
      },
      onFocus: () => latest.current(id),
    }),
    [cancel],
  );
}
