"use client";

import { use } from "react";

import { LeadDetailScreen } from "./LeadDetailScreen";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives.
 */
export default function LeadDetailPage({
  params,
}: {
  params: Promise<{ slug: string; leadId: string }>;
}) {
  const { slug, leadId } = use(params);
  return <LeadDetailScreen slug={slug} leadId={leadId} />;
}
