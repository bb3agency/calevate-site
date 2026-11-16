"use client";

import { use } from "react";

import { InboundListScreen } from "./InboundListScreen";

/** `/c/{slug}/inbound` — every inbound line (D-997). A page module exports only `default` (D-196). */
export default function InboundPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <InboundListScreen slug={slug} />;
}
