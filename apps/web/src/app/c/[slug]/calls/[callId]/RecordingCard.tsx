"use client";

import { AudioLines } from "lucide-react";

import { Card, ProblemNotice } from "@/components/ui";
import {
  CallAudioPlayer,
  type CallAudioPlayerHandle,
} from "@/components/callAudioPlayer";

import type { useRecordingLink } from "./transcriptAccess";

/**
 * A short-lived, presigned link to OUR copy of the audio — never the engine's URL.
 *
 * Fetched on a click rather than with the page: the endpoint mints a signed URL with a
 * ticking expiry AND writes an `audit_log` row (crm/routes.py), so requesting one for
 * every visitor who never presses play would both burn the link and record a listen
 * that did not happen.
 *
 * Rendered into an `<audio>` element rather than an anchor. A signed URL in an `href`
 * is a URL a browser keeps in history and hands to the next page as a referrer, and the
 * signature is the credential.
 */
export function RecordingCard({
  recording,
  playerRef,
  onTimeUpdate,
  durationS,
}: {
  recording: ReturnType<typeof useRecordingLink>;
  playerRef: React.Ref<CallAudioPlayerHandle>;
  onTimeUpdate: (seconds: number) => void;
  durationS: number | null;
}) {
  return (
    <Card title="Recording">
      {recording.error && <ProblemNotice error={recording.error} />}
      {recording.data ? (
        <div className="space-y-2">
          <CallAudioPlayer
            ref={playerRef}
            src={recording.data.url}
            fallbackDurationS={recording.data.duration_s ?? durationS}
            onTimeUpdate={onTimeUpdate}
            onExpired={async () => {
              // Mint a replacement rather than surfacing the browser's bare media error.
              // `mutateAsync` REJECTS on failure, so the catch is what turns "we could
              // not get you a new link" into the player's own refusal instead of an
              // unhandled rejection in the console.
              try {
                const fresh = await recording.mutateAsync();
                return fresh.url;
              } catch {
                return null;
              }
            }}
          />
          <p className="text-xs text-ink-faint">
            Opening this recording was recorded in your audit log. The link is private to this
            page and is refreshed automatically while you listen.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <button
            type="button"
            disabled={recording.isPending}
            onClick={() => recording.mutate()}
            className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
          >
            <AudioLines className="h-4 w-4" />
            {recording.isPending ? "Preparing…" : "Listen to this call"}
          </button>
          <p className="text-xs text-ink-faint">Opening the recording is recorded in your audit log.</p>
        </div>
      )}
    </Card>
  );
}
