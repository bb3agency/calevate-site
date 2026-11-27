"use client";

/**
 * How long this account keeps what its calls leave behind (W12.9), under the call log. The
 * days are the account's own retention settings read from the server (`GET /v1/calls/kept`),
 * never a constant, so a changed setting changes the sentence. Says nothing until they load,
 * and nothing about a kind with no period.
 */

import { formatCount } from "@/components/ui";
import { useCallRetention } from "@/lib/api/inboundToday";
import { useClientRealm } from "@/lib/api/session";

const days = (n: number) => `${formatCount(n)} ${n === 1 ? "day" : "days"}`;

export function RetentionLine() {
  const { session } = useClientRealm();
  const kept = useCallRetention(session);
  const recording = kept.data?.recording_days;
  const transcript = kept.data?.transcript_days;
  if (recording == null && transcript == null) return null;
  const parts = [
    recording != null ? `recordings for ${days(recording)}` : null,
    transcript != null ? `transcripts for ${days(transcript)}` : null,
  ].filter(Boolean);
  return <p className="text-meta text-ink-muted">We keep {parts.join(" and ")}.</p>;
}
