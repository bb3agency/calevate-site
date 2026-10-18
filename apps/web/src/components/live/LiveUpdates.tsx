"use client";

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
