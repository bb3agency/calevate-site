"use client";

import { use } from "react";

import { CampaignScreen } from "../CampaignScreen";

/** `/c/{slug}/campaigns/{id}` — one campaign: its state, its checklist and its results. */
export default function CampaignPage({
  params,
}: {
  params: Promise<{ slug: string; campaignId: string }>;
}) {
  const { slug, campaignId } = use(params);
  return <CampaignScreen slug={slug} campaignId={campaignId} />;
}
