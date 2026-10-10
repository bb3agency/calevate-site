"use client";

import { AudioLines } from "lucide-react";

import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import {
  CallAudioPlayer,
  type CallAudioPlayerHandle,
} from "@/components/callAudioPlayer";
import type { CallDetail } from "@/lib/api/client";

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
}: {
  recording: ReturnType<typeof useRecordingLink>;
  playerRef: React.Ref<CallAudioPlayerHandle>;
  onTimeUpdate: (seconds: number) => void;
  durationS: number | null;
  moments: CallDetail["moments"];
}) {
  if (recording.data) {
    return (
      <div className="space-y-2">
        <CallAudioPlayer
          ref={playerRef}
          src={recording.data.url}
          fallbackDurationS={recording.data.duration_s ?? durationS}
          onTimeUpdate={onTimeUpdate}
          marks={moments.map((m) => ({ atS: m.at_ms / 1000, label: m.label }))}
          onExpired={async () => {
            // Mint a replacement rather than surfacing the browser's bare media error.
            // `mutateAsync` rejects on failure, and the catch turns that into the
            // player's own refusal instead of an unhandled rejection.
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
