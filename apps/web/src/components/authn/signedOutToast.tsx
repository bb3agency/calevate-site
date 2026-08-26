"use client";

/**
 * "Your session ended" — said once, at the door, and only when it is true.
 *
 * ## Why this is a toast and not the screen
 *
 * The gate used to render a full red panel on the console URL and stop there. That is a
 * dead end: the only thing anybody can do from it is click through to sign in, so the
 * click is ceremony. `SessionGate` now sends people straight to the door, which leaves
 * one thing worth saying — WHY they are looking at a sign-in form they did not ask for —
 * and that is a passing remark, not a screen.
 *
 * ## Only when a session actually ended
 *
 * `takeSignedOut` answers false for a browser that never held a session in this realm, so
 * a first-time visitor who typed a console URL sees the sign-in page and nothing else.
 * They are not "signed out"; they are simply not signed in, and announcing an event that
 * did not happen is worse than silence.
 *
 * ## Announced, then allowed to leave
 *
 * `role="status"` + `aria-live="polite"` announces it once without stealing focus — this
 * is information, and a person's next action is to type a password. Deliberately NOT a
 * `role="alert"` or a focus trap: interrupting the form to say something the form is
 * already the answer to is the pattern this replaces.
 *
 * It auto-dismisses, and it is also dismissible by hand, because an auto-dismissing
 * message a person is still reading is its own small failure. `prefers-reduced-motion` is
 * honoured by having no entrance animation at all rather than a shorter one.
 */

import { useEffect, useState } from "react";

import { ShieldAlert, X } from "lucide-react";

import { takeSignedOut } from "@/lib/authn/signedOutNotice";

/** Long enough to read two short lines without hurrying, short enough not to linger. */
export const SIGNED_OUT_TOAST_MS = 6000;

export interface SignedOutToastProps {
  /** The realm whose mark to consume — `"admin"` or `"client"`. */
  realm: string;
  /** Names the session in the copy, so the sentence is about the right door. */
  realmLabel: string;
}

export function SignedOutToast({ realm, realmLabel }: SignedOutToastProps) {
  /**
   * `null` until the effect has run, and that is not the same as `false`.
   *
   * `takeSignedOut` reads `sessionStorage`, which does not exist during the server render
   * — reading it in the initial state would hydrate a different tree than the server sent.
   * Starting at `null` means the first paint matches the server (nothing) and the notice
   * appears on the client pass.
   */
  const [visible, setVisible] = useState<boolean | null>(null);

  useEffect(() => {
    // Consumed on mount, so the mark cannot survive to a later visit. `takeSignedOut`
    // clears as it reads; this component never has to remember to.
    setVisible(takeSignedOut(realm));
  }, [realm]);

  useEffect(() => {
    if (visible !== true) return;
    const timer = window.setTimeout(
      () => setVisible(false),
      SIGNED_OUT_TOAST_MS,
    );
    return () => window.clearTimeout(timer);
  }, [visible]);

  if (visible !== true) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="signed-out-toast"
      className="mb-4 flex items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 shadow-sm"
    >
      <ShieldAlert
        aria-hidden
        className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted"
      />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium text-ink">Your {realmLabel} session ended</p>
        <p className="mt-0.5 text-ink-muted">
          Sessions end after a period of inactivity, or when you sign out
          everywhere. Sign in again to pick up where you left off.
        </p>
      </div>
      <button
        type="button"
        onClick={() => setVisible(false)}
        aria-label="Dismiss"
        className="-m-1 rounded-lg p-1 text-ink-faint hover:bg-app hover:text-ink"
      >
        <X aria-hidden className="h-4 w-4" />
      </button>
    </div>
  );
}
