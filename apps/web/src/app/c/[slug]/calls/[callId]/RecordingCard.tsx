"use client";

import { useEffect, useRef } from "react";
import { AudioLines } from "lucide-react";

import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import {
  CallAudioPlayer,
  type CallAudioPlayerHandle,
  type PlayerMark,
} from "@/components/callAudioPlayer";
import type { CallDetail } from "@/lib/api/client";
import { momentClock, momentSeekMs, type CallMoment } from "@/lib/callMoments";

const MARK_TONE: Record<CallMoment["category"], PlayerMark["tone"]> = {
  details: "neutral",
  attention: "warn",
  buying: "brand",
};

import type { useRecordingLink } from "./transcriptAccess";

/**
 * The recording, above the transcript it plays.
 *
 * A short-lived, presigned link to OUR copy of the audio — never the engine's URL —
 * fetched on the first press rather than with the page: the endpoint mints a signed URL
 * with a ticking expiry AND writes an `audit_log` row (crm/routes.py), so requesting one
 * for every visitor who never presses play would burn the link and record a listen that
 * did not happen. It is rendered into an `<audio>` element rather than an anchor: a
 * signed URL in an `href` is kept in history and handed on as a referrer, and the
 * signature is the credential.
 */
export function RecordingCard({
  recording,
  playerRef,
  onTimeUpdate,
  durationS,
  moments,
  startAtS = null,
  download,
}: {
  recording: ReturnType<typeof useRecordingLink>;
  playerRef: React.Ref<CallAudioPlayerHandle>;
  onTimeUpdate: (seconds: number) => void;
  durationS: number | null;
  moments: CallDetail["moments"];
  /**
   * Where to start once the recording opens: a moment that was clicked before the audio
   * was loaded, or a `?t=` link from the lead page. Applied once per opened link.
   */
  startAtS?: number | null;
  /** The Download control, drawn beside speed and volume; absent for a role that cannot have it. */
  download?: React.ReactNode;
}) {
  // The last link this card held. While a re-mint is in flight TanStack clears
  // `recording.data`; without this the player unmounts, the fresh one forgets it already
  // retried, and a dead object re-mints forever (each mint an audited read).
  const lastLink = useRef(recording.data);
  if (recording.data) lastLink.current = recording.data;
  const link = recording.data ?? lastLink.current;
  // One re-mint per card, whatever the player's own state: a remount cannot re-arm it.
  const remints = useRef(0);
  const url = link?.url ?? null;
  const startedFor = useRef<string | null>(null);
  useEffect(() => {
    if (url == null || startAtS == null || startedFor.current === url) return;
    startedFor.current = url;
    const handle = playerRef && typeof playerRef === "object" ? playerRef.current : null;
    handle?.seekTo(startAtS);
  }, [url, startAtS, playerRef]);

  if (link) {
    return (
      <div className="space-y-2">
        <CallAudioPlayer
          ref={playerRef}
          src={link.url}
          fallbackDurationS={link.duration_s ?? durationS}
          onTimeUpdate={onTimeUpdate}
          extraControls={download}
          marks={moments.map((m) => ({
            atS: m.at_ms / 1000,
            seekS: momentSeekMs(m) / 1000,
            label: `${momentClock(m)} ${m.label}`,
            tone: MARK_TONE[m.category],
          }))}
          onExpired={async () => {
            // Mint a replacement rather than surfacing the browser's bare media error.
            // `mutateAsync` rejects on failure, and the catch turns that into the
            // player's own refusal instead of an unhandled rejection.
            if (remints.current >= 1) return null;
            remints.current += 1;
            try {
              const fresh = await recording.mutateAsync();
              return fresh.url;
            } catch {
              return null;
            }
          }}
        />
        <p className="text-meta text-ink-faint">
          Opening this recording was recorded in your audit log. The link is private to this
          page and is refreshed automatically while you listen.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {recording.error != null && <ProblemNotice error={recording.error} />}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <button
          type="button"
          disabled={recording.isPending}
          onClick={() => recording.mutate()}
          className={SECONDARY_BUTTON}
        >
          <AudioLines aria-hidden className="h-4 w-4" />
          {recording.isPending ? "Preparing…" : "Listen to this call"}
        </button>
        <span className="text-meta text-ink-faint">Opening the recording is recorded in your audit log.</span>
      </div>
    </div>
  );
}
