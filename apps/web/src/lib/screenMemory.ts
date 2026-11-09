"use client";

import { useEffect } from "react";

/**
 * WHERE A LIST SCREEN WAS LEFT, for the length of one browser tab.
 *
 * Opening a call or a lead unmounts the list it was opened from, so pressing Back used to
 * land on page one with every filter gone: an owner working down "Needs you" re-chose the
 * filter after every call. The filters and the page are kept in `sessionStorage` rather
 * than the address bar because the list pages remount on a changed query string
 * (`calls/page.tsx`, `leads/page.tsx`) and a search box can hold a phone number, which
 * never goes into a URL (hard rule 6). Nothing typed into a search box is kept here.
 *
 * Storage can be missing or refused (a private window, blocked site data), so every read
 * and write is guarded and a screen without it simply starts fresh, as it always did.
 */

const PREFIX = "calevate:screen:";

/** What `key` held when the screen was last left in this tab, or null. */
export function readScreenMemory<T extends object>(key: string): Partial<T> | null {
  try {
    const raw = window.sessionStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Partial<T>) : null;
  } catch {
    return null;
  }
}

/** Keeps `value` under `key` whenever it changes; a null key keeps nothing. */
export function useRememberScreen(key: string | null, value: object): void {
  const json = JSON.stringify(value);
  useEffect(() => {
    if (key === null) return;
    try {
      window.sessionStorage.setItem(PREFIX + key, json);
    } catch {
      // Storage refused: the screen still works, it just starts fresh next time.
    }
  }, [key, json]);
}
