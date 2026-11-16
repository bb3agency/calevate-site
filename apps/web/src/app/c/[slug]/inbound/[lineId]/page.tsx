"use client";

import { use } from "react";

import { InboundLineScreen } from "../InboundLineScreen";

/** `/c/{slug}/inbound/{id}` — one inbound line: its voice, its words, its numbers (D-997). */
export default function InboundLinePage({ params }: { params: Promise<{ slug: string; lineId: string }> }) {
  const { slug, lineId } = use(params);
  return <InboundLineScreen slug={slug} lineId={lineId} />;
}
