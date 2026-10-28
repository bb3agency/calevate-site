"use client";

import { useId, useState } from "react";
import { Pencil } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
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
 * THE OPENING LINE, EDITABLE IN PLACE (D-918): what the agent says first on every call, with
 * an Edit button that opens the box.
 *
 * It saves through the agent's own route (`PUT /v1/agents/{id}/script/opening-line`,
 * `script_builder.replace_opening_line`), so the same rules hold here as on the Script page:
 * the calling system's ceiling with the notices switched on (D-846), and a refusal while
 * other script changes wait or the script is written as one piece. A live agent is put live
 * again by that route; a draft is ready at its next call. The count is against the room the
 * server measures (`greeting_budget.opening_room`), never a number of ours. The AI and
 * recording notices are separate sentences said before or after it (D-163, D-864); editing
 * the line never changes them.
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
  /** False where another Edit button for the same line is on screen. */
  editable?: boolean;
}) {
  const session = useClientSession();
  const replace = useReplaceOpeningLine(session, agent.id);
  const feedback = useActionFeedback(replace, { errorDisplay: "inline" });
  const boxId = useId();
  const counterId = useId();
  const current = agent.script_opening_line.trim();
  const [draft, setDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const room = agent.greeting_budget?.opening_room ?? null;

  if (draft === null) {
    return (
      <figure className="min-w-0">
        <figcaption className="text-meta text-ink-muted">{label}</figcaption>
        {current ? (
          <blockquote lang={lang} className="mt-1 break-words text-body text-ink">
            “{current}”
          </blockquote>
        ) : (
          <p className="mt-1 text-meta text-ink-faint">No opening line yet.</p>
        )}
        {editable ? (
        <button
          type="button"
          className={`${TEXT_ACTION} mt-1`}
          onClick={() => {
            replace.reset();
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
  const empty = spokenLength(draft) === 0;
  const unchanged = draft.trim() === current;
  const refusal = replace.error ? refusalLine(replace.error) : null;
  const save = () => {
    if (over || empty || unchanged || replace.isPending) return;
    replace.mutate(draft.trim(), {
      onSuccess: () => {
        setDraft(null);
        setSaved(true);
      },
    });
  };

  return (
    <div className="min-w-0 space-y-2">
      <label htmlFor={boxId} className="text-meta font-medium text-ink">
        Opening line
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
          status={feedback.status}
          pendingLabel="Saving…"
          successLabel="Saved"
          disabled={over || empty || unchanged}
          onClick={save}
        >
          Save
        </ActionButton>
        <button type="button" className={TEXT_ACTION} onClick={() => setDraft(null)}>
          Cancel
        </button>
      </div>
      <Why>Callers hear this first. Your AI and recording notices are separate and stay as set.</Why>
    </div>
  );
}
