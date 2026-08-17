"use client";

/**
 * Warn before an unattended console signs itself out (D-174, §5.6).
 *
 * ## Why the browser has to own this at all, when the server already enforces an idle bound
 *
 * `apps/api/authn/sessions.py` gives the admin realm a 30-minute idle timeout and slides
 * `last_seen_at` on every verified request (`IDLE_WRITE_FLOOR`). The console polls — the
 * dashboard every twenty seconds, and `client.ts` calls a tab left open "the normal case,
 * not an edge". **So the server's idle bound essentially never fires while a tab is
 * open**: the polling keeps sliding it. An operator who walks away from an unlocked laptop
 * has a live admin session for as long as the tab lives, which is precisely the risk the
 * 30 minutes was chosen against.
 *
 * This hook is what makes the server's number mean what it says. It measures HUMAN
 * activity rather than HTTP activity, and its bound is the same 30 minutes — 25 to the
 * warning, 5 more to the sign-out — so the console ends a session at the moment the server
 * would have if nothing had been polling on the absent operator's behalf.
 *
 * ## Two timers, cleared every way out
 *
 * The reference's version is one of the few pieces §5.7 does NOT fault, and its shape is
 * kept: a `clearTimers` that both the reschedule and the unmount go through. The activity
 * listeners are `passive`, because `scroll` and `wheel` handlers that are not are a
 * measurable scroll-jank source on the low-end Android this console is used on, and this
 * one never calls `preventDefault`.
 *
 * ## Once the warning is up, activity is IGNORED — and that is the fix, not a shortcut
 *
 * The first spelling of this hook called `onActive()` on any activity while the warning
 * was showing, which dismissed the modal and restarted the clock. It is wrong twice.
 *
 * The functional half: the modal is a focus-trapped `alertdialog` whose only exits are its
 * two buttons, and `mousemove`/`click` are in `ACTIVITY_EVENTS`. So moving the pointer
 * towards "Stay signed in" dismissed the dialog before it could be pressed, and PRESSING it
 * dismissed the dialog on the click that started the extension — hiding the outcome,
 * including a failure the operator needed to see. `tests/authnGuards.test.tsx`'s "does NOT
 * sign out when the extension request simply failed" is the case that caught it: the
 * warning it asserts on had already been dismissed by its own button press.
 *
 * The security half is the one that would have survived a cosmetic fix: extending a session
 * is a decision, and a stray mouse movement over a laptop somebody walked away from is not
 * one. This is the standard shape — react-idle-timer's `promptBeforeIdle` stops resetting
 * on activity once the prompt is open, and CMS's design system says the same
 * (design.cms.gov/components/idle-timeout) — for exactly this reason.
 *
 * So the warning is sticky: activity below it does nothing, and `resume()` — returned to
 * the caller and called only after an EXPLICIT extension the server agreed to — is what
 * restarts the clock.
 */

import { useCallback, useEffect, useRef } from "react";

/**
 * The events that count as a person being present.
 *
 * `mousemove` and `scroll` are the ones that matter for the false-positive direction —
 * without them, reading a long call transcript without touching the keyboard reads as
 * idleness and the modal interrupts somebody who is working. `visibilitychange` is
 * deliberately NOT here: a tab coming back to the foreground is not evidence that the
 * person who left it is the person who returned.
 */
const ACTIVITY_EVENTS = [
  "mousedown",
  "mousemove",
  "keydown",
  "touchstart",
  "wheel",
  "scroll",
  "click",
] as const;

export interface IdleTimeoutOptions {
  /** Idle time before the warning shows. */
  warningAfterMs: number;
  /** Further idle time after the warning before the session is ended. */
  logoutAfterWarningMs: number;
  onWarning: () => void;
  onLogout: () => void;
  /** Off when there is no session to protect — no listeners, no timers. */
  enabled: boolean;
}

export interface IdleTimeoutControls {
  /**
   * Dismiss the warning and start the idle clock again, from now.
   *
   * The ONLY way out of the warning short of the logout timer. Call it after an extension
   * the SERVER agreed to — see `adminIdleTimeoutModal.tsx`, which calls it on the branch
   * where the refreshed `SessionOut` is still a complete admin session and on no other.
   * Calling it on a failed extension would hand back the five minutes the failure did not
   * buy.
   */
  resume: () => void;
}

export function useIdleTimeout({
  warningAfterMs,
  logoutAfterWarningMs,
  onWarning,
  onLogout,
  enabled,
}: IdleTimeoutOptions): IdleTimeoutControls {
  // Callbacks through refs so a caller re-creating them every render does not tear down
  // and rebuild the timers on every render — which would mean the idle clock restarted
  // continuously and the warning never fired at all.
  const handlers = useRef({ onWarning, onLogout });
  handlers.current = { onWarning, onLogout };

  const warningShown = useRef(false);
  const timers = useRef<{ warning?: ReturnType<typeof setTimeout>; logout?: ReturnType<typeof setTimeout> }>({});
  /**
   * The live `schedule`, so `resume` can reach it.
   *
   * `schedule` closes over the effect's timings, and `resume` is returned to a caller that
   * holds it across renders; a ref is what lets the second call the first without either
   * of them becoming a dependency of the other. `undefined` while disabled, which is what
   * makes `resume` a no-op there rather than a way to start timers on a signed-out page.
   */
  const scheduleRef = useRef<(() => void) | undefined>(undefined);

  const clearTimers = useCallback(() => {
    clearTimeout(timers.current.warning);
    clearTimeout(timers.current.logout);
    timers.current = {};
  }, []);

  const resume = useCallback(() => {
    warningShown.current = false;
    scheduleRef.current?.();
  }, []);

  useEffect(() => {
    if (!enabled) {
      clearTimers();
      warningShown.current = false;
      scheduleRef.current = undefined;
      return;
    }

    const schedule = (): void => {
      clearTimers();
      timers.current.warning = setTimeout(() => {
        warningShown.current = true;
        handlers.current.onWarning();
        timers.current.logout = setTimeout(() => {
          warningShown.current = false;
          handlers.current.onLogout();
        }, logoutAfterWarningMs);
      }, warningAfterMs);
    };
    scheduleRef.current = schedule;

    const onActivity = (): void => {
      // Sticky warning: see the file docstring. Once the prompt is up, nothing below it
      // counts — not the pointer crossing it, and not the click on its own button. Only
      // `resume()` reopens the clock, and only the logout timer closes it the other way.
      if (warningShown.current) return;
      schedule();
    };

    schedule();
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, onActivity, { passive: true });
    }
    return () => {
      for (const event of ACTIVITY_EVENTS) window.removeEventListener(event, onActivity);
      clearTimers();
      scheduleRef.current = undefined;
    };
  }, [enabled, warningAfterMs, logoutAfterWarningMs, clearTimers]);

  return { resume };
}
