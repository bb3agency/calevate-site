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
 * need a second factor is a client that can be wrong about it, and the direction it would
 * be wrong in is skipping one. The server owns the verdict, the form renders it.
 *
 * ## The four §5.7 defects this form is shaped by
 *
 * **2 — the user-enumeration oracle.** Theirs distinguishes a known admin with a wrong
 * password (401 `INVALID_CREDENTIALS`), a deactivated admin (401 `UNAUTHORISED`) and an
 * unknown address (a 200 with a generic message), and renders three different sentences.
 * Ours cannot: the server answers all three with one status, one body and — via
 * `verify_password_blocking` against a dummy hash — one wall-clock cost, and this form
 * renders one fixed sentence chosen by problem code with no reference to the address that
 * was typed. `tests/authnScreens.test.tsx` drives two different upstream bodies
 * through it and asserts the DOM is character-identical.
 *
 * **3 — the dev OTP bypass.** There is no `devOtp` field on any response here, nothing
 * reads `process.env` on this path, and no code is ever auto-filled. A credential in a
 * response body is not made safe by an environment variable, and the guard test
 * `tests/authnSourceGuards.test.ts` reads this directory's source to keep it that way.
 *
 * **4 — the duplicated countdown.** One `useCountdown`, keyed on an absolute deadline,
 * cleaned up by its own effect. Pressing resend replaces the deadline rather than starting
 * a second interval, so the cooldown cannot tick at double speed and nothing survives
 * unmount.
 *
 * **5 — the password held across the OTP step.** Theirs keeps it in form state for the
 * whole OTP window so that "resend" can re-post it. **Ours clears it the instant step one
 * succeeds**, and can, because the backend already issues the short-lived challenge §5.7
 * asks for: `POST /login` sets a session cookie on the `otp_required` branch too, that
 * session can reach exactly one route, and `POST /login/otp/resend` therefore takes NO
 * BODY. The challenge is the cookie. Nothing about the password needs to survive.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, KeyRound, LogIn, Mail } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { Card, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import { MAX_PASSWORD_CHARS } from "@/lib/authn/password";
import type { AuthnSession, RealmAuthn } from "@/lib/authn/realm";
import { useCountdown } from "@/lib/authn/useCountdown";

/**
 * How long before a fresh code can be asked for.
 *
 * Sixty seconds, the reference's number and the ordinary one for an emailed code. It is a
 * COURTESY bound, not a security control — the security control is server-side
 * (`OTP_BUDGET`: five failures in ten minutes, and a new code retires the previous one so
 * resending cannot accumulate parallel codes). Saying that here matters because a
 * client-side cooldown that looked like the real limit would invite somebody to relax it.
 */
const RESEND_COOLDOWN_MS = 60_000;

export interface SignInFormProps {
  /** The realm this form signs into. A literal at every call site. */
  authn: RealmAuthn;
  /** Where to go once there is a full session. */
  onSignedIn: (session: AuthnSession | null) => void;
  /** This realm's password-reset page. */
  forgotPath: string;
  /** Extra copy under the form — the invitation hint, the bootstrap hint. */
  footer?: React.ReactNode;
}

type Step = "credentials" | "code";

export function SignInForm({ authn, onSignedIn, forgotPath, footer }: SignInFormProps) {
  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [resendReadyAt, setResendReadyAt] = useState<number | null>(null);
  const cooldown = useCountdown(resendReadyAt);
  const codeField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step === "code") codeField.current?.focus();
  }, [step]);

  const signIn = useMutation({
    mutationFn: () => authn.signIn({ email: email.trim(), password }),
    onSuccess: (status) => {
      if (status === "authenticated") {
        setPassword("");
        onSignedIn(null);
        return;
      }
      // §5.7 defect 5: the password's last use has happened. Cleared here, not on
      // unmount, not on success of the second step.
      setPassword("");
      setCode("");
      setResendReadyAt(Date.now() + RESEND_COOLDOWN_MS);
      setStep("code");
    },
  });

  const submitCode = useMutation({
    mutationFn: () => authn.submitSecondFactor(code.trim()),
    onSuccess: (session) => {
      setCode("");
      onSignedIn(session);
    },
  });

  const resend = useMutation({
    // No arguments. The live session is the challenge — see the file docstring.
    mutationFn: () => authn.resendSecondFactor(),
    onSuccess: () => {
      setCode("");
      setResendReadyAt(Date.now() + RESEND_COOLDOWN_MS);
    },
  });

  const startOver = useCallback(() => {
    // Ends the half-authenticated session rather than merely hiding it. A `live` session
    // that has not answered its code is still a session, and leaving one behind because
    // somebody pressed "use a different address" is a credential nobody is watching.
    void authn.signOut().catch(() => {
      // A failed sign-out must not trap the person on this step; the local reset below is
      // what the screen needs, and the server-side session expires on its own bound.
    });
    setStep("credentials");
    setPassword("");
    setCode("");
    setResendReadyAt(null);
    signIn.reset();
    submitCode.reset();
    resend.reset();
  }, [authn, signIn, submitCode, resend]);

  const onCredentials = (event: FormEvent) => {
    event.preventDefault();
    // The single-flight submit guard. `disabled` on the button is not enough on its own:
    // Enter in a text field submits the form, and a second Enter before React re-renders
    // would dispatch a second sign-in.
    if (signIn.isPending) return;
    signIn.mutate();
  };

  const onCode = (event: FormEvent) => {
    event.preventDefault();
    if (submitCode.isPending) return;
    submitCode.mutate();
  };

  if (step === "code") {
    return (
      <Card>
        <form className="space-y-4" onSubmit={onCode} noValidate>
          <div className="space-y-1">
            <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
              <Mail aria-hidden className="h-4 w-4" />
              Enter the code we emailed
            </h2>
            {/* The address is NOT printed back. It is on screen nowhere in this step,
                which keeps a shoulder-surfed screenshot from carrying an operator's
                address alongside the fact that it is an operator's address. */}
            <p className="text-sm text-ink-muted">
              Your password was accepted. We have sent a six-digit code to the address on
              file for this account. It is good for ten minutes.
            </p>
          </div>

          <AuthField
            label="Six-digit code"
            inputMode="numeric"
            autoComplete="one-time-code"
            // Focus moves here because the STEP changed and the control that had it has
            // unmounted; without this, focus falls to `<body>` and a keyboard or
            // screen-reader user is dropped at the top of a page that just changed under
            // them. `tests/a11y.ts` names focus order as a barrier axe cannot see.
            inputRef={codeField}
            maxLength={16}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />

          <AuthProblemNotice error={submitCode.error ?? resend.error} />

          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              className={PRIMARY_BUTTON}
              disabled={submitCode.isPending || code.trim().length === 0}
            >
              <KeyRound aria-hidden className="h-4 w-4" />
              {submitCode.isPending ? "Checking…" : "Finish signing in"}
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={resend.isPending || cooldown > 0}
              onClick={() => {
                if (resend.isPending || cooldown > 0) return;
                resend.mutate();
              }}
            >
              {cooldown > 0 ? `Send a new code in ${cooldown}s` : "Send a new code"}
            </button>
          </div>

          <p className="text-xs text-ink-faint">
            A new code replaces the previous one, so use the most recent email.
          </p>

          <button type="button" className={SECONDARY_BUTTON} onClick={startOver}>
            <ArrowLeft aria-hidden className="h-4 w-4" />
            Use a different email address
          </button>
        </form>
      </Card>
    );
  }

  return (
    <Card>
      <form className="space-y-4" onSubmit={onCredentials} noValidate>
        <AuthField
          label="Email address"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <AuthField
          label="Password"
          type="password"
          autoComplete="current-password"
          // The maximum only. NOT the 12-character minimum, deliberately: an account
          // whose password predates that floor still exists and still signs in
          // (`tests/authn_password_test.py` has the case), and a client that refused to
          // SUBMIT it would lock out the one person who cannot fix it from this screen.
          // The floor belongs on the forms that SET a password, and it is on all three.
          maxLength={MAX_PASSWORD_CHARS}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <AuthProblemNotice error={signIn.error} />

        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={signIn.isPending || email.trim() === "" || password === ""}
        >
          <LogIn aria-hidden className="h-4 w-4" />
          {signIn.isPending ? "Signing in…" : "Sign in"}
        </button>

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Link href={forgotPath} className="text-brand-strong underline underline-offset-2">
            I have forgotten my password
          </Link>
        </div>

        {footer}
      </form>
    </Card>
  );
}
