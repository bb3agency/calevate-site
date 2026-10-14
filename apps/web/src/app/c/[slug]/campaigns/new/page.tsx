"use client";

import { use } from "react";

import { NewCampaignScreen } from "../NewCampaignScreen";

/** `/c/{slug}/campaigns/new` — create a campaign (FLOWS §5). */
export default function NewCampaignPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <NewCampaignScreen slug={slug} />;
}
