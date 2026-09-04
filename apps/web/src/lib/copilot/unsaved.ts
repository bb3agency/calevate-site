/**
 * WOULD LEAVING THIS SCREEN THROW SOMEBODY'S WORK AWAY? — the half of D-524 the server
 * cannot answer.
 *
 * The assistant can now open another screen. The request already tells the server which
 * FIELDS a screen has, so the server knows a form exists; it has no way to know whether
 * anybody has typed in it. This browser does. So the seam is split honestly: the server
 * decides the DESTINATION and this decides whether to ASK FIRST.
 *
 * ## The rule, and why it is not `beforeunload` and not a `confirm()`
 *
 * `beforeunload` fires for a full page load and not for a client-side route change, so it
 * cannot see this move at all. `window.confirm` blocks the whole tab, cannot be styled, cannot
 * be read by the same assistive path as the rest of the console, and would be the second way
 * this product asks somebody to confirm something. `ConfirmDialog` is the first, and this uses
 * it.
 *
 * ## What "dirty" means when nobody has said
 *
 * A screen may DECLARE the answer (`CopilotSurface.unsaved`) and that answer wins. Most do
 * not, and the conservative reading is the point of this module: **a screen with any writable
 * field is treated as possibly dirty**, and so is a screen that did not describe itself at all
 * (`fallback.ts`) — because "I cannot see this screen" is the one state where a confident "no
 * unsaved work" would be a guess.
 *
 * That is deliberately asymmetric, and the asymmetry is the design. Asking when there was
 * nothing to lose costs one click on a question the person just asked for. Not asking when
 * there was costs a half-typed campaign script and destroys something no tool of ours is
 * allowed to destroy without asking. The two errors are not the same size, so the tie does not
 * go to convenience.
 *
 * The consequence a reader should expect: the console's many READ-ONLY screens — the
 * dashboard, the logs, the statements, everything that declares `noFill` and no writable field
 * — navigate straight through, which is most of where "take me to X" is asked from. A screen
 * that wants to skip the question anyway declares `unsaved: false` and means it.
 */

import type { CopilotSurface } from "./types";

/** Whether to ask before leaving, and the sentence saying what is at stake. */
export interface UnsavedVerdict {
  ask: boolean;
  /**
   * What the person would lose, in their terms — rendered as the dialog's body. `""` when
   * `ask` is false: there is nothing to say and nothing to show it in.
   */
  reason: string;
}

const GO: UnsavedVerdict = { ask: false, reason: "" };

/**
 * Should the console ask before opening another screen?
 *
 * `filledCount` is how many fields the assistant itself has just written into this screen and
 * nobody has saved (`CopilotConversation.batch`). It is checked FIRST and it is the one case
 * where the answer is certain rather than cautious: those values are unsaved by construction,
 * and an assistant that filled a form and then navigated away from it would have undone its
 * own answer.
 */
export function unsavedWork(surface: CopilotSurface, filledCount: number): UnsavedVerdict {
  if (filledCount > 0) {
    return {
      ask: true,
      reason: `The assistant filled in ${filledCount} ${
        filledCount === 1 ? "field" : "fields"
      } on this screen that you haven't saved yet. Leaving will discard them.`,
    };
  }
  if (surface.unsaved === true) {
    return {
      ask: true,
      reason: "You have changes on this screen that haven't been saved. Leaving will discard them.",
    };
  }
  // A screen that says `false` has answered the question and is believed — that is the whole
  // point of letting a screen declare it. Checked before the two guesses below, so a declared
  // clean screen is never asked about because it happens to have an editable field on it.
  if (surface.unsaved === false) return GO;
  if (surface.undeclared === true) {
    return {
      ask: true,
      reason:
        "This screen hasn't told the assistant what it holds, so anything you've typed here can't be ruled out. Leaving will discard unsaved changes.",
    };
  }
  if (surface.fields.some((field) => field.writable !== false)) {
    return {
      ask: true,
      reason:
        "This screen has a form on it. Anything typed in that hasn't been saved will be lost.",
    };
  }
  return GO;
}
