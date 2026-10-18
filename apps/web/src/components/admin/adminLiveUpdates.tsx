"use client";

import { useMemo } from "react";

import { adminSession } from "@/lib/api/admin";
import { useLiveUpdates } from "@/lib/live/useLiveUpdates";

/**
 * The operator console's live change stream (D-774), mounted once in `app/admin/layout.tsx`.
 * Renders nothing. Apart from `ClientLiveUpdates` so the client console does not load the
 * admin API client.
 */
export function AdminLiveUpdates() {
  const session = useMemo(() => adminSession(), []);
  useLiveUpdates(session, "/v1/admin/live");
  return null;
}
