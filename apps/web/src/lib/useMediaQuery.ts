"use client";

import { useSyncExternalStore } from "react";

/**
 * Does `query` match right now? Re-renders when it starts or stops matching.
 *
 * False on the server and in a browser without `matchMedia`, so the first paint is the
 * wide layout and a phone switches once it has hydrated. Use it only where the two
 * layouts are different MARKUP (a table and a list); where only the styling differs, a
 * CSS breakpoint is the right tool and needs no JavaScript.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false),
    () => false,
  );
}
