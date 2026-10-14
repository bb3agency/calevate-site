"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { openEventStream, type Session } from "@/lib/api/client";

import { LiveConnection } from "./liveConnection";
import { setLiveHealthy } from "./liveStatus";
import { familyOf } from "./topics";

/** The client realm's stream and the operator console's. */
export type LiveStreamPath = "/v1/live" | "/v1/admin/live";

/**
 * Keep every feed on screen current from the live change stream (D-774). Mount ONCE per
 * realm layout; every screen under it benefits without doing anything.
 *
 * Notes become `invalidateQueries` over the families `lib/live/topics.ts` maps them to,
 * so the refetch goes through the same hook, key and authorised route the screen already
 * uses; only queries on screen refetch, the rest are marked stale.
 */
export function useLiveUpdates(session: Session, path: LiveStreamPath): void {
  const client = useQueryClient();

  useEffect(() => {
    const connection = new LiveConnection({
      open: (signal, onEvent) => openEventStream(session, path, { signal, onEvent }),
      invalidate: (families) => {
        void client.invalidateQueries({
          predicate: (query) => {
            const family = familyOf(query.queryKey);
            return family !== null && families.has(family);
          },
        });
      },
      onHealth: setLiveHealthy,
      isVisible: () => document.visibilityState !== "hidden",
      // The operator stream carries every account's notes, so it gathers longer.
      coalesceMs: path === "/v1/admin/live" ? 1_500 : 400,
    });
    const onVisibility = () => connection.visibilityChanged();
    document.addEventListener("visibilitychange", onVisibility);
    connection.start();
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      connection.stop();
    };
  }, [client, session, path]);
}
