"use client";

import { useEffect, useId, useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { FIELD_INLINE, ProblemNotice, QUIET_ICON_BUTTON, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  MAX_NOTE,
  VOTE_REASONS,
  useRateAnswer,
  type AnswerVote,
  type VoteReason,
} from "@/lib/copilot/rating";

/**
 * Thumbs up or down under one Pip answer (D-937), with an optional reason for a thumbs
 * down. Pressing the chosen thumb again takes the vote back. The choice shows at once and
 * goes back to what the server holds if the save fails, with one line saying so.
 */
export function AnswerRating({
  turnId,
  session,
  realm,
  vote: savedVote = null,
  reason: savedReason = null,
}: {
  turnId: string;
  session: Session;
  realm: "client" | "admin";
  vote?: AnswerVote | null;
  reason?: VoteReason | null;
}) {
  const rate = useRateAnswer(session, realm, turnId);
  // Inline: the vote goes back on screen and the reason shows under the thumbs, so a toast
  // would say it twice. Each save passes its own callbacks to put the vote back.
  useActionFeedback(rate, { errorDisplay: "inline" });
  const [vote, setVote] = useState<AnswerVote | null>(savedVote);
  const [reason, setReason] = useState<VoteReason | null>(savedReason);
  const [picking, setPicking] = useState(false);
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<"idle" | "saved" | "failed">("idle");
  const noteId = useId();

  // A newer stored page (another device voted) wins over what this one last showed.
  useEffect(() => {
    setVote(savedVote);
    setReason(savedReason);
  }, [savedVote, savedReason]);

  const save = (next: AnswerVote | null, nextReason: VoteReason | null, nextNote = "") => {
    const before = { vote, reason };
    setVote(next);
    setReason(nextReason);
    setStatus("idle");
    rate.mutate(
      { vote: next, reason: nextReason, note: nextNote },
      {
        onSuccess: () => setStatus("saved"),
        onError: () => {
          setVote(before.vote);
          setReason(before.reason);
          setStatus("failed");
        },
      },
    );
  };

  const pressUp = () => {
    setPicking(false);
    save(vote === "up" ? null : "up", null);
  };
  const pressDown = () => {
    if (vote === "down") {
      setPicking(false);
      save(null, null);
      return;
    }
    save("down", null);
    setPicking(true);
  };
  const pick = (value: VoteReason) => {
    setReason(value);
    if (value !== "other") {
      setPicking(false);
      save("down", value);
    }
  };

  return (
    <div className="mt-1.5 text-xs text-ink-muted">
      <div className="flex items-center gap-0.5" role="group" aria-label="Rate this answer">
        <button
          type="button"
          className={QUIET_ICON_BUTTON}
          aria-pressed={vote === "up"}
          aria-label="Helpful"
          title="Helpful"
          onClick={pressUp}
        >
          <ThumbsUp
            aria-hidden
            className={`h-3.5 w-3.5 ${vote === "up" ? "fill-current text-brand" : ""}`}
          />
        </button>
        <button
          type="button"
          className={QUIET_ICON_BUTTON}
          aria-pressed={vote === "down"}
          aria-label="Not helpful"
          title="Not helpful"
          onClick={pressDown}
        >
          <ThumbsDown
            aria-hidden
            className={`h-3.5 w-3.5 ${vote === "down" ? "fill-current text-ink" : ""}`}
          />
        </button>
        <span role="status" className="ml-1">
          {status === "saved" && vote !== null && !picking ? "Thanks" : null}
          {status === "failed" ? "Couldn't save. Try again." : null}
        </span>
      </div>
      {status === "failed" && rate.error ? (
        <div className="mt-1">
          <ProblemNotice error={rate.error} />
        </div>
      ) : null}
      {picking && vote === "down" && (
        <div className="mt-1 space-y-1.5" role="group" aria-label="What went wrong?">
          <p className="text-ink-faint">What went wrong?</p>
          <div className="flex flex-wrap gap-1.5">
            {VOTE_REASONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-pressed={reason === option.value}
                onClick={() => pick(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
          {reason === "other" && (
            <form
              noValidate
              className="flex flex-wrap items-center gap-1.5"
              onSubmit={(event) => {
                event.preventDefault();
                setPicking(false);
                save("down", "other", note);
              }}
            >
              <label htmlFor={noteId} className="sr-only">
                In a few words
              </label>
              <input
                id={noteId}
                className={`${FIELD_INLINE} min-w-0 flex-1 text-xs`}
                maxLength={MAX_NOTE}
                placeholder="In a few words (optional)"
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <button type="submit" className={SECONDARY_BUTTON_SM}>
                Send
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
