"use client";

/**
 * The code prompt that clears a step-up refusal, without leaving the screen (D-210).
 *
 * `core/stepup.py` demands a second factor proved in the last five minutes before a
 * dangerous admin action, and `authn/stepup.py::reauthentication_required` prints the two
 * endpoints that clear it — because "an operator mid-incident must not have to find the
 * source to learn how to get past this". They should not have to find the source OR a
 * curl either, which is what this panel is: the refusal's own remediation, as two buttons.
 *
 * ## Why it is mounted once in the shell rather than per screen
 *
 * The refusal can arrive from anywhere, including from `lib/api/admin.ts::mint`, which
 * runs inside the transport while assembling headers and has no component in scope.
 * `lib/authn/stepUpPrompt.ts` is the external store that lets any of them ask; this is the
 * one subscriber. A per-screen prompt would mean the sixteen gated routes each need their
 * own, and the one nobody wrote would be the one an operator hits at 3am.
 *
 * ## What it deliberately does NOT do
 *
 * It does not retry anything. Proving the factor resolves the ask and the ORIGINAL caller
 * decides what to do next — because only that caller knows whether its request is safe to
 * repeat. `admin.ts::mint` repeats because its route refuses before it writes anything and
 * a test pins that; a caller without that proof must not have a retry imposed on it from
 * here (`lib/api/client.ts` records the same rule for its own deleted retry rung).
 *
 * It also does not read `mfa_complete` and decide anything from it. The server's answer to
 * `/step-up/verify` is the authority: a 2xx means `mfa_verified_at` was restamped, and
 * anything else is a refusal this panel renders rather than interprets.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { KeyRound, Mail, ShieldCheck, X } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import { confirmAdminStepUp, requestAdminStepUp } from "@/lib/authn/adminAuthn";
import { useCountdown } from "@/lib/authn/useCountdown";
import {
  completeStepUpPrompt,
  dismissStepUpPrompt,
  readStepUpPrompt,
  subscribeToStepUpPrompt,
} from "@/lib/authn/stepUpPrompt";
import { useFocusTrap } from "@/lib/focusTrap";

/**
 * The same sixty seconds `SignInForm` waits between codes, and the same reason it gives:
 * this is a courtesy that stops an operator hammering a button, NOT the real limit. The
 * real one is `throttle.OTP_BUDGET` server-side, and a client-side cooldown dressed up as
 * the real limit would invite somebody to relax it.
 */
const RESEND_COOLDOWN_MS = 60_000;

export function StepUpPrompt() {
  const prompt = useSyncExternalStore(subscribeToStepUpPrompt, readStepUpPrompt, readStepUpPrompt);
  const panel = useRef<HTMLDivElement>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [sending, setSending] = useState(false);
  const [checking, setChecking] = useState(false);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [resendReadyAt, setResendReadyAt] = useState<number | null>(null);
  const cooldown = useCountdown(resendReadyAt);

  const reset = useCallback(() => {
    setCode("");
    setError(null);
    setSentAt(null);
    setResendReadyAt(null);
  }, []);

  const close = useCallback(() => {
    reset();
    dismissStepUpPrompt();
  }, [reset]);

  const send = useCallback(() => {
    if (sending || cooldown > 0) return;
    setSending(true);
    setError(null);
    void requestAdminStepUp()
      .then(() => {
        setSentAt(Date.now());
        setResendReadyAt(Date.now() + RESEND_COOLDOWN_MS);
      })
      .catch(setError)
      .finally(() => setSending(false));
  }, [cooldown, sending]);

  const submit = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      if (checking || code.trim().length === 0) return;
      setChecking(true);
      setError(null);
      void confirmAdminStepUp(code.trim())
        .then(() => {
          // Reset BEFORE completing: the ask resolves synchronously into callers that may
          // re-render this tree, and leaving a spent code in state would show it again the
          // next time the prompt opens.
          reset();
          completeStepUpPrompt();
        })
        // NOT a dismissal. A wrong code, a 429 and a dropped connection all leave the
        // prompt open with a sentence — closing on a typo would fail the caller's action
        // for a keystroke, which is `problems.ts`'s §5.3 argument applied to this screen.
        .catch(setError)
        .finally(() => setChecking(false));
    },
    [checking, code, reset],
  );

  // THE ONLY SUBSCRIBER LEAVING MEANS NOBODY CAN ANSWER. The shell unmounts on sign-out
  // and when the session gate stops rendering its children, and an ask left pending then
  // is a caller waiting on a prompt that no longer exists anywhere. Settling it `false`
  // makes that a refusal the caller reports rather than a promise nothing will resolve.
  // Empty deps so this runs on unmount ONLY, never on a re-render.
  useEffect(() => dismissStepUpPrompt, []);

  // Escape DOES dismiss here, unlike the idle-timeout modal. That one hides a running
  // countdown, so closing it silently is a deadline nobody can see; this one blocks
  // exactly one action the operator asked for, and refusing to let them out of it would
  // trap them on a screen whose only other exit is a sign-out.
  useFocusTrap(panel, prompt !== null, close, "first-tabbable");

  if (prompt === null) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={panel}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="step-up-title"
        aria-describedby="step-up-body"
        tabIndex={-1}
        className="w-full max-w-md rounded-card border border-line bg-surface p-4 shadow-lg outline-none sm:p-6"
      >
        <div className="flex items-start justify-between gap-3">
          <h2
            id="step-up-title"
            className="flex items-center gap-2 text-[17px] font-semibold text-ink"
          >
            <ShieldCheck aria-hidden className="h-4 w-4" />
            Confirm it is still you
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close without confirming"
            className="rounded-md p-1 text-ink-faint hover:bg-surface-muted hover:text-ink"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>

        <div id="step-up-body" className="mt-3 space-y-3 text-sm text-ink-muted">
          <p>
            {/* The server's own words for what is waiting, not a sentence invented here —
                the caller knows which action it is and this panel does not. */}
            {prompt.reason} This needs a second factor proved in the last five minutes.
          </p>

          <form className="space-y-3" onSubmit={submit} noValidate>
            {sentAt === null ? (
              <button
                type="button"
                className={PRIMARY_BUTTON}
                disabled={sending}
                onClick={send}
              >
                <Mail aria-hidden className="h-4 w-4" />
                {sending ? "Sending…" : "Email me a code"}
              </button>
            ) : (
              <>
                {/* The address is not printed back, for the reason `SignInForm` gives:
                    a shoulder-surfed screen should not carry an operator's address. */}
                <p>We have sent a six-digit code to the address on file for this account.</p>
                <AuthField
                  label="Six-digit code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={16}
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                />
                <div className="flex flex-wrap gap-2">
                  <button
                    type="submit"
                    className={PRIMARY_BUTTON}
                    disabled={checking || code.trim().length === 0}
                  >
                    <KeyRound aria-hidden className="h-4 w-4" />
                    {checking ? "Checking…" : "Confirm"}
                  </button>
                  <button
                    type="button"
                    className={SECONDARY_BUTTON}
                    disabled={sending || cooldown > 0}
                    onClick={send}
                  >
                    {cooldown > 0 ? `Send a new code in ${cooldown}s` : "Send a new code"}
                  </button>
                </div>
              </>
            )}

            <AuthProblemNotice error={error} />
          </form>
        </div>
      </div>
    </div>
  );
}
