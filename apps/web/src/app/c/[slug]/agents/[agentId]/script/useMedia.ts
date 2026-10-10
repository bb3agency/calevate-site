"use client";

import { useSyncExternalStore } from "react";

/**
 * A media query's answer, kept current. False on the server and in a browser (or test
 * environment) without `matchMedia`, so the phone layout is the one that renders first.
 */
export function useMedia(query: string): boolean {
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

/** Wide enough for the flow canvas beside a section editor. */
export const DESKTOP = "(min-width: 1024px)";
