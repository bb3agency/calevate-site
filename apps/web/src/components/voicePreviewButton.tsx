"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";

import { ActionButton } from "@/components/arc/feedback";
import { ApiProblem, type Session } from "@/lib/api/client";
import { useVoicePreview } from "@/lib/api/voicePreview";

/** 36px round, 44px on touch (WCAG 2.5.8), so a row's play target stays reachable. */
/** The round icon-only shape, on top of `ActionButton`'s secondary-sm look. */
const COMPACT_BUTTON = "h-9 w-9 shrink-0 rounded-full! px-0! py-0! touch:h-11 touch:w-11";

/**
 * The one clip playing on the page. Pressing play on a second voice pauses the first —
 * two voices talking over each other is not a comparison anybody can make.
 */
let playing: HTMLAudioElement | null = null;

/**
 * Play / pause one voice's preview clip.
 *
 * The bytes are read on the first press only, through the authenticated transport, and
 * handed to a hidden `<audio>` as an object URL that is revoked when the button unmounts or
 * the clip changes. The control is a real button whose accessible name says which voice it
 * plays and whether pressing it plays or pauses.
 */
export function VoicePreviewButton({
  session,
  path,
  voiceId,
  label,
  compact = false,
}: {
  session: Session;
  path: string;
  voiceId: string;
  /** The voice's name, for the button's accessible name. */
  label: string;
  /** A round icon-only button, for a row in a long list. The name stays in the label. */
  compact?: boolean;
}) {
  const [requested, setRequested] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [refused, setRefused] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const clip = useVoicePreview(session, path, voiceId, requested);

  // One object URL per blob, revoked when the blob changes or the button goes away.
  useEffect(() => {
    if (!clip.data) return;
    const url = URL.createObjectURL(clip.data);
    setSrc(url);
    return () => {
      URL.revokeObjectURL(url);
      setSrc(null);
    };
  }, [clip.data]);

  // The first press asked for the bytes; play as soon as they are on the element.
  const wantsPlay = useRef(false);
  useEffect(() => {
    if (src && wantsPlay.current) {
      wantsPlay.current = false;
      start();
    }
  }, [src]);

  // Stop the sound when the button leaves the page.
  useEffect(() => {
    const element = audio.current;
    return () => {
      if (element && playing === element) {
        element.pause();
        playing = null;
      }
    };
  }, []);

  function start() {
    const element = audio.current;
    if (!element) return;
    if (playing && playing !== element) playing.pause();
    playing = element;
    void Promise.resolve(element.play()).catch((error: unknown) => {
      setIsPlaying(false);
      // The first press only fetches the clip, so this play() runs after the press, and a
      // browser that lets sound start only from a tap refuses it. The clip is loaded by
      // then, so the next press plays at once; saying so beats a button that just stopped.
      if (error instanceof DOMException && error.name === "NotAllowedError") setRefused(true);
    });
  }

  function toggle() {
    setRefused(false);
    const element = audio.current;
    if (isPlaying && element) {
      element.pause();
      return;
    }
    if (src) {
      start();
      return;
    }
    wantsPlay.current = true;
    setRequested(true);
    if (clip.isError) void clip.refetch();
  }

  const loading = requested && clip.isFetching && !src;
  const failure =
    clip.error instanceof ApiProblem && clip.error.status === 404
      ? "No preview is stored for this voice yet."
      : clip.error
        ? "The preview could not be played. Try again."
        : refused
          ? "Ready. Tap again to listen."
          : null;

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <ActionButton
        variant="secondary-sm"
        className={compact ? COMPACT_BUTTON : undefined}
        status={loading ? "pending" : "idle"}
        pendingLabel={compact ? "" : <span aria-hidden>Listen</span>}
        onClick={toggle}
        aria-label={`${isPlaying ? "Pause" : "Play"} the preview of ${label}`}
      >
        {isPlaying ? <Pause aria-hidden className="h-4 w-4" /> : <Play aria-hidden className="h-4 w-4" />}
        {!compact && <span aria-hidden>{isPlaying ? "Pause" : "Listen"}</span>}
      </ActionButton>
      {failure && (
        <span role="status" className="text-xs text-warn">
          {failure}
        </span>
      )}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- The clip exists to be HEARD:
          its content is what the voice sounds like, a sensory experience no caption can carry
          (WCAG 1.2.1's sensory exception). The voice's name and language are on the row. */}
      <audio
        ref={audio}
        src={src ?? undefined}
        preload="none"
        className="hidden"
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
      />
    </span>
  );
}
