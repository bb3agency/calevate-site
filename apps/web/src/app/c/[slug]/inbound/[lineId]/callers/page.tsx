"use client";

import { use } from "react";

import { LineCallersScreen } from "../../LineCallersScreen";

/** `/c/{slug}/inbound/{id}/callers` — the people one line still owes a call (W4.1). */
export default function LineCallersPage({ params }: { params: Promise<{ slug: string; lineId: string }> }) {
  const { slug, lineId } = use(params);
  return <LineCallersScreen slug={slug} lineId={lineId} />;
}
