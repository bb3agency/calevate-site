"use client";

/**
 * Create a Calevate account without an invitation (D-703): "Continue with Google", or an
 * email address proved by a six-digit code and then a password.
 *
 * The server answers "code sent" the same way whether or not the address already has an
 * account (it mails that owner a way in instead), so this form always moves on to the code
 * step and never says which. On success the session cookie is set and `onCreated` runs;
 * the signup page then asks for the business.
 */

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { GoogleSignIn } from "@/components/authn/googleSignIn";
import { OtpInput } from "@/components/interior/otp-input";
import { completeEmailSignup, startEmailSignup } from "@/lib/authn/clientAuthn";
import { MAX_PASSWORD_CHARS, passwordProblem, passwordRule } from "@/lib/authn/password";
import { useCountdown } from "@/lib/authn/useCountdown";

const OTP_LENGTH = 6;
const RESEND_COOLDOWN_MS = 60_000;
/** On top of `ActionButton`'s primary look. */
const SUBMIT = "w-full py-2.5";
const TEXT_ACTION =
  "inline-flex items-center gap-1.5 rounded-md text-sm font-medium text-brand-strong underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:text-ink-muted disabled:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 dark:text-brand-bright touch:min-h-11";

export function CreateAccountForm({ onCreated }: { onCreated: () => void }) {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [resendReadyAt, setResendReadyAt] = useState<number | null>(null);
  const [resent, setResent] = useState(false);
  const cooldown = useCountdown(resendReadyAt);
  const firstField = useRef<HTMLInputElement>(null);
  const moved = useRef(false);

  const start = useMutation({
    mutationFn: () => startEmailSignup(email.trim()),
    onSuccess: () => {
      setResendReadyAt(Date.now() + RESEND_COOLDOWN_MS);
      setStep("code");
    },
  });
  const resend = useMutation({
    mutationFn: () => startEmailSignup(email.trim()),
    onSuccess: () => {
      setResendReadyAt(Date.now() + RESEND_COOLDOWN_MS);
      setResent(true);
      setCode("");
    },
  });
  const finish = useMutation({
    mutationFn: () =>
      completeEmailSignup({
        email: email.trim(),
        code,
        password,
        name: name.trim() || undefined,
      }),
    onSuccess: onCreated,
  });
  // Every refusal is `AuthProblemNotice`'s generic sentence beside the form, never a toast
  // carrying the server's words: those must not say whether an address has an account.
  const startFeedback = useActionFeedback(start, { errorDisplay: "inline" });
  const resendFeedback = useActionFeedback(resend, { errorDisplay: "inline" });
  const finishFeedback = useActionFeedback(finish, { errorDisplay: "inline" });

  // Focus follows a step change (never first paint), so the next field is where you type.
  useEffect(() => {
    if (!moved.current) {
      moved.current = true;
      return;
    }
    firstField.current?.focus();
  }, [step]);

  const onEmail = (event: FormEvent) => {
    event.preventDefault();
    if (start.isPending || email.trim() === "") return;
    startFeedback.run();
  };
  const onFinish = (event: FormEvent) => {
    event.preventDefault();
    if (finish.isPending || code.length !== OTP_LENGTH || passwordProblem(password, "client")) {
      return;
    }
    finishFeedback.run();
  };

  if (step === "email") {
    return (
      <form className="space-y-5" onSubmit={onEmail} noValidate>
        <div className="space-y-1.5">
          <h1 className="text-balance text-2xl font-semibold tracking-tight text-ink">
            Create your Calevate account
          </h1>
          <p className="text-sm text-ink-muted">
            Your free trial starts as soon as you tell us about your business.
          </p>
        </div>
        <GoogleSignIn />
        <AuthField
          label="Work email"
          type="email"
          name="email"
          autoComplete="email"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <AuthProblemNotice error={start.error} />
        <ActionButton
          type="submit"
          className={SUBMIT}
          status={startFeedback.status}
          pendingLabel="Sending a code…"
          disabled={email.trim() === ""}
        >
          Email me a code
        </ActionButton>
      </form>
    );
  }

  return (
    <form className="space-y-5" onSubmit={onFinish} noValidate>
      <div className="space-y-1.5">
        <h1 className="text-balance text-2xl font-semibold tracking-tight text-ink">
          Check your email
        </h1>
        <p className="text-sm text-ink-muted">
          If this address can be used for a new account, a {OTP_LENGTH}-digit code is on its
          way. It works for 10 minutes. Already have an account? We have emailed you a way to
          sign in instead.
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
        status={finish.isError && code === "" ? "error" : "idle"}
        readOnly={finish.isPending}
        inputRef={firstField}
      />
      <AuthField
        label="Your name"
        name="name"
        autoComplete="name"
        maxLength={120}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <AuthField
        label="Choose a password"
        type="password"
        name="new-password"
        autoComplete="new-password"
        reveals="password"
        maxLength={MAX_PASSWORD_CHARS}
        hint={passwordRule("client")}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <AuthProblemNotice error={finish.error ?? resend.error} />
      <p role="status" className="min-h-5 text-sm text-ink-muted">
        {finish.isPending
          ? "Creating your account…"
          : resent
            ? "A new code is on its way. It replaces the last one."
            : ""}
      </p>
      <ActionButton
        type="submit"
        className={SUBMIT}
        status={finishFeedback.status}
        pendingLabel="Creating your account…"
        disabled={code.length !== OTP_LENGTH || passwordProblem(password, "client") !== null}
      >
        Create my account
      </ActionButton>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <button
          type="button"
          className={TEXT_ACTION}
          disabled={resend.isPending || cooldown > 0}
          onClick={() => {
            if (!resend.isPending && cooldown === 0) resendFeedback.run();
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
        <button
          type="button"
          className={TEXT_ACTION}
          onClick={() => {
            setStep("email");
            setCode("");
            setPassword("");
          }}
        >
          <ArrowLeft aria-hidden className="h-4 w-4" />
          Use a different email address
        </button>
      </div>
    </form>
  );
}
