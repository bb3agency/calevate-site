"use client";

import { useId, useState } from "react";
import type { UseMutationResult } from "@tanstack/react-query";
import { Pencil } from "lucide-react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD } from "@/components/ui";
import { Why } from "@/components/why";
import type { Agent } from "@/lib/api/agents";
import { ApiProblem } from "@/lib/api/client";
import { useReplaceOpeningLine } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";

import { RoomCounter, roomLabel, spokenLength } from "../panels/openingLineFix";

/** The server's refusal as one short line, and its full sentence behind a tap. */
export function refusalLine(error: unknown): { line: string; detail: string | null } {
  if (error instanceof ApiProblem) {
    const detail = [error.message, error.remediation].filter(Boolean).join(" ");
    return { line: error.title ?? error.message, detail: error.title ? detail : (error.remediation ?? null) };
  }
  return { line: "Couldn't save it. Try again.", detail: null };
}

/**
 * ONE SPOKEN LINE, EDITABLE IN PLACE (D-918): the line quoted, an Edit button, then the box
 * with its count against the server's room, Save and Cancel, and the server's refusal in one
 * short line with the rest behind a tap.
 *
 * Generic over what it saves (`save`, a mutation taking the new text, with its caller's
 * `useActionFeedback` status), so each line an agent
 * speaks first gets the same editor: the opening line today, and the line an agent that both
 * answers and calls says when it calls, once that has a route. The count comes from `room`,
 * the server's own measure; with none, the box just counts characters.
 */
export function LineEditor({
  caption,
  fieldLabel,
  value,
  lang,
  room,
  save,
  status,
  why,
  editable = true,
  empty = "No line yet.",
}: {
  /** Above the quoted line ("It opens every call with"). */
  caption: string;
  /** The text box's label ("Opening line"). */
  fieldLabel: string;
  value: string;
  lang: string;
  room: number | null;
  save: UseMutationResult<unknown, Error, string>;
  /** The save's feedback status, from the caller's `useActionFeedback(save)`. */
  status: FeedbackStatus;
  /** One sentence behind "Why?" under the box. */
  why?: string;
  /** False where another Edit button for the same line is on screen. */
  editable?: boolean;
  empty?: string;
}) {
  const boxId = useId();
  const counterId = useId();
  const current = value.trim();
  const [draft, setDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (draft === null) {
    return (
      <figure className="min-w-0">
        <figcaption className="text-meta text-ink-muted">{caption}</figcaption>
        {current ? (
          <blockquote lang={lang} className="mt-1 break-words text-body text-ink">
            “{current}”
          </blockquote>
        ) : (
          <p className="mt-1 text-meta text-ink-faint">{empty}</p>
        )}
        {editable ? (
          <button
            type="button"
            className={`${TEXT_ACTION} mt-1`}
            onClick={() => {
              save.reset();
              setSaved(false);
              setDraft(current);
            }}
          >
            <Pencil aria-hidden className="h-3.5 w-3.5" />
            {current ? "Edit" : "Write one"}
          </button>
        ) : null}
        {saved ? (
          <span role="status" className="ml-3 text-meta text-ink-muted">
            Saved
          </span>
        ) : null}
      </figure>
    );
  }

  const over = room !== null && roomLabel(draft, room).over;
  const blank = spokenLength(draft) === 0;
  const unchanged = draft.trim() === current;
  const refusal = save.error ? refusalLine(save.error) : null;
  const submit = () => {
    if (over || blank || unchanged || save.isPending) return;
    save.mutate(draft.trim(), {
      onSuccess: () => {
        setDraft(null);
        setSaved(true);
      },
    });
  };

  return (
    <div className="min-w-0 space-y-2">
      <label htmlFor={boxId} className="text-meta font-medium text-ink">
        {fieldLabel}
      </label>
      <textarea
        id={boxId}
        lang={lang}
        rows={3}
        value={draft}
        aria-invalid={over || refusal !== null}
        aria-describedby={counterId}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setDraft(null);
        }}
        className={`${FIELD} w-full resize-y text-[16px] leading-relaxed`}
      />
      {room !== null ? (
        <RoomCounter id={counterId} text={draft} room={room} />
      ) : (
        <p id={counterId} className="text-xs tabular-nums text-ink-muted">
          {spokenLength(draft)} characters
        </p>
      )}
      {refusal ? (
        <div role="alert" className="text-meta text-ink">
          <p>{refusal.line}</p>
          {refusal.detail ? <Why label="Details">{refusal.detail}</Why> : null}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          variant="primary-sm"
          status={status}
          pendingLabel="Saving…"
          successLabel="Saved"
          disabled={over || blank || unchanged}
          onClick={submit}
        >
          Save
        </ActionButton>
        <button type="button" className={TEXT_ACTION} onClick={() => setDraft(null)}>
          Cancel
        </button>
      </div>
      {why ? <Why>{why}</Why> : null}
    </div>
  );
}

/**
 * THE OPENING LINE (D-918): what the agent says first on every call.
 *
 * Saved through the agent's own route (`PUT /v1/agents/{id}/script/opening-line`,
 * `script_builder.replace_opening_line`), so the Script page's rules hold here: the calling
 * system's ceiling with the notices on (D-846), and a refusal while other script changes
 * wait or the script is written as one piece. A live agent is put live again by that route;
 * a draft is ready at its next call. The count is against `greeting_budget.opening_room`.
 * The AI and recording notices are separate sentences (D-163, D-864); this never changes them.
 */
export function OpeningLine({
  agent,
  lang,
  label = "It opens every call with",
  editable = true,
}: {
  agent: Agent;
  lang: string;
  label?: string;
  editable?: boolean;
}) {
  const session = useClientSession();
  const replace = useReplaceOpeningLine(session, agent.id);
  // The refusal is drawn under the box, so no toast repeats it.
  const feedback = useActionFeedback(replace, { errorDisplay: "inline" });
  return (
    <LineEditor
      caption={label}
      fieldLabel="Opening line"
      value={agent.script_opening_line}
      lang={lang}
      room={agent.greeting_budget?.opening_room ?? null}
      save={replace}
      status={feedback.status}
      editable={editable}
      empty="No opening line yet."
      why="Callers hear this first. Your AI and recording notices are separate and stay as set."
    />
  );
}
