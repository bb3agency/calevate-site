"use client";

import { useRef, type ReactNode } from "react";

import { DANGER_BUTTON, ProblemNotice, SECONDARY_BUTTON } from "./ui";
import { useFocusTrap } from "@/lib/focusTrap";

/**
 * "Are you sure?" for the actions a client cannot take back — ONE dialog, not one per
 * screen.
 *
 * Three controls in the client console fired an irreversible or high-consequence mutation
 * on a single unconfirmed click: turning off an integration endpoint (a `DELETE` with no
 * re-activate route, so the client's live CRM feed stops and re-adding mints a NEW signing
 * secret), removing a colleague's access, and un-suppressing a number on the do-not-call
 * list (which puts a real person back in the dial pool under TCCCPR). Each is the case
 * NN/g reserves a confirmation dialog for — "irreversible actions", with the copy
 * describing the CONSEQUENCE rather than restating the command
 * (https://www.nngroup.com/articles/confirmation-dialog/, read 25 Aug 2026) — and GOV.UK's
 * Button guidance is more specific still: where an action "cannot easily be undone or
 * might have serious consequences", the final confirmation is a warning button
 * (https://design-system.service.gov.uk/components/button/, read 25 Aug 2026).
 *
 * ## Why a shared component rather than three dialogs
 *
 * CLAUDE.md: one way per problem. `aiExtraDialog.tsx` is this repo's accessible-dialog
 * reference — `role="dialog"` + `aria-modal` + `aria-labelledby`/`aria-describedby` and
 * the full APG focus contract through `useFocusTrap` — and it is deliberately NOT
 * generalised, because it is the one thing in the console that debits a wallet and there
 * may only be one statement about what a client's money buys. This is its sibling for the
 * OTHER shape: a consequence, a refusal slot, and two buttons. Three hand-rolled copies
 * would be three focus traps to get right and three places for the safe answer to drift
 * into the wrong DOM position.
 *
 * ## Two things that are decisions, not layout
 *
 * 1. **Cancel comes FIRST in DOM order**, so a keyboard reaches the safe answer with
 *    fewer keystrokes — the same argument `AcceptChargeDialog` makes for "Not now".
 * 2. **Focus lands on the CONTAINER**, not on a button. The container is labelled by its
 *    heading and described by its body, so a screen reader reads the consequence before
 *    it reads either choice; landing on "Cancel" would announce a button and say nothing
 *    about what it declines.
 *
 * The refusal renders INSIDE the panel, because that is where the decision is being made:
 * closing the dialog to show the error elsewhere leaves a person unsure whether the thing
 * happened.
 */
export function ConfirmDialog({
  title,
  confirmLabel,
  pendingLabel,
  cancelLabel = "Cancel",
  pending,
  error,
  onCancel,
  onConfirm,
  children,
}: {
  /** What is about to happen, naming the target. Becomes the dialog's accessible name. */
  title: string;
  /** The confirm button's label. Say the action, never "OK" — "OK" confirms nothing. */
  confirmLabel: string;
  /** The confirm button's label while the mutation is in flight. */
  pendingLabel: string;
  cancelLabel?: string;
  pending: boolean;
  error: unknown;
  onCancel: () => void;
  onConfirm: () => void;
  /** The consequence, in the client's own terms. Rendered as the dialog's description. */
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  // Always `true`: every caller renders this inside a `{confirming && …}`, so mounting IS
  // opening and unmounting is what hands focus back to the control that opened it.
  useFocusTrap(panel, true, onCancel, "container");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-body"
        tabIndex={-1}
        className="w-full max-w-md rounded-card border border-line bg-surface p-6 shadow-lg outline-none"
      >
        <h2 id="confirm-title" className="text-[17px] font-semibold text-ink">
          {title}
        </h2>

        <div id="confirm-body" className="mt-3 space-y-3 text-sm text-ink-muted">
          {children}
        </div>

        {error != null && (
          <div className="mt-3">
            <ProblemNotice error={error} />
          </div>
        )}

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button type="button" className={SECONDARY_BUTTON} onClick={onCancel} disabled={pending}>
            {cancelLabel}
          </button>
          <button type="button" className={DANGER_BUTTON} onClick={onConfirm} disabled={pending}>
            {pending ? pendingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
