"use client";

/**
 * THE OPENING LINE'S ROOM, and the way back when a notice switch had none (D-846).
 *
 * What an agent says first is the notices switched on and then its opening line, and the
 * calling system speaks only so many characters there. The server sends the room the line
 * has (`greeting_budget`), measured the way the publish measures it, so this screen only
 * counts the line being typed against that number and never re-joins the sentences itself.
 *
 * Characters are counted as code points, which is how the server counts them: a Telugu
 * letter is one either way, an emoji is one here and two in a JavaScript `length`.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { FIELD, FIELD_LABEL, ProblemNotice } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useReplaceOpeningLine } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";

/** The problem code for a notice switch refused because the opening line leaves no room. */
export const NOTICE_NEEDS_ROOM = "opening_line_too_long_for_notice";

export function problemCode(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

/** Characters as the server counts them, after the trim it applies. */
export function spokenLength(text: string): number {
  return [...text.trim()].length;
}

/** "N characters left", or how far over, for a line against its room. */
export function roomLabel(text: string, room: number): { label: string; over: boolean } {
  const left = room - spokenLength(text);
  if (left >= 0) {
    return { label: `${left} ${left === 1 ? "character" : "characters"} left`, over: false };
  }
  const over = -left;
  return { label: `${over} ${over === 1 ? "character" : "characters"} too long`, over: true };
}

/** The live counter under an opening-line box. Polite, so it is read when typing pauses. */
export function RoomCounter({ id, text, room }: { id: string; text: string; room: number }) {
  const { label, over } = roomLabel(text, room);
  return (
    <p
      id={id}
      aria-live="polite"
      className={`mt-1 text-xs tabular-nums ${over ? "font-medium text-warn" : "text-ink-muted"}`}
    >
      {label}
    </p>
  );
}

/**
 * Shown in place of a refused notice switch: the refusal, the opening line in a box with
 * its room counting down, a Save that puts the shorter line live and then retries the
 * switch, and Pip as the other way to shorten it (prefilled, never sent).
 */
export function OpeningLineFix({
  agent,
  error,
  room,
  retry,
  retrying,
}: {
  agent: Agent;
  /** The refusal, shown as the server worded it. */
  error: unknown;
  /** The room the line has once the refused switch is on. */
  room: number;
  /** Switch it on again, once the shorter line is live. */
  retry: () => void;
  retrying: boolean;
}) {
  const session = useClientSession();
  const replace = useReplaceOpeningLine(session, agent.id);
  const replaceFeedback = useActionFeedback(replace, { errorDisplay: "inline" });
  const [line, setLine] = useState(agent.script_opening_line);
  const { over } = roomLabel(line, room);
  const empty = spokenLength(line) === 0;
  const busy = replace.isPending || retrying;
  // One press does two things (save the line, then switch the notice on again); the button is
  // busy across both, and the switch's own outcome is drawn by the panel that owns it.
  const status: FeedbackStatus = busy ? "pending" : replaceFeedback.status === "error" ? "error" : "idle";
  const counterId = `opening-fix-room-${agent.id}`;

  return (
    <div className="mt-4 space-y-3">
      <ProblemNotice error={replace.error ?? error} />
      <div>
        <label className={FIELD_LABEL} htmlFor={`opening-fix-${agent.id}`}>
          Opening line
        </label>
        <textarea
          id={`opening-fix-${agent.id}`}
          className={FIELD}
          rows={3}
          value={line}
          aria-invalid={over}
          aria-describedby={counterId}
          onChange={(event) => setLine(event.target.value)}
        />
        <RoomCounter id={counterId} text={line} room={room} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          variant="primary-sm"
          status={status}
          pendingLabel="Saving…"
          disabled={over || empty}
          onClick={() => replace.mutate(line, { onSuccess: () => retry() })}
        >
          Save and switch on
        </ActionButton>
        <AskAssistant
          prompt={`Shorten the opening line of ${agent.name} to at most ${room} characters, in the same language, keeping what it says.`}
          label={`Ask ${ASSISTANT_NAME} to shorten it`}
        />
      </div>
      <p className="text-xs text-ink-muted">
        Goes live at once. The rest of the script stays.
      </p>
    </div>
  );
}
