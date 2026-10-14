"use client";

import { use } from "react";

import { EditCampaignScreen } from "../../EditCampaignScreen";

/** `/c/{slug}/campaigns/{id}/edit` — change a draft's settings. */
export default function EditCampaignPage({
  params,
}: {
  params: Promise<{ slug: string; campaignId: string }>;
}) {
  const { slug, campaignId } = use(params);
  return <EditCampaignScreen slug={slug} campaignId={campaignId} />;
}
