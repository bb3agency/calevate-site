"use client";

/**
 * The code prompt that clears a step-up refusal, without leaving the screen (D-210).
 *
 * `core/stepup.py` demands a recently-proved second factor before a dangerous admin
 * action, and `authn/stepup.py::reauthentication_required` prints the two
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

import { KeyRound, LogOut, Mail, ShieldCheck } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import {
  ADMIN_SIGN_IN_PATH,
  adminAuthn,
  confirmAdminStepUp,
  requestAdminStepUp,
} from "@/lib/authn/adminAuthn";
import { markSignedOut } from "@/lib/authn/signedOutNotice";
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

/**
 * How long a proved factor lasts, in minutes — `authn/stepup.REAUTH_MAX_AGE`.
 *
 * A SECOND COPY OF A SERVER NUMBER, so it is pinned rather than trusted. This sentence
 * read "the last five minutes" as a hardcoded string while the constant it describes was
 * being changed to thirty; nothing would have caught that, and the operator would have
 * been told the wrong thing by the one screen whose whole job is explaining this control.
 * `tests/step_up_window_mirror_test.py` reads this literal out of this file and compares
 * it to the Python constant, so the two cannot drift again.
 */
export const REAUTH_WINDOW_MINUTES = 30;

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

  const [leaving, setLeaving] = useState(false);

  /**
   * THE ONLY WAY OUT OF THIS PANEL THAT IS NOT PROVING THE FACTOR (D-473).
   *
   * There used to be an `X`. It was argued for on the grounds that this prompt "blocks
   * exactly one action the operator asked for", so trapping them would be unkind — and
   * that reasoning was sound about the ACTION and wrong about the SCREEN. A close control
   * on a second-factor challenge reads as "not now", which is exactly the posture the
   * challenge exists to refuse: the person who cannot answer it is either the operator,
   * who can, or somebody at their unattended keyboard, who cannot and should not be left
   * with the console open. Founder's call, and it is the stricter of the two.
   *
   * `dismissStepUpPrompt()` still runs, FIRST and unconditionally. Every caller awaiting
   * `requireStepUp` must be settled `false` or it waits on a prompt that is being torn
   * down — and the sign-out network call may fail, so settling cannot be made to depend on
   * it. Same reason the unmount effect below settles too.
   *
   * `markSignedOut` is what makes the sign-in page say "you have been signed out" instead
   * of appearing for no reason; it returns false for a session that never existed, so a
   * fresh tab is not told it lost something.
   */
  const signOutAndLeave = useCallback(() => {
    if (leaving) return;
    setLeaving(true);
    reset();
    dismissStepUpPrompt();
    markSignedOut("admin");
    // `window.location.assign`, not the router: the session cookie is gone, so every
    // client-side cache in this tree is about to describe a session that no longer
    // exists. A full document load is the same exit `adminIdleTimeoutModal` takes, for
    // the same reason.
    //
    // `.catch()` BEFORE `.finally()`, and the order is the point: `finally` passes a
    // rejection through, so `signOut().finally(leave)` leaves AND raises an unhandled
    // rejection when the logout request fails — which is precisely the case this path
    // exists for, an operator abandoning a console whose network may be the reason they
    // are stuck. The local session state is already cleared by `signOut`'s own `finally`
    // (`lib/authn/realm.ts`), so there is nothing here to report and nothing to retry:
    // the browser must stop believing it holds a session either way.
    void adminAuthn
      .signOut()
      .catch(() => undefined)
      .finally(() => {
        if (typeof window !== "undefined") window.location.assign(ADMIN_SIGN_IN_PATH);
      });
  }, [leaving, reset]);

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

  // Escape does NOT dismiss, and that is the same decision as the missing `X` rather than
  // a separate one: leaving the close button off while Escape still closed it would hide
  // the exit rather than remove it, which is worse than either — the control would look
  // strict and behave loosely, and only a keyboard user would know. The two exits are
  // proving the factor and signing out, which is what an `alertdialog` is for. This
  // matches `adminIdleTimeoutModal`, whose trap takes the same no-op.
  useFocusTrap(panel, prompt !== null, () => {}, "first-tabbable");

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
        </div>

        <div id="step-up-body" className="mt-3 space-y-3 text-sm text-ink-muted">
          <p>
            {/* The server's own words for what is waiting, not a sentence invented here —
                the caller knows which action it is and this panel does not. */}
            {prompt.reason} This needs a second factor proved in the last{" "}
            {REAUTH_WINDOW_MINUTES} minutes.
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

          {/* THE OTHER EXIT, and the only one. Separated from the form by a rule because
              it is not an alternative way to do the thing the operator came for — it is
              leaving. `DANGER`-weight styling would overstate it (signing out is not
              destructive); a secondary button understates it against the primary, which
              is correct: proving the factor is what this panel is for. */}
          <div className="border-t border-line pt-3">
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={leaving}
              onClick={signOutAndLeave}
            >
              <LogOut aria-hidden className="h-4 w-4" />
              {leaving ? "Signing out…" : "Sign out"}
            </button>
            <p className="mt-2 text-xs text-ink-faint">
              If this is not your session, sign out. Nothing you were doing has been
              applied.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
