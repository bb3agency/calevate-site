"use client";

import { useEffect, useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { useDiscardTeaching, useHearVoiceNote, useTeaching } from "@/lib/api/teach";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

const FAILURE: Record<string, string> = {
  voice_unreadable: "We could not hear that recording. Try again somewhere quieter, or type it.",
  nothing_heard: "We did not hear any words. Try recording again, or type it.",
  upload_missing: "That recording went missing. Record it again.",
  /* Set by the worker sweep `interrupted_work.py` when a run stopped part way. */
  interrupted: "That stopped before we finished listening. Record it again, or type it.",
};

export interface VoiceWords {
  /** Send a recording to be heard. */
  record: (blob: Blob) => void;
  /** The recording is being heard. */
  listening: boolean;
  /** Why the last recording gave no words, in a sentence; null when it did. */
  failure: string | null;
  /** A request that failed outright (upload refused, discard refused). */
  error: Error | null;
}

/**
 * A voice note heard into words for a text box: the teach box's path (D-821), shared by
 * every box that takes a spoken answer. The words come back for the person to check, the
 * heard teaching is discarded, and `onWords` receives them.
 */
export function useVoiceWords(session: Session, onWords: (words: string) => void): VoiceWords {
  const hear = useHearVoiceNote(session);
  const discard = useDiscardTeaching(session);
  // Both refusals are drawn by the caller under its box.
  useActionFeedback(hear, { errorDisplay: "inline" });
  useActionFeedback(discard, { errorDisplay: "inline" });
  const [heardId, setHeardId] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const heard = useTeaching(session, heardId);

  const note = heard.data;
  const discardNote = discard.mutate;
  useEffect(() => {
    if (!note || note.id !== heardId) return;
    if (note.status === "heard") {
      onWords(note.words ?? "");
      setHeardId(null);
      discardNote(note.id);
    } else if (note.status === "failed") {
      setFailure(note.error_code ?? "voice_unreadable");
      setHeardId(null);
    }
  }, [note, heardId, discardNote, onWords]);

  return {
    record: (blob) => {
      setFailure(null);
      hear.mutate({ file: blob }, { onSuccess: (started) => setHeardId(started.id) });
    },
    listening:
      hear.isPending ||
      (heardId !== null && note?.status !== "heard" && note?.status !== "failed"),
    failure:
      failure === null
        ? null
        : (lookup(FAILURE, failure) ?? "We could not hear that recording. Type it instead."),
    error: (hear.error as Error | null) ?? (discard.error as Error | null) ?? null,
  };
}
