"use client";

import { use } from "react";

import { parseStartAt } from "@/lib/callMoments";

import { CallDetailScreen } from "./CallDetailScreen";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives. `?t=<seconds>` opens
 * the call at a key moment (the lead page links here); the recording still starts only on
 * a press, because opening it is audited.
 */
export default function CallDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; callId: string }>;
  // Optional so the screen can be mounted with route params alone (tests, previews).
  searchParams?: Promise<{ t?: string | string[] }>;
}) {
  const { slug, callId } = use(params);
  const { t } = searchParams ? use(searchParams) : { t: undefined };
  return (
    <CallDetailScreen
      slug={slug}
      callId={callId}
      startAt={parseStartAt(Array.isArray(t) ? t[0] : t)}
    />
  );
}
