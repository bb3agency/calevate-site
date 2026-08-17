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
  /** The person came back while the warning was up. */
  onActive: () => void;
  onLogout: () => void;
  /** Off when there is no session to protect — no listeners, no timers. */
  enabled: boolean;
}

export function useIdleTimeout({
  warningAfterMs,
  logoutAfterWarningMs,
  onWarning,
  onActive,
  onLogout,
  enabled,
}: IdleTimeoutOptions): void {
  // Callbacks through refs so a caller re-creating them every render does not tear down
  // and rebuild the timers on every render — which would mean the idle clock restarted
  // continuously and the warning never fired at all.
  const handlers = useRef({ onWarning, onActive, onLogout });
  handlers.current = { onWarning, onActive, onLogout };

  const warningShown = useRef(false);
  const timers = useRef<{ warning?: ReturnType<typeof setTimeout>; logout?: ReturnType<typeof setTimeout> }>({});

  const clearTimers = useCallback(() => {
    clearTimeout(timers.current.warning);
    clearTimeout(timers.current.logout);
    timers.current = {};
  }, []);

  useEffect(() => {
    if (!enabled) {
      clearTimers();
      warningShown.current = false;
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

    const onActivity = (): void => {
      // While the warning is up, activity DISMISSES it and restarts the clock. Not
      // extending the session — that is a deliberate button press, because a session
      // extension is a security decision and a stray mouse movement is not one.
      if (warningShown.current) {
        warningShown.current = false;
        handlers.current.onActive();
      }
      schedule();
    };

    schedule();
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, onActivity, { passive: true });
    }
    return () => {
      for (const event of ACTIVITY_EVENTS) window.removeEventListener(event, onActivity);
      clearTimers();
    };
  }, [enabled, warningAfterMs, logoutAfterWarningMs, clearTimers]);
}
