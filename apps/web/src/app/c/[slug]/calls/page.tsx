"use client";

import { useSearchParams } from "next/navigation";
import { use } from "react";

import { CallsScreen } from "./CallsScreen";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives.
 *
 * Keyed on the query string because the screen seeds its filters from `?status=`,
 * `?agent_id=` and `?campaign_id=` once, at mount: the header's live-calls link opens
 * `?status=in_progress` while this screen is already showing, and without a remount the
 * URL would change and the list would not.
 */
export default function CallsPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const query = useSearchParams().toString();
  return <CallsScreen key={query} slug={slug} />;
}
