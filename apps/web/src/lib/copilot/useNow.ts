"use client";

import { useEffect, useState } from "react";

/**
 * The time, refreshed every `intervalMs` while `active`. One ticker per live view, handed
 * down to its rows, so a timeline of ten running rows re-renders once a second, not ten times.
 */
export function useNow(active: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [active, intervalMs]);
  return now;
}
