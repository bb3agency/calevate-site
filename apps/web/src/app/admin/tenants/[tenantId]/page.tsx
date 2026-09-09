"use client";

import { use } from "react";

import { TenantDetail } from "./TenantDetail";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives — and each of its
 * panels is one file beside `TenantDetail.tsx`.
 */
export default function TenantDetailPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <TenantDetail tenantId={tenantId} />;
}
