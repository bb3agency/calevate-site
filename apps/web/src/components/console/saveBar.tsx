"use client";

import type { ReactNode } from "react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { ProblemNotice } from "@/components/ui";

/**
 * THE SAVE FOR A CHOICE THAT IS ALWAYS ON SCREEN (a voice, a model, what an agent is): it
 * appears only once the choice differs from what is saved, with Cancel beside it, and sticks
 * to the bottom of the window so a long list of options never pushes it out of reach.
 *
 * One bar for every such setting on the agent page and the account's model screen, so a
 * person learns one way to change a thing. A choice that saves the moment it is flipped (a
 * switch) needs no bar; a value edited behind "Change" uses the row's own inline form.
 *
 * Render it inside the `<form>` it submits. The negative bottom offset cancels the shell's
 * bottom padding (`SHELL_MAIN_CLASS`), so the bar sits on the window's edge. On a phone the
 * two buttons take the full width.
 *
 * Pass the caller's `useActionFeedback(...).status` as `status`. A failure keeps the bar (the
 * choice still differs) and shows the button's error face. A success unmounts the bar before
 * its tick could be seen, so the caller's feedback carries a `successToast`.
 */
export function SaveBar({
  label,
  saving = false,
  status,
  onCancel,
  note,
  disabled = false,
  title,
  waitingFor = null,
  error = null,
}: {
  /** The consequence, as the button says it ("Use this voice", "Save model"). */
  label: string;
  /** Read only when `status` is not given: `true` is the pending face. */
  saving?: boolean;
  status?: FeedbackStatus;
  onCancel: () => void;
  /** One line on when the change takes effect. */
  note?: ReactNode;
  disabled?: boolean;
  title?: string;
  /** Another save it shares a write with is running: held, with this reason. */
  waitingFor?: ReactNode;
  /** Why the last save was refused: said in the bar, beside the button that was pressed,
   *  not at the top of a form scrolled out of view. */
  error?: unknown;
}) {
  const shown: FeedbackStatus = status ?? (saving ? "pending" : "idle");
  const busy = shown === "pending";
  return (
    <div className="settings-enter sticky -bottom-4 z-sticky -mx-1 flex flex-wrap items-center gap-3 border-t border-line bg-surface px-1 py-3 lg:-bottom-8">
      <div className="flex w-full gap-2 sm:w-auto">
        <ActionButton
          type="submit"
          variant="primary-sm"
          status={shown}
          pendingLabel="Saving…"
          successLabel="Saved"
          disabled={disabled}
          title={title}
          waitingFor={waitingFor}
          className="flex-1 sm:flex-none"
        >
          {label}
        </ActionButton>
        <ActionButton
          variant="secondary-sm"
          disabled={busy}
          onClick={onCancel}
          className="flex-1 sm:flex-none"
        >
          Cancel
        </ActionButton>
      </div>
      {note ? <span className="text-meta text-ink-muted">{note}</span> : null}
      {error != null ? (
        <div className="w-full">
          <ProblemNotice error={error} />
        </div>
      ) : null}
    </div>
  );
}
