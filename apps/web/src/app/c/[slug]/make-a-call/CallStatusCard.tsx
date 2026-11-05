"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check, PhoneForwarded } from "lucide-react";

import { SECONDARY_BUTTON } from "@/components/ui";
import { useLiveCalls } from "@/lib/api/liveCalls";
import { useClientRealm } from "@/lib/api/session";

/** The statuses a call is still under way in (`calevate_shared.events.CallStatus`). */
const UNDER_WAY = new Set(["queued", "ringing", "in_progress"]);

/** Where the call stands, in an owner's words. An unknown status is printed, never hidden. */
const WORDS: Record<string, string> = {
  queued: "Dialling",
  ringing: "Ringing",
  in_progress: "On the call",
  completed: "Call ended",
  no_answer: "No answer",
  busy: "Busy",
  voicemail: "Went to voicemail",
  failed: "Did not connect",
  unreported: "No ending heard yet",
};

const STEPS = [
  { key: "ringing", label: "Ringing" },
  { key: "talking", label: "Talking" },
  { key: "ended", label: "Ended" },
] as const;

function stepOf(status: string, ended: boolean): number {
  if (ended) return 2;
  return status === "in_progress" ? 1 : 0;
}

/**
 * THE CALL JUST PLACED, LIVE: ringing, talking, ended, from `GET /v1/calls/live` (the call
 * log's own read, D-886), and a link to the call. The read stops once the call has ended,
 * and the server stops calling a call live past the longest one can run, so it always ends.
 */
export function CallStatusCard({
  callId,
  followUpNumber,
  onAnother,
}: {
  callId: string;
  /** Set when the call follows up an earlier one: which follow-up it is. */
  followUpNumber?: number | null;
  onAnother: () => void;
}) {
  const { session, href } = useClientRealm();
  // The last answer is kept: once the read stops, its cache entry is gone, and the card
  // must go on saying how the call ended rather than fall back to "Dialling".
  const [seen, setSeen] = useState<{ status: string; ended: boolean }>({ status: "queued", ended: false });
  const done = seen.ended;
  const live = useLiveCalls(session, done ? [] : [callId]);
  const row = live.data?.find((r) => r.id === callId);
  useEffect(() => {
    if (!row) return;
    // `unreported`: past the longest a call can run with no ending heard. The poll stops
    // and the card says so rather than claiming it is still ringing.
    const unreported = row.live_state === "unreported";
    const ended = unreported || (!UNDER_WAY.has(row.status) && row.live_state == null);
    const status = unreported ? "unreported" : row.status;
    setSeen((prev) => (prev.status === status && prev.ended === ended ? prev : { status, ended }));
  }, [row]);
  const status = seen.status;
  const step = stepOf(status, done);
  const words = WORDS[status] ?? status.replace(/_/g, " ");

  return (
    <section aria-labelledby="call-status-heading" className="rounded-lg border border-line bg-surface p-4 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="call-status-heading" className="text-body font-semibold text-ink">
          {followUpNumber ? `Call-back #${followUpNumber}` : "This call"}
        </h2>
        <p aria-live="polite" className="text-heading font-semibold text-ink">
          {words}
        </p>
      </div>
      <ol className="mt-4 grid grid-cols-3 gap-2" aria-label="Call progress">
        {STEPS.map((s, i) => {
          const reached = i <= step;
          const current = i === step;
          return (
            <li key={s.key} aria-current={current ? "step" : undefined} className="min-w-0">
              <span
                aria-hidden
                className={`block h-1.5 rounded-full ${reached ? "bg-brand" : "bg-ink/[0.08]"} ${
                  current && !done ? "motion-safe:animate-pulse" : ""
                }`}
              />
              <span
                className={`mt-1.5 flex items-center gap-1 text-meta ${reached ? "font-medium text-ink" : "text-ink-faint"}`}
              >
                {i < step ? <Check aria-hidden className="h-3.5 w-3.5 shrink-0" /> : null}
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>
      {live.error != null && !done ? (
        <p className="mt-3 text-meta text-warn">Couldn&apos;t check on the call just now. Trying again.</p>
      ) : null}
      <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4">
        <Link href={href(`/c/${session.orgSlug}/calls/${callId}`)} className={SECONDARY_BUTTON}>
          {done ? "Open the call" : "See the call"}
        </Link>
        <button type="button" onClick={onAnother} className={SECONDARY_BUTTON}>
          <PhoneForwarded aria-hidden className="h-4 w-4" />
          Make another call
        </button>
      </div>
    </section>
  );
}
