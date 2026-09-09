"use client";

import { use } from "react";

import { CallDetailScreen } from "./CallDetailScreen";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives.
 */
export default function CallDetailPage({
  params,
}: {
  params: Promise<{ slug: string; callId: string }>;
}) {
  const { slug, callId } = use(params);
  return <CallDetailScreen slug={slug} callId={callId} />;
}
