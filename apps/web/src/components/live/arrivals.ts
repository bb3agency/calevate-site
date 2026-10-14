"use client";

import { useEffect, useRef, useState } from "react";

import { FLASH_MS } from "@/components/console/valueFlash";

/**
 * Whether a new list of ids CONTINUES the one on screen (a live change: a few items
 * arrived or left) rather than replacing it (another page, filter or server sort). Only a
 * continuation animates: paging through a log must not make every row "arrive".
 *
 * From an empty list, up to three arrivals count as live (the first lead of the day); more
 * is a load, not an arrival.
 */
export function continuesFrom(before: ReadonlySet<string>, after: readonly string[]): boolean {
  if (before.size === 0) return after.length > 0 && after.length <= 3;
  let kept = 0;
  let added = 0;
  for (const id of after) {
    if (before.has(id)) kept += 1;
    else added += 1;
  }
  return kept > 0 && added <= Math.max(3, Math.ceil(after.length / 4));
}

/**
 * Which items ARRIVED in this render. Decided while rendering, not in an effect, because
 * an entrance has to be on the element when it first paints. Measured against the last
 * COMMITTED render, so the first render and a re-render of the same items mark nothing.
 *
 * `null` means "not loaded yet": nothing is committed until the first answer, so the first
 * answer is a load and never an arrival, even when it is one item into an empty screen.
 */
export function useArrivals(ids: readonly string[] | null): { arrived: Set<string>; continuous: boolean } {
  const committed = useRef<ReadonlySet<string> | null>(null);
  const before = committed.current;
  const continuous = before !== null && ids !== null && continuesFrom(before, ids);
  const arrived = new Set<string>();
  if (continuous && ids !== null) for (const id of ids) if (!before?.has(id)) arrived.add(id);
  useEffect(() => {
    if (ids !== null) committed.current = new Set(ids);
  });
  return { arrived, continuous };
}

/**
 * The `live-enter` class for items that just arrived, kept for `FLASH_MS` so a re-render
 * a moment later does not cut the entrance short. `live-enter` (globals.css) is a 220 ms
 * fade with a 4 px drop that reduced motion turns off entirely.
 */
export function useEnterClass(ids: readonly string[] | null): (id: string) => string {
  const { arrived } = useArrivals(ids);
  const [recent, setRecent] = useState<ReadonlySet<string>>(() => new Set());
  const key = [...arrived].join("\u0000");
  useEffect(() => {
    if (key === "") return;
    setRecent(new Set(key.split("\u0000")));
    const timer = setTimeout(() => setRecent(new Set()), FLASH_MS);
    return () => clearTimeout(timer);
  }, [key]);
  return (id) => (arrived.has(id) || recent.has(id) ? "live-enter" : "");
}
