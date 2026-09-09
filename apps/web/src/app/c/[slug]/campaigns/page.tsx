"use client";

import { CampaignsScreen } from "./CampaignsScreen";

/**
 * `/c/{slug}/campaigns` — outbound campaigns (FLOWS §5, SURFACES §2b).
 *
 * A route module keeps the chrome and hands off (UX-DOCTRINE §6): it may export only
 * `default` (D-196), so the screen cannot be split by extraction while it lives here.
 * This file used to BE the screen at 2,505 lines; `CampaignsScreen.tsx` and its siblings
 * are what came out of it, and the argument for each split is at the top of each file.
 */
export default function CampaignsPage() {
  return <CampaignsScreen />;
}
