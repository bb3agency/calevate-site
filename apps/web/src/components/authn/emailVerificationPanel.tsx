"use client";

/**
 * Verify the address on file, with a code emailed to it (D-174). Rendered under an account
 * page's Email address row once the person chooses "Verify"; the row already says the
 * address is not verified, so this panel does not say it again.
 *
 * `POST /otp/request` + `POST /otp/verify`, both scoped to the CALLER'S OWN subject: there
 * is no parameter naming whose mailbox to mail, which is what stops this being a way to
 * send mail to arbitrary addresses. So there is no address field here either.
 *
 * The countdown is the resend cooldown and nothing else. The API does not return the
 * code's expiry, so the ten minutes is stated as prose rather than counted down (D-174).
 */

import { useRef, useState } from "react";

import { useMutation } from "@tanstack/react-query";

import { AuthProblemNotice } from "@/components/authn/fields";
import { TEXT_ACTION } from "@/components/console/section";
import { OtpInput } from "@/components/interior/otp-input";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { RealmAuthn } from "@/lib/authn/realm";
import { OTP_LENGTH, OTP_RESEND_COOLDOWN_MS } from "@/lib/authn/otp";
import { useCountdown } from "@/lib/authn/useCountdown";

export function EmailVerificationPanel({
  authn,
  onVerified,
}: {
  authn: RealmAuthn;
  /** Re-read the session, so the page reflects the server's answer and not this one. */
  onVerified: () => void;
}) {
  const [code, setCode] = useState("");
  const [shakes, setShakes] = useState(0);
  const inFlight = useRef(false);
  const [resendReadyAt, setResendReadyAt] = useState<number | null>(null);
  /** State, not `requestCode.isSuccess`: a resend in flight must not fold the code field away. */
  const [sent, setSent] = useState(false);
  const cooldown = useCountdown(resendReadyAt);

  const requestCode = useMutation({
    mutationFn: () => authn.requestEmailCode(),
    onSuccess: () => {
      setCode("");
      setSent(true);
      setResendReadyAt(Date.now() + OTP_RESEND_COOLDOWN_MS);
    },
  });

  const verify = useMutation({
    mutationFn: (value: string) => authn.verifyEmailCode(value),
    onSuccess: () => {
      setCode("");
      setResendReadyAt(null);
      onVerified();
    },
    onError: () => {
      setCode("");
      setShakes((n) => n + 1);
      inFlight.current = false;
    },
  });

  // One submission per code: the last digit submits it, and a paste, an autofill and an
  // Enter landing together must not send it twice.
  const submitOnce = (value: string) => {
    if (inFlight.current || value.length !== OTP_LENGTH) return;
    inFlight.current = true;
    verify.mutate(value);
  };

  const resend = () => {
    if (requestCode.isPending || cooldown > 0) return;
    requestCode.mutate();
  };

  if (!sent) {
    return (
      <div className="space-y-3">
        <p className="text-meta text-ink-muted">
          We email a six-digit code to this address. It works for ten minutes.
        </p>
        <AuthProblemNotice error={requestCode.error} />
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={requestCode.isPending}
          onClick={resend}
        >
          {requestCode.isPending ? "Sending…" : "Email me a code"}
        </button>
      </div>
    );
  }

  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submitOnce(code);
      }}
    >
      <OtpInput
        label="Six-digit code"
        length={OTP_LENGTH}
        value={code}
        onChange={setCode}
        onComplete={submitOnce}
        status={verify.isError && code === "" ? "error" : "idle"}
        shakeKey={shakes}
        readOnly={verify.isPending}
      />
      <AuthProblemNotice error={verify.error ?? requestCode.error} />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={verify.isPending || code.length !== OTP_LENGTH}
        >
          {verify.isPending ? "Checking…" : "Verify"}
        </button>
        <button
          type="button"
          className={TEXT_ACTION}
          disabled={requestCode.isPending || cooldown > 0}
          onClick={resend}
        >
          {cooldown > 0 ? `Send another code in ${cooldown}s` : "Send another code"}
        </button>
      </div>
    </form>
  );
}
