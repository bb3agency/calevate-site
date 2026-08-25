"use client";

/**
 * "You are offline", said ONCE, in one place, by the thing that actually knows.
 *
 * ## The defect this closes
 *
 * Nothing in this app read the browser's online state — `grep -rn "navigator.onLine" src`
 * returned nothing — while TEN screens each hand-wrote their own explanation of the same
 * TanStack behaviour, in ten different sentences (`admin/health`, `admin/holds`,
 * `admin/qa-sampling`, `admin/new`, `admin/operators`, three tenant screens, and
 * `lib/api/admin/access.ts`). Ten authors independently rediscovering one vendor behaviour
 * is a missing abstraction, and the missing piece was the plain fact underneath all ten:
 * the connection is gone. Each of those screens is left to explain what IT cannot do; this
 * says what is true of the whole window.
 *
 * ## Why it reads TanStack's `onlineManager` and not `navigator.onLine` directly
 *
 * `navigator.onLine` is the obvious source and is the WRONG one here by a hair that
 * matters: what a reader needs explained is why the panels have stalled, and what stalls
 * them is `onlineManager` — query-core pauses a fetch when IT believes the browser is
 * offline. It is a module-level singleton that already subscribes to the window's
 * `online`/`offline` events (so this is `navigator.onLine`, plus the events, minus a second
 * listener), it is what `fetchStatus === "paused"` is derived from, and it is settable —
 * which is how `tests/harness.tsx::browserOffline()` takes the suite offline and how this
 * banner is testable at all. Reading a second, independent source would let the banner and
 * the paused panels disagree, and the banner is the one claiming to explain the panels.
 *
 * `useSyncExternalStore` rather than `useState` + an effect: it is React 19's supported way
 * to read an external mutable store without tearing, and its third argument gives the
 * server snapshot — `true`, i.e. "online" — so the server never renders a banner that a
 * hydrating browser would immediately remove.
 *
 * ## What it is not
 *
 * It is NOT a replacement for a screen's own refusal. §52 still applies: a panel whose read
 * paused must still say it has no answer rather than render a zero. This says why, once,
 * above all of them — so those ten sentences can eventually shrink to "waiting for a
 * connection" instead of each carrying its own diagnosis.
 */

import { useSyncExternalStore } from "react";

import { onlineManager } from "@tanstack/react-query";
import { CloudOff } from "lucide-react";

/** Whether this browser can currently reach the network, as query-core believes it. */
export function useOnline(): boolean {
  return useSyncExternalStore(
    (onStoreChange) => onlineManager.subscribe(onStoreChange),
    () => onlineManager.isOnline(),
    () => true,
  );
}

/**
 * The strip. Renders nothing at all while online — no wrapper, no empty live region — so
 * mounting it costs a connected user no DOM and no landmark.
 *
 * `role="status"` (polite), not `role="alert"`: losing a connection is not an interruption
 * that should cut across whatever a screen reader is currently saying, and it is announced
 * the moment the element appears. Amber rather than rose, on the same reasoning
 * `RestrictionNote` is slate: being offline is a state of the world, not a fault of the
 * product, and the product is not broken when it comes back.
 */
export function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-center text-xs font-semibold text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      <CloudOff aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span>
        You are offline. Nothing on this screen is up to date, and anything you save will
        wait until the connection is back.
      </span>
    </div>
  );
}
