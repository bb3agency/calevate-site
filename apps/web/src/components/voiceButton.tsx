"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

import { ModalDialog } from "@/components/modalDialog";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";

/** A clip stops itself here: our speech-to-text takes clips under 30 seconds (Sarvam's REST
 *  reference, `apps/workers/speech_to_text.py`). */
export const MAX_RECORDING_S = 30;

/**
 * The container the browser records in, best first. Chrome, Firefox and Safari from 18.4
 * record WebM/Opus; older iOS Safari records only MP4/AAC, so it is asked for next rather
 * than assumed. Both are on the server's accepted list (`teach/teaching.VOICE_CONTENT_TYPES`).
 * An empty string lets the browser use its own default.
 */
const RECORDING_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"] as const;

export function recordingMimeType(
  supports: (type: string) => boolean = (type) => MediaRecorder.isTypeSupported(type),
): string {
  return RECORDING_TYPES.find((type) => supports(type)) ?? "";
}

/** What the browser says about the microphone before we ask for it. */
async function microphonePermission(): Promise<PermissionState | "unknown"> {
  try {
    const status = await navigator.permissions?.query({ name: "microphone" as PermissionName });
    return status?.state ?? "unknown";
  } catch {
    // Safari and Firefox may not know the "microphone" name, or the API at all.
    return "unknown";
  }
}

function errorName(error: unknown): string {
  return error instanceof Error || error instanceof DOMException ? error.name : "";
}

/**
 * "Say it". The browser's own microphone prompt is easy to miss or dismiss, and once
 * refused it never shows again, so we explain before it appears: already allowed records
 * straight away; not yet asked opens our dialog, whose button triggers the browser's
 * prompt; blocked opens the same dialog saying how to unblock it.
 *
 * Used by the teach box's voice note and the spoken brief of "Meet your agent" (D-855).
 */
export function VoiceButton({
  disabled,
  onRecorded,
  onTypeInstead,
  label = "Say it",
  why = "Say what your agents should know. Your browser will ask to use the microphone; choose Allow.",
}: {
  disabled: boolean;
  onRecorded: (blob: Blob) => void;
  /** Close the question and put the cursor in the text box. */
  onTypeInstead: () => void;
  label?: string;
  /** The dialog's sentence before the browser asks for the microphone. */
  why?: string;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<"ask" | "blocked" | null>(null);
  const [starting, setStarting] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    recorder.current?.stop();
    setRecording(false);
  };

  useEffect(() => () => stop(), []);

  const start = async () => {
    setStarting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setAsking(null);
      const type = recordingMimeType();
      const media = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      const chunks: Blob[] = [];
      media.ondataavailable = (event) => chunks.push(event.data);
      media.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunks, { type: media.mimeType.split(";")[0] || "audio/webm" });
        if (blob.size > 0) onRecorded(blob);
      };
      recorder.current = media;
      media.start();
      setSeconds(0);
      setRecording(true);
      timer.current = setInterval(() => {
        setSeconds((s) => {
          if (s + 1 >= MAX_RECORDING_S) stop();
          return s + 1;
        });
      }, 1000);
    } catch (caught) {
      const name = errorName(caught);
      if (name === "NotAllowedError") {
        setAsking("blocked");
      } else {
        setAsking(null);
        setError(
          name === "NotFoundError"
            ? "No microphone found on this device."
            : "We could not use your microphone. Allow it in your browser, or type it.",
        );
      }
    } finally {
      setStarting(false);
    }
  };

  const press = async () => {
    setError(null);
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record. Type it instead.");
      return;
    }
    const state = await microphonePermission();
    if (state === "granted") {
      await start();
      return;
    }
    setAsking(state === "denied" ? "blocked" : "ask");
  };

  const typeInstead = () => {
    setAsking(null);
    // After the dialog has handed focus back to the button, so the text box keeps it.
    setTimeout(onTypeInstead, 0);
  };

  const left = MAX_RECORDING_S - seconds;
  return (
    <>
      {recording ? (
        <button type="button" className={SECONDARY_BUTTON} onClick={stop}>
          <Square aria-hidden className="h-3.5 w-3.5 fill-current text-danger" />
          Stop · <span className="tabular-nums">0:{String(seconds).padStart(2, "0")}</span>
        </button>
      ) : (
        <button type="button" className={SECONDARY_BUTTON} onClick={() => void press()} disabled={disabled || starting}>
          <Mic aria-hidden className="h-4 w-4" />
          {label}
        </button>
      )}
      {recording ? (
        <span className="text-meta text-ink-muted" aria-live="polite">
          Recording, {left <= 10 ? `${left} seconds left` : `up to ${MAX_RECORDING_S} seconds`}
        </span>
      ) : null}
      {error ? (
        <p role="alert" className="basis-full text-meta text-danger">
          {error}
        </p>
      ) : null}
      {asking ? (
        <ModalDialog
          title={asking === "blocked" ? "Your microphone is blocked" : "Allow your microphone"}
          description={
            <p>
              {asking === "blocked"
                ? "Turn it on for this site: click the icon at the left of the address bar, set Microphone to Allow, then press Try again."
                : why}
            </p>
          }
          onClose={() => setAsking(null)}
          actions={
            <>
              <button type="button" className={SECONDARY_BUTTON} onClick={typeInstead}>
                Type it instead
              </button>
              <button type="button" className={PRIMARY_BUTTON} onClick={() => void start()} disabled={starting}>
                {asking === "blocked" ? "Try again" : "Allow microphone"}
              </button>
            </>
          }
        />
      ) : null}
    </>
  );
}
