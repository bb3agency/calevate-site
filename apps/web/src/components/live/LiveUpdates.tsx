"use client";

import { useMemo } from "react";

import { adminSession } from "@/lib/api/admin";
import { useClientSession } from "@/lib/api/session";
import { useLiveUpdates } from "@/lib/live/useLiveUpdates";

/**
 * The client console's live change stream (D-774). Mounted once, in `app/c/[slug]/layout.tsx`,
 * inside the realm provider so it speaks with the same session as every screen — including
 * an operator's view-as session, which receives the viewed account's notes. Renders nothing.
 */
export function ClientLiveUpdates() {
  useLiveUpdates(useClientSession(), "/v1/live");
  return null;
}

/** The operator console's stream, mounted once in `app/admin/layout.tsx`. Renders nothing. */
export function AdminLiveUpdates() {
  const session = useMemo(() => adminSession(), []);
  useLiveUpdates(session, "/v1/admin/live");
  return null;
}
