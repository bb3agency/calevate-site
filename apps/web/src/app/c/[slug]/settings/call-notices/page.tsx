"use client";

import { CallNoticesScreen } from "./CallNoticesScreen";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives.
 */
export default function CallNoticesPage() {
  return <CallNoticesScreen />;
}
