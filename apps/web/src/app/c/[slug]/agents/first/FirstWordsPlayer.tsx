"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ApiProblem, type Session } from "@/lib/api/client";
import {
  partBlob,
  useFirstWords,
  useSpeakFirstWords,
  type FirstWordsPart,
  type FirstWordsWork,
} from "@/lib/api/firstWords";

/** Said under the button: what pressing it is, and is not. */
export const NO_CALL_NOTE = "No call, no minutes.";

/**
 * "HEAR ITS FIRST WORDS" (W1.3): what a caller hears first on this work, in its voice,
 * played in the page. No call is placed, so nothing is ticked and no minute is used.
 *
 * The words are the server's, composed as the calls compose them (the opening with every
 * notice it carries, whole), never a line typed here. The server is asked first without
 * speaking, so the button is offered only where a press can play: a Clear voice gets its
 * words and one line saying why they cannot be heard here, never a sample in another voice.
 *
 * The audio comes in parts (the engine speaks a few sentences at a time); they play one after
 * another, and the words show with the part being spoken in full ink.
 */
export function FirstWordsPlayer({
  session,
  agentId,
  work,
  lang,
  version,
}: {
  session: Session;
  agentId: string;
  work: FirstWordsWork | null;
  /** The language the words are in, for the transcript's `lang`. */
  lang?: string;
  /** What the work says first now, so a rewritten script is read again. */
  version: string | null;
}) {
  const known = useFirstWords(session, agentId, work, version);
  const speak = useSpeakFirstWords(session, agentId, work);
  // Its refusal (the day's samples used, say) is drawn under the button, so no toast repeats it.
  useActionFeedback(speak, { errorDisplay: "inline" });
  const audio = useRef<HTMLAudioElement>(null);
  const [parts, setParts] = useState<readonly FirstWordsPart[]>([]);
  const [urls, setUrls] = useState<readonly string[]>([]);
  // The part on the element, and whether the last one has played to its end.
  const [at, setAt] = useState<number | null>(null);
  const [finished, setFinished] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [refused, setRefused] = useState(false);
  const wantsPlay = useRef(false);

  // A rewritten script is new words: what was fetched for the old ones is let go.
  useEffect(() => {
    speak.reset();
    setParts([]);
    setAt(null);
    setFinished(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  useEffect(() => {
    const made = parts.map((part) => URL.createObjectURL(partBlob(part)));
    setUrls(made);
    return () => made.forEach((url) => URL.revokeObjectURL(url));
  }, [parts]);

  const playFrom = (index: number) => {
    const element = audio.current;
    const url = urls[index];
    if (!element || url === undefined) return;
    setAt(index);
    setFinished(false);
    if (element.src !== url) element.src = url;
    void Promise.resolve(element.play()).catch((error: unknown) => {
      setPlaying(false);
      // The first press fetches the audio, so play() runs after the press; a browser that lets
      // sound start only from a tap refuses it. The audio is here now, so the next tap plays.
      if (error instanceof DOMException && error.name === "NotAllowedError") setRefused(true);
    });
  };

  // The first press asked for the audio; play as soon as it is on hand.
  useEffect(() => {
    if (wantsPlay.current && urls.length > 0) {
      wantsPlay.current = false;
      playFrom(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urls]);

  // Stop the sound when the player leaves the page.
  useEffect(() => {
    const element = audio.current;
    return () => element?.pause();
  }, []);

  const data = known.data;
  if (work === null || data === undefined) return null;
  if (!data.playable) {
    return data.unavailable_rule === "first_words_needs_studio_voice" && data.unavailable_reason ? (
      <p className="text-meta text-ink-muted">{data.unavailable_reason}</p>
    ) : null;
  }

  const press = () => {
    setRefused(false);
    const element = audio.current;
    if (playing) {
      element?.pause();
      return;
    }
    if (urls.length > 0) {
      if (at === null || finished) playFrom(0);
      else playFrom(at);
      return;
    }
    wantsPlay.current = true;
    speak.mutate(undefined, { onSuccess: (spoken) => setParts(spoken.parts ?? []) });
  };
  const problem = speak.error instanceof ApiProblem ? speak.error : null;
  const failure = speak.error
    ? problem
      ? [problem.message, problem.remediation].filter(Boolean).join(" ")
      : "It could not be played. Try again."
    : refused
      ? "Ready. Tap again to listen."
      : null;
  const words = parts;

  return (
    <div className="min-w-0 rounded-card border border-line bg-surface-muted/60 px-3 py-3 sm:px-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <ActionButton
          variant="secondary-sm"
          status={speak.isPending ? "pending" : "idle"}
          pendingLabel="Getting it ready…"
          onClick={press}
          aria-label={playing ? "Pause its first words" : "Hear its first words"}
        >
          {playing ? (
            <Pause aria-hidden className="h-4 w-4" />
          ) : finished ? (
            <RotateCcw aria-hidden className="h-4 w-4" />
          ) : (
            <Play aria-hidden className="h-4 w-4" />
          )}
          <span aria-hidden>{playing ? "Pause" : finished ? "Hear it again" : "Hear its first words"}</span>
        </ActionButton>
        <span className="text-meta text-ink-muted">{NO_CALL_NOTE}</span>
      </div>
      {words.length > 0 ? (
        // The words being heard: the transcript of the audio, the part being spoken in ink.
        <p lang={lang} className="mt-2.5 break-words text-body leading-relaxed">
          {words.map((part, index) => (
            <span
              key={index}
              className={`transition-colors duration-(--duration-fast) ${
                index === at && playing ? "text-ink" : "text-ink-muted"
              }`}
            >
              {index > 0 ? " " : ""}
              {part.text}
            </span>
          ))}
        </p>
      ) : null}
      {failure ? (
        <p role="status" className="mt-2 text-meta text-warn">
          {failure}
        </p>
      ) : null}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- Its transcript is the paragraph
          above, shown whole while it plays. */}
      <audio
        ref={audio}
        preload="none"
        className="hidden"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          if (at !== null && at < urls.length - 1) playFrom(at + 1);
          else {
            setPlaying(false);
            setFinished(true);
          }
        }}
      />
    </div>
  );
}
