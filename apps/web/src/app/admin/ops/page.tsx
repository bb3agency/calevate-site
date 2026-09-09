"use client";

import { OpsSurface } from "./OpsSurface";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives — and the panels it
 * mounts are one file each, beside `OpsSurface.tsx`.
 */
export default function OpsPage() {
  return <OpsSurface />;
}
