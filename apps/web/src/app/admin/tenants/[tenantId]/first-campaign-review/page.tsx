"use client";

import { use } from "react";

import { ReviewScreen } from "./ReviewScreen";

export default function FirstCampaignReviewPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  return <ReviewScreen tenantId={tenantId} />;
}
