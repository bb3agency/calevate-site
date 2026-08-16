"use client";

import { useCallback, useEffect, useId, useImperativeHandle, useRef, useState } from "react";
import {
  AlertTriangle,
  Gauge,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Volume2,
  VolumeX,
} from "lucide-react";

import { SECONDARY_BUTTON_SM } from "@/components/ui";

/**
 * The player for one call recording — built rather than borrowed, and the reasons are
 * specific enough to be worth stating.
 *
 * `<audio controls>` was what this screen had. It plays audio, and for reviewing a sales
 * call it is the wrong instrument for three reasons that are not cosmetic:
 *
 * 1. **No playback rate.** The single most-used control when a person reviews calls for
 *    a living. Chrome hides rate behind a context menu, Safari has none, Firefox's is
 *    three clicks deep. An owner checking twenty calls at 1x is an owner who checks five.
 * 2. **No skip.** Scrubbing a 40-minute call with a 300-pixel native bar is ±90 seconds
 *    per pixel-ish; "back ten seconds because I missed the number" is not expressible.
 * 3. **Nothing to hang the transcript off.** The turns on this screen carry `start_ms`.
 *    A native element exposes no seek affordance to its siblings, so the transcript and
 *    the audio stay two unrelated things on one page.
 *
 * NO WAVEFORM, deliberately. Drawing one means either shipping a peaks library
 * (~40 kB and a canvas render loop) or decoding the whole file client-side, which for a
 * one-hour recording means holding tens of megabytes of PCM in a browser tab. The seek
 * bar plus a buffered range gives the two things a waveform is actually used for here —
 * where am I, and how much has loaded — at zero cost. Revisit only with a measured
 * complaint, not on taste.
 *
 * ## The expiry contract, which is the part that used to be broken
 *
 * The `src` is a presigned URL and it dies. The server now sizes that window from the
 * call's own duration, so it should outlive one pass — but "should" is not a design.
 * When the element errors mid-playback this asks the parent for a fresh link through
 * `onExpired` and RESTORES the position, so the listener hears a stall rather than
 * losing their place. `MEDIA_ERR_NETWORK` and `MEDIA_ERR_SRC_NOT_SUPPORTED` are both
 * treated as expiry candidates because S3 answers an expired signature with a 403 whose
 * body is XML, and browsers report that as either one depending on when it arrives.
 *
 * One retry, then a refusal a person can act on. Re-minting in a loop against a bucket
 * that is genuinely gone is how a screen becomes a request generator.
 */

export type CallAudioPlayerHandle = {
  /** Jump to `seconds` and start playing. Used by the transcript to seek to a turn. */
  seekTo: (seconds: number) => void;
};

const RATES = [1, 1.25, 1.5, 2] as const;
const SKIP_S = 10;

/** `137` -> `2:17`, `3730` -> `1:02:10`. Hours only appear when there are hours. */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  const s = String(whole % 60).padStart(2, "0");
  const m = Math.floor(whole / 60) % 60;
  const h = Math.floor(whole / 3600);
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function CallAudioPlayer({
  src,
  fallbackDurationS,
  onTimeUpdate,
  onExpired,
  ref,
}: {
  src: string;
  /**
   * The call's metered length. Drawn on the seek bar until the browser has fetched
   * enough of the file to report its own `duration` — which is `NaN` at first paint, and
   * a scrubber with no end is a scrubber nobody drags.
   */
  fallbackDurationS: number | null;
  onTimeUpdate?: (seconds: number) => void;
  /**
   * Ask for a fresh presigned URL. Resolve with the new one, or `null` if a new link
   * could not be minted — the player then shows a refusal instead of retrying.
   */
  onExpired?: () => Promise<string | null>;
  ref?: React.Ref<CallAudioPlayerHandle>;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [loaded, setLoaded] = useState<number | null>(null);
  const [buffered, setBuffered] = useState(0);
  const [rate, setRate] = useState<(typeof RATES)[number]>(1);
  const [muted, setMuted] = useState(false);
  const [failed, setFailed] = useState(false);
  // The URL actually on the element. Starts as the prop and is replaced in place by a
  // re-mint, so a refreshed link does not remount the element and lose the position.
  const [liveSrc, setLiveSrc] = useState(src);
  // One re-mint per element. Reset whenever the parent hands down a genuinely new link.
  const remintedRef = useRef(false);
  const sliderId = useId();

  useEffect(() => {
    setLiveSrc(src);
    remintedRef.current = false;
    setFailed(false);
  }, [src]);

  // The browser's own answer wins once it has one; `fallbackDurationS` only covers the
  // window before that. They can differ by a fraction of a second and the audio is the
  // authority on its own length.
  const duration = loaded ?? (fallbackDurationS && fallbackDurationS > 0 ? fallbackDurationS : 0);

  const seekTo = useCallback((seconds: number) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = Math.max(0, seconds);
    setCurrent(el.currentTime);
    void el.play().catch(() => {
      /* Autoplay refusal is not an error worth a banner: the play button still works. */
    });
  }, []);

  useImperativeHandle(ref, () => ({ seekTo }), [seekTo]);

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) {
      void el.play().catch(() => setFailed(true));
    } else {
      el.pause();
    }
  }, []);

  const nudge = useCallback((delta: number) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = Math.min(Math.max(0, el.currentTime + delta), el.duration || Infinity);
    setCurrent(el.currentTime);
  }, []);

  const cycleRate = useCallback(() => {
    const el = audioRef.current;
    const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
    setRate(next);
    if (el) el.playbackRate = next;
  }, [rate]);

  /**
   * An error on the element. The signature may simply have expired, so ask for a new
   * one ONCE and put the listener back where they were; anything else, or a second
   * failure, is a refusal rather than a retry.
   */
  const handleError = useCallback(async () => {
    const el = audioRef.current;
    if (!el || !onExpired || remintedRef.current) {
      setFailed(true);
      return;
    }
    remintedRef.current = true;
    const resumeAt = el.currentTime;
    const wasPlaying = !el.paused;
    const fresh = await onExpired();
    if (!fresh) {
      setFailed(true);
      return;
    }
    setLiveSrc(fresh);
    // The element reloads on the new `src`; restore the position once it can accept one.
    const restore = () => {
      el.currentTime = resumeAt;
      if (wasPlaying) void el.play().catch(() => setFailed(true));
      el.removeEventListener("loadedmetadata", restore);
    };
    el.addEventListener("loadedmetadata", restore);
  }, [onExpired]);

  const pct = duration > 0 ? (current / duration) * 100 : 0;
  const bufferedPct = duration > 0 ? Math.min(100, (buffered / duration) * 100) : 0;

  return (
    <div className="space-y-3">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- The transcript rendered
          directly above IS this recording's caption track, in the same view and in the
          same scroll position (WCAG 1.2.2 is met by a transcript). A <track> here would
          be a second copy of the same text, behind a control, free to drift from the one
          the compliance rules actually govern. Disabled at the site rather than in
          eslint.config.mjs so the next <audio> added anywhere still has to answer. */}
      <audio
        ref={audioRef}
        src={liveSrc}
        preload="metadata"
        onLoadedMetadata={(e) => {
          const el = e.currentTarget;
          if (Number.isFinite(el.duration)) setLoaded(el.duration);
          el.playbackRate = rate;
        }}
        onTimeUpdate={(e) => {
          const t = e.currentTarget.currentTime;
          setCurrent(t);
          onTimeUpdate?.(t);
        }}
        onProgress={(e) => {
          const el = e.currentTarget;
          if (el.buffered.length > 0) setBuffered(el.buffered.end(el.buffered.length - 1));
        }}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => void handleError()}
        className="hidden"
      />

      {failed && (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            This recording stopped playing and could not be reloaded. Reload the page to try
            again — the audio itself is still stored.
          </span>
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? "Pause recording" : "Play recording"}
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-strong text-white transition hover:opacity-90 dark:bg-brand-bright dark:text-black"
        >
          {playing ? (
            <Pause className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Play className="ml-0.5 h-4 w-4" aria-hidden="true" />
          )}
        </button>

        <div className="min-w-0 flex-1">
          {/* The bar is a real range input so it is keyboard- and screen-reader-native:
              arrows scrub, Home/End jump, and the value is announced as a time rather
              than as a number of seconds. A div with a drag handler is none of those. */}
          <div className="relative">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 overflow-hidden rounded-full bg-black/10 dark:bg-white/15"
            >
              <div className="h-full bg-black/15 dark:bg-white/20" style={{ width: `${bufferedPct}%` }} />
              <div
                className="absolute inset-y-0 left-0 bg-brand-strong dark:bg-brand-bright"
                style={{ width: `${pct}%` }}
              />
            </div>
            <input
              id={sliderId}
              type="range"
              min={0}
              max={Math.max(1, Math.floor(duration))}
              step={1}
              value={Math.floor(current)}
              onChange={(e) => {
                const el = audioRef.current;
                const next = Number(e.target.value);
                setCurrent(next);
                if (el) el.currentTime = next;
              }}
              aria-label="Seek within the recording"
              aria-valuetext={`${formatClock(current)} of ${formatClock(duration)}`}
              className="relative w-full cursor-pointer appearance-none bg-transparent [&::-moz-range-thumb]:h-3 [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-brand-strong [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-brand-strong dark:[&::-moz-range-thumb]:bg-brand-bright dark:[&::-webkit-slider-thumb]:bg-brand-bright"
            />
          </div>
          <div className="mt-0.5 flex justify-between text-xs tabular-nums text-ink-faint">
            <span>{formatClock(current)}</span>
            {/* Zero duration means the metadata has not arrived AND the call carried no
                metered length. Showing "0:00" there would be a number about the audio
                that is not true of it. */}
            <span>{duration > 0 ? formatClock(duration) : "—"}</span>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => nudge(-SKIP_S)}
          className={SECONDARY_BUTTON_SM}
          aria-label={`Back ${SKIP_S} seconds`}
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
          {SKIP_S}s
        </button>
        <button
          type="button"
          onClick={() => nudge(SKIP_S)}
          className={SECONDARY_BUTTON_SM}
          aria-label={`Forward ${SKIP_S} seconds`}
        >
          <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
          {SKIP_S}s
        </button>
        <button
          type="button"
          onClick={cycleRate}
          className={SECONDARY_BUTTON_SM}
          aria-label={`Playback speed, currently ${rate} times. Press to change.`}
        >
          <Gauge className="h-3.5 w-3.5" aria-hidden="true" />
          {rate}×
        </button>
        <button
          type="button"
          onClick={() => {
            const el = audioRef.current;
            const next = !muted;
            setMuted(next);
            if (el) el.muted = next;
          }}
          className={SECONDARY_BUTTON_SM}
          aria-label={muted ? "Unmute" : "Mute"}
        >
          {muted ? (
            <VolumeX className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Volume2 className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
      </div>
    </div>
  );
}
