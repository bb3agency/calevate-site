"use client";

import { use } from "react";

import { CampaignsListScreen } from "./CampaignsListScreen";

/** `/c/{slug}/campaigns` — the campaign list (FLOWS §5). A page module exports only `default` (D-196). */
export default function CampaignsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <CampaignsListScreen slug={slug} />;
}
