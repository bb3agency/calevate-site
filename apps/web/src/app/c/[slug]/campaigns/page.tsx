"use client";

import { useSearchParams } from "next/navigation";
import { use } from "react";

import { CampaignsListScreen } from "./CampaignsListScreen";

/**
 * `/c/{slug}/campaigns` — the campaign list (FLOWS §5). A page module exports only `default` (D-196).
 *
 * Keyed on the query string: the status filter is seeded from `?status=` once, at mount,
 * so a link to another status followed from this screen must remount it to take effect.
 */
export default function CampaignsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const query = useSearchParams().toString();
  return <CampaignsListScreen key={query} slug={slug} />;
}
