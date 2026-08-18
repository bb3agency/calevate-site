"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";

import { NoticeBox, ProblemNotice } from "@/components/ui";
import { requestStepUp, verifyStepUp } from "@/lib/authn/adminAuthn";
import { AUTHN_CODES, codeOf, signInMessage } from "@/lib/authn/problems";

/**
 * The browser half of step-up re-authentication — the prompt D-178 assumed and D-340 built.
 *
 * ═══ WHAT WAS MISSING ═══
 *
 * `apps/api/core/stepup.py` refuses a dangerous admin mutation whose session has not proved
 * a second factor in the last five minutes, with `403 reauthentication_required`, and its
 * `remediation` names the two calls that clear it:
 *
 *     POST /v1/auth/admin/step-up to have a code emailed, POST the code to
 *     /v1/auth/admin/step-up/verify, then repeat this request with X-Confirm-Action: …
 *
 * `apps/api/authn/stepup.py` says in as many words why it prints that: "an operator
 * mid-incident must not have to find the source — or the frontend — to learn how to get
 * past this". It is the right sentence **for an operator reading a log**. On a screen with
 * a button it is a console telling somebody to go and write curl, which is the failure
 * `lib/authn/problems.ts` had already anticipated in prose ("NOT the server's `detail`,
 * which prints the two curl calls that clear it … wrong on a screen where the button is
 * what does it") — and then nothing rendered that copy, because no surface outside sign-in
 * ever called `signInMessage`. Twelve confirmed writes across six admin screens reached
 * this refusal and every one of them printed the curl.
 *
 * So the copy that was already authored is what this renders, and the two calls it names
 * are two controls instead of two shell commands.
 *
 * ═══ WHY IT DOES NOT REPLAY THE ACTION ITSELF ═══
 *
 * The obvious shape — hold the refused request and re-send it once the factor is fresh —
 * is rejected. A dangerous mutation that a component can re-issue from memory, seconds
 * later, after an interstitial the operator was not expecting, is a second irreversible
 * write nobody pressed a button for; the credit adjustment and the tenant erasure are both
 * on this list. `onRetry` is therefore OPTIONAL and is wired by the caller only where
 * re-sending is the same request the operator already confirmed — and where it is absent,
 * the prompt says to press the control again, which puts the decision back where the
 * confirmation string put it.
 *
 * ═══ THE THREE STATES, AND WHAT EACH ONE MAY NOT DO ═══
 *
 * `idle` → `sent` → done. The transition to `sent` happens only on a successful 202, so a
 * mail that failed to leave does not put an operator in front of a code field that can
 * never be satisfied. A failed VERIFY stays in `sent` with the refusal beside the field:
 * `invalid_second_factor` is a typo, not a dead session (`isSessionGone` deliberately
 * excludes it), and dropping back to `idle` would retire the code they are holding.
 */
export function StepUpPrompt({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [cleared, setCleared] = useState(false);
  /**
   * The refusal from the step-up exchange ITSELF, kept apart from the `error` prop.
   *
   * They are two different failures with two different remedies — "this action needs a
   * fresh factor" and "that code did not match" — and rendering the second where the first
   * lives would replace the reason the operator is here with the reason their last
   * keystroke failed.
   */
  const [exchangeError, setExchangeError] = useState<unknown>(null);

  if (codeOf(error) !== AUTHN_CODES.reauthenticationRequired) return null;

  async function send() {
    setBusy(true);
    setExchangeError(null);
    try {
      await requestStepUp();
      setSent(true);
    } catch (failure) {
      // Stay in `idle`. See the docstring: a code field nobody can satisfy is worse than
      // the button that failed to produce one.
      setExchangeError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setExchangeError(null);
    try {
      await verifyStepUp(code);
      // The code is spent and the session is rotated; holding either would be a value that
      // can only now be wrong.
      setCode("");
      setCleared(true);
    } catch (failure) {
      setExchangeError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    // `role="alert"`: this interrupts an operator mid-task, exactly as `ProblemNotice` and
    // `WriteFailure` do for the failures they render.
    <div role="alert">
      <NoticeBox
        tone="warn"
        icon={<KeyRound aria-hidden className="h-5 w-5" />}
        title="Confirm it is still you"
      >
        {/* The sentence is `SIGN_IN_COPY`'s, not the server's `detail`. Its first job is to
            stop this being read as a logout and the action being abandoned. */}
        <p className="mt-1">{signInMessage(error)}</p>
        {cleared ? (
          <div className="mt-3">
            <p className="font-medium">Confirmed. Nothing was changed by the refused attempt.</p>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="mt-2 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white dark:bg-slate-100 dark:text-slate-900"
              >
                Try that action again
              </button>
            ) : (
              <p className="mt-1">Press the control again to send the action.</p>
            )}
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {!sent ? (
              <button
                type="button"
                onClick={() => void send()}
                disabled={busy}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
              >
                {busy ? "Sending…" : "Email me a code"}
              </button>
            ) : (
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs font-medium">
                  <span className="block">Code from your email</span>
                  <input
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    // `one-time-code` is what a password manager and iOS/Android SMS
                    // autofill look for; `inputMode` keeps a phone on the numeric pad.
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    className="mt-1 w-40 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-sm dark:border-slate-600 dark:bg-slate-950"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void confirm()}
                  disabled={busy || code.trim() === ""}
                  className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
                >
                  {busy ? "Confirming…" : "Confirm"}
                </button>
                <button
                  type="button"
                  onClick={() => void send()}
                  disabled={busy}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium disabled:opacity-50 dark:border-slate-600"
                >
                  Send a new code
                </button>
              </div>
            )}
          </div>
        )}
        {/* The exchange's own refusal, below the controls it belongs to. `ProblemNotice`
            renders the API's sentence — `invalid_second_factor` already says "check the
            most recent email, or ask for a new code", which is the action beside it. */}
        {exchangeError != null && (
          <div className="mt-2">
            <ProblemNotice error={exchangeError} />
          </div>
        )}
      </NoticeBox>
    </div>
  );
}
