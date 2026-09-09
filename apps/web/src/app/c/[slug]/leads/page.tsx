"use client";

import { LeadsScreen } from "./LeadsScreen";

/**
 * `/c/{slug}/leads` — the CRM table (D-21, SURFACES §2).
 *
 * A route module keeps the chrome and hands off (UX-DOCTRINE §6): it may export only
 * `default` (D-196), so the screen cannot be split by extraction while it lives here.
 * This file used to BE the screen at 1,466 lines; `LeadsScreen.tsx` and its siblings are
 * what came out of it, and the argument for each split is at the top of each file.
 */
export default function LeadsPage() {
  return <LeadsScreen />;
}
