"use client";

/**
 * Sign in: password, then — where the realm demands one — the emailed code (D-174, §5.6).
 *
 * Takes its realm as a prop, and each page passes a literal instance
 * (`adminAuthn` / `clientAuthn`). There is no branch on the realm below and no way for one
 * to be reached from the other's page; see `lib/authn/realm.ts` for the same argument made
 * about the factory, and `apps/api/authn/routes.py::_realm_router` for the server making it
 * first.
 *
 * ## Which step comes next is the SERVER'S answer, not this form's
 *
 * `POST /login` returns `authenticated` or `otp_required`, and this form reads that field
 * and nothing else. It does not know that `MFA_REQUIRED_REALMS` contains the admin realm
 * and not the client one, and it must not: a client that decided for itself which realms
 * need a second factor could be wrong about it in the direction of skipping one.
 *
 * ## The §5.7 defects this form is shaped by
 *
 * **2 — the user-enumeration oracle.** The server answers an unknown address, a wrong
 * password and a deactivated account identically, and this form renders one fixed sentence
 * chosen by problem code with no reference to the address that was typed.
 * `tests/authnScreens.test.tsx` drives two different upstream bodies through it and asserts
 * the DOM is character-identical.
 *
 * **3 — the dev OTP bypass.** No response carries a code, nothing reads `process.env` on
 * this path, and no code is ever auto-filled by us (the platform's own one-time-code
 * autofill is the person's, not ours). `tests/authnSourceGuards.test.ts` keeps it so.
 *
 * **4 — the duplicated countdown.** One `useCountdown`, keyed on an absolute deadline.
 * Resend replaces the deadline rather than starting a second interval.
 *
 * **5 — the password held across the OTP step.** Cleared the instant step one succeeds:
 * `POST /login` sets a session cookie on the `otp_required` branch too, that session can
 * reach exactly one route, and `POST /login/otp/resend` therefore takes no body.
 *
 * ## The code step
 *
 * The code submits itself when the last digit lands, through `submitOnce`, which a ref
 * guards so a paste, an autofill and a quick Enter cannot send the same code twice. A
 * refused code clears the boxes and shakes them, and focus stays in the field for the next
 * try. The resend countdown starts at the server's cooldown and, if the server refuses a
 * resend anyway, restarts from its `Retry-After`.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { OtpInput } from "@/components/interior/otp-input";
import { NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import {
  SIGN_OUT_INCOMPLETE_PARAM,
  SIGN_OUT_INCOMPLETE_VALUE,
} from "@/components/authn/sidebarSignOut";
import { ApiProblem } from "@/lib/api/client";
import { OTP_LENGTH, OTP_RESEND_COOLDOWN_MS } from "@/lib/authn/otp";
import { MAX_PASSWORD_CHARS } from "@/lib/authn/password";
import { AUTHN_CODES, codeOf } from "@/lib/authn/problems";
import type { AuthnSession, RealmAuthn } from "@/lib/authn/realm";
import { useCountdown } from "@/lib/authn/useCountdown";

/** The full-width primary action an auth card ends with. */
const SUBMIT = `${PRIMARY_BUTTON} w-full justify-center py-2.5`;
/** A quiet text action: the resend and the step back. */
const TEXT_ACTION =
  "inline-flex items-center gap-1.5 rounded-md text-sm font-medium text-brand-strong underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:text-ink-muted disabled:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 dark:text-brand-bright touch:min-h-11";

export interface SignInFormProps {
  /** The realm this form signs into. A literal at every call site. */
  authn: RealmAuthn;
  /** Where to go once there is a full session. */
  onSignedIn: (session: AuthnSession | null) => void;
  /** This realm's password-reset page. */
  forgotPath: string;
  /** The screen's heading and lead for the password step. */
  heading: ReactNode;
  /** Extra copy under the form — the invitation hint, the bootstrap hint. */
  footer?: ReactNode;
  /** Other ways in, shown above the email field: the client realm's Google button. */
  alternatives?: ReactNode;
}

/**
 * Did the sidebar's sign-out reach the server, or only this browser?
 *
 * Read from `window.location.search` on mount rather than through `useSearchParams`,
 * which in the App Router forces every page rendering this form into a Suspense boundary.
 */
function useIncompleteSignOut(): boolean {
  const [incomplete, setIncomplete] = useState(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setIncomplete(params.get(SIGN_OUT_INCOMPLETE_PARAM) === SIGN_OUT_INCOMPLETE_VALUE);
  }, []);
  return incomplete;
}

type Step = "credentials" | "code";

export function SignInForm({
  authn,
  onSignedIn,
  forgotPath,
  heading,
  footer,
  alternatives,
}: SignInFormProps) {
  const [step, setStep] = useState<Step>("credentials");
  const signOutIncomplete = useIncompleteSignOut();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [shakes, setShakes] = useState(0);
  const [resent, setResent] = useState(false);
  const [resendReadyAt, setResendReadyAt] = useState<number | null>(null);
  const cooldown = useCountdown(resendReadyAt);
  const codeField = useRef<HTMLInputElement>(null);
  const emailField = useRef<HTMLInputElement>(null);
  const codeInFlight = useRef(false);
  /**
   * A step change unmounts the control that had focus, so focus is put somewhere — but
   * only when the step CHANGES, never on first paint, where stealing focus would scroll a
   * small screen past the heading and interrupt a screen reader mid-page.
   */
  const stepChanged = useRef(false);

  useEffect(() => {
    if (!stepChanged.current) {
      stepChanged.current = true;
      return;
    }
    if (step === "code") codeField.current?.focus();
    else emailField.current?.focus();
  }, [step]);

  const signIn = useMutation({
    mutationFn: () => authn.signIn({ email: email.trim(), password }),
    onSuccess: (status) => {
      // §5.7 defect 5: the password's last use has happened.
      setPassword("");
      if (status === "authenticated") {
        onSignedIn(null);
        return;
      }
      setCode("");
      setResent(false);
      setResendReadyAt(Date.now() + OTP_RESEND_COOLDOWN_MS);
      setStep("code");
    },
  });

  const submitCode = useMutation({
    mutationFn: (value: string) => authn.submitSecondFactor(value),
    onSuccess: (session) => {
      setCode("");
      onSignedIn(session);
    },
    onError: () => {
      // The refused code is gone from the boxes so the next try starts clean; focus never
      // left the field (it is read-only, not disabled, while the check runs).
      setCode("");
      setShakes((n) => n + 1);
      codeInFlight.current = false;
    },
  });

  const submitOnce = useCallback(
    (value: string) => {
      if (codeInFlight.current || value.length !== OTP_LENGTH) return;
      codeInFlight.current = true;
      setResent(false);
      submitCode.mutate(value);
    },
    [submitCode],
  );

  const resend = useMutation({
    // No arguments. The live session is the challenge — see the file docstring.
    mutationFn: () => authn.resendSecondFactor(),
    onSuccess: () => {
      setCode("");
      setResent(true);
      setResendReadyAt(Date.now() + OTP_RESEND_COOLDOWN_MS);
      // The previous refusal is about a code that no longer exists; left on screen it
      // reads as the resend having failed.
      submitCode.reset();
      codeField.current?.focus();
    },
    onError: (error) => {
      // The server's own clock wins: a refusal inside its cooldown says how long is left.
      if (
        codeOf(error) === AUTHN_CODES.resendTooSoon &&
        error instanceof ApiProblem &&
        error.retryAfterSeconds !== undefined
      ) {
        setResendReadyAt(Date.now() + error.retryAfterSeconds * 1000);
      }
    },
  });

  const startOver = useCallback(() => {
    // Ends the half-authenticated session rather than merely hiding it.
    void authn.signOut().catch(() => {
      // A failed sign-out must not trap the person on this step; the server-side session
      // expires on its own bound.
    });
    setStep("credentials");
    setPassword("");
    setCode("");
    setResent(false);
    setResendReadyAt(null);
    codeInFlight.current = false;
    signIn.reset();
    submitCode.reset();
    resend.reset();
  }, [authn, signIn, submitCode, resend]);

  const onCredentials = (event: FormEvent) => {
    event.preventDefault();
    // Single flight: Enter in a text field submits the form, and a second Enter before
    // React re-renders would otherwise dispatch a second sign-in.
    if (signIn.isPending) return;
    signIn.mutate();
  };

  const onCode = (event: FormEvent) => {
    event.preventDefault();
    submitOnce(code);
  };

  if (step === "code") {
    const checking = submitCode.isPending;
    const refused = submitCode.isError && code === "";
    return (
      <form className="space-y-5" onSubmit={onCode} noValidate>
        <div className="space-y-1.5">
          <h1 className="text-balance text-2xl font-semibold tracking-tight text-ink">
            Check your email
          </h1>
          {/* The address is NOT printed back, so a shoulder-surfed screenshot of this step
              does not pair an address with the fact that it signs in here. */}
          <p className="text-sm text-ink-muted">
            We sent a {OTP_LENGTH}-digit code to the email address on this account. It
            works for 10 minutes.
          </p>
        </div>

        <OtpInput
          label="Six-digit code"
          length={OTP_LENGTH}
          value={code}
          onChange={(next) => {
            setCode(next);
            setResent(false);
          }}
          onComplete={submitOnce}
          status={refused ? "error" : "idle"}
          shakeKey={shakes}
          readOnly={checking}
          inputRef={codeField}
        />

        <AuthProblemNotice error={submitCode.error ?? resend.error} />

        {/* Announced politely: the person asked for this and is not interrupted by it. */}
        <p role="status" className="min-h-5 text-sm text-ink-muted">
          {checking ? "Checking the code…" : resent ? "A new code is on its way. It replaces the last one." : ""}
        </p>

        <button
          type="submit"
          className={SUBMIT}
          disabled={checking || code.length !== OTP_LENGTH}
        >
          Finish signing in
        </button>

        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <button
            type="button"
            className={TEXT_ACTION}
            disabled={resend.isPending || cooldown > 0}
            onClick={() => {
              if (resend.isPending || cooldown > 0) return;
              resend.mutate();
            }}
          >
            {cooldown > 0 ? (
              <>
                Send a new code in <span className="tabular-nums">{cooldown}s</span>
              </>
            ) : resend.isPending ? (
              "Sending…"
            ) : (
              "Send a new code"
            )}
          </button>
          <button type="button" className={TEXT_ACTION} onClick={startOver}>
            <ArrowLeft aria-hidden className="h-4 w-4" />
            Use a different email address
          </button>
        </div>
      </form>
    );
  }

  return (
    <form className="space-y-5" onSubmit={onCredentials} noValidate>
      {heading}
      {alternatives}
      <AuthField
        label="Email address"
        type="email"
        name="email"
        autoComplete="username"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="next"
        inputRef={emailField}
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <div>
        <AuthField
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          enterKeyHint="go"
          // The maximum only. NOT the minimum: an account whose password predates the
          // current floor still signs in, and refusing to SUBMIT it would lock out the
          // one person who cannot fix it from this screen.
          maxLength={MAX_PASSWORD_CHARS}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {/* Under the field rather than beside its label, so the tab order runs email,
            password, Sign in without a detour. */}
        <div className="mt-1.5 flex justify-end">
          <Link href={forgotPath} className={TEXT_ACTION}>
            Forgot your password?
          </Link>
        </div>
      </div>

      {signOutIncomplete && (
        <NoticeBox tone="warn" title="Signed out on this device only">
          <p className="mt-1">
            Calevate could not be reached to end the session everywhere else, so it may
            still be open on another device until it times out. Sign in and use
            &ldquo;Sign out everywhere&rdquo; on your account page to end it now.
          </p>
        </NoticeBox>
      )}

      <AuthProblemNotice error={signIn.error} />

      <button
        type="submit"
        className={SUBMIT}
        disabled={signIn.isPending || email.trim() === "" || password === ""}
      >
        {signIn.isPending ? "Signing in…" : "Sign in"}
      </button>

      {footer}
    </form>
  );
}
