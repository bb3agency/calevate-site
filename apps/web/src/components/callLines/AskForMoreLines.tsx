"use client";

/**
 * "Need more? Ask us." — the client's way to ask for more calls at once.
 *
 * The number is Calevate's to set (a commercial decision), so this is a request, not a
 * control: a button that opens a short form, then the request's state in place of the
 * button. One request is open at a time on the server, so the button is gone while one
 * waits and a double tap cannot ask twice.
 *
 * Shared by the Phone numbers tile and the campaign wizard: both read `GET /v1/call-lines`
 * through `useMyCallLines`, so sending here updates the other at once.
 */

import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { NumberField } from "@/components/arc/number-field";
import { TEXT_ACTION } from "@/components/console/section";
import { ModalDialog } from "@/components/modalDialog";
import { FIELD, ProblemNotice, SECONDARY_BUTTON, formatISTDay } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { callsAtOnce, useAskForMoreLines, useMyCallLines, type MyCallLines } from "@/lib/api/callLines";
import { useWriteAccess } from "@/lib/api/hooks";

/** The longest note the server keeps (`CALL_LINE_REQUEST_TEXT_MAX`). */
const NOTE_MAX = 280;

export function AskForMoreLines({ session }: { session: Session }) {
  const lines = useMyCallLines(session);
  const write = useWriteAccess(session, "org:manage", "ask for more calls at once");
  const [open, setOpen] = useState(false);
  const reasonId = useId();
  const data = lines.data;

  // Before the account's lines are known there is nothing to ask against; the sentence
  // stays, without a button that could only guess.
  if (!data) return <span>Need more? Ask us.</span>;
  if (data.on_trial) return <span>Trial: one line. More once you pay.</span>;

  const request = data.request;
  if (request?.status === "open") {
    const day = formatISTDay(request.created_at);
    const asked = request.wanted_lines != null ? `Asked for ${request.wanted_lines}` : "Asked for more";
    return (
      <span role="status">
        {asked}
        {day ? ` on ${day}` : ""}. We&apos;ll let you know.
      </span>
    );
  }

  const atMost = data.call_lines >= data.max_lines;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1">
      {request?.status === "declined" && (
        <span>We could not add more{request.decline_reason ? `: ${request.decline_reason}` : "."}</span>
      )}
      {request?.status === "done" && request.lines_granted != null && (
        <span>Raised to {request.lines_granted}.</span>
      )}
      {atMost ? (
        <span>That is the most an account can have.</span>
      ) : (
        <>
          <button
            type="button"
            className={TEXT_ACTION}
            disabled={!write.allowed}
            aria-describedby={write.allowed ? undefined : reasonId}
            aria-haspopup="dialog"
            onClick={() => setOpen(true)}
          >
            {request ? "Ask for more" : "Need more? Ask us."}
          </button>
          {!write.allowed && write.reason && (
            <span id={reasonId} className="text-meta text-ink-muted">
              {write.reason}
            </span>
          )}
        </>
      )}
      {open && <AskDialog session={session} data={data} onClose={() => setOpen(false)} />}
    </span>
  );
}

function AskDialog({ session, data, onClose }: { session: Session; data: MyCallLines; onClose: () => void }) {
  const ask = useAskForMoreLines(session);
  const feedback = useActionFeedback(ask, {
    errorDisplay: "inline",
    successToast: "Sent. We'll let you know.",
  });
  const [wanted, setWanted] = useState<number | null>(Math.min(data.call_lines + 1, data.max_lines));
  const [note, setNote] = useState("");
  const pending = ask.isPending;

  return (
    <ModalDialog
      title="Ask for more calls at once"
      description={`You have ${callsAtOnce(data.call_lines)}. We reply on your bell.`}
      initialFocus="container"
      onClose={() => {
        if (!pending) onClose();
      }}
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={pending}>
            Cancel
          </button>
          <ActionButton
            status={feedback.status}
            pendingLabel="Sending…"
            successLabel="Sent"
            onClick={() => {
              if (pending) return;
              const trimmed = note.trim();
              ask.mutate({ wanted, note: trimmed === "" ? null : trimmed }, { onSuccess: onClose });
            }}
          >
            Send
          </ActionButton>
        </>
      }
    >
      <div className="mt-4 space-y-4">
        <NumberField
          label="How many at once"
          hint={`${data.call_lines + 1} to ${data.max_lines}.`}
          value={wanted}
          onChange={setWanted}
          min={data.call_lines + 1}
          max={data.max_lines}
          unit="calls"
          disabled={pending}
        />
        <Field label="Anything we should know?" hint="Optional.">
          {(control) => (
            <textarea
              {...control}
              className={FIELD}
              rows={3}
              maxLength={NOTE_MAX}
              value={note}
              disabled={pending}
              onChange={(event) => setNote(event.target.value)}
            />
          )}
        </Field>
        {ask.error != null && <ProblemNotice error={ask.error} />}
      </div>
    </ModalDialog>
  );
}
