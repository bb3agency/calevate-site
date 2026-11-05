"use client";

/**
 * The route module for a client's campaigns; the screen is `CampaignsScreen.tsx` (a route
 * module may export only `default`, D-196).
 */

import { use } from "react";

import { CampaignsScreen } from "./CampaignsScreen";

export default function TenantCampaignsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <CampaignsScreen tenantId={tenantId} />;
}
