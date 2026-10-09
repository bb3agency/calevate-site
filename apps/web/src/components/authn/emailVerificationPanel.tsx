"use client";

/**
 * Verify the address on file, with a code emailed to it (D-174).
 *
 * `POST /otp/request` + `POST /otp/verify`, both scoped to the CALLER'S OWN subject —
 * there is no parameter naming whose mailbox to mail, which is what stops this being a way
 * to send mail to arbitrary addresses. So there is no address field on this panel either,
 * and its absence is the feature.
 *
 * The countdown is the resend cooldown and nothing else. **The API does not return the
 * code's expiry**, so a countdown to it would be this browser's guess dressed as a fact;
 * the ten minutes is stated as prose because that is what it is — see D-174 on the
 * `expires_at` the contract is missing.
 */

import { useRef, useState } from "react";

import { useMutation } from "@tanstack/react-query";
import { MailCheck, ShieldCheck } from "lucide-react";

import { AuthProblemNotice } from "@/components/authn/fields";
import { OtpInput } from "@/components/interior/otp-input";
import { NoticeBox, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { RealmAuthn } from "@/lib/authn/realm";
import { OTP_LENGTH, OTP_RESEND_COOLDOWN_MS } from "@/lib/authn/otp";
import { useCountdown } from "@/lib/authn/useCountdown";



export function EmailVerificationPanel({
  authn,
  verified,
  onVerified,
}: {
  authn: RealmAuthn;
  verified: boolean;
  /** Re-read the session, so the panel reflects the server's answer and not this one. */
  onVerified: () => void;
}) {
  const [code, setCode] = useState("");
  const [shakes, setShakes] = useState(0);
  const inFlight = useRef(false);
  const [resendReadyAt, setResendReadyAt] = useState<number | null>(null);
  const cooldown = useCountdown(resendReadyAt);

  const requestCode = useMutation({
    mutationFn: () => authn.requestEmailCode(),
    onSuccess: () => {
      setCode("");
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

  if (verified) {
    return (
      <NoticeBox
        tone="ok"
        icon={<ShieldCheck aria-hidden className="h-4 w-4" />}
        title="Your email address is verified"
      >
        {/* What a person wants at a verified address is what RESTS on it, because that is
            what tells them whether losing the mailbox matters — not "Nothing to do here."
            It is the only address a code is sent to (`POST /otp/request` takes no address;
            it mails this session's own subject, `authn/routes.py`) and the only one a
            password reset link goes to (`POST /password/reset/request`). Both hold on both
            realms, which is why they live here rather than in either page. */}
        <p className="mt-1">
          It is the only address we email a code or a password reset link to, so keep it one
          you can open.
        </p>
      </NoticeBox>
    );
  }

  return (
    <div className="space-y-3 text-sm text-ink-muted">
      <NoticeBox
        tone="warn"
        icon={<MailCheck aria-hidden className="h-4 w-4" />}
        title="Your email address is not verified yet"
      >
        <p className="mt-1">
          We will email a six-digit code to the address on this account. It is good for ten
          minutes, and a new code replaces the previous one.
        </p>
      </NoticeBox>

      {requestCode.isSuccess && (
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
          <AuthProblemNotice error={verify.error} />
          <button
            type="submit"
            className={PRIMARY_BUTTON}
            disabled={verify.isPending || code.length !== OTP_LENGTH}
          >
            {verify.isPending ? "Checking…" : "Verify my address"}
          </button>
        </form>
      )}

      <AuthProblemNotice error={requestCode.error} />

      <button
        type="button"
        className={SECONDARY_BUTTON}
        disabled={requestCode.isPending || cooldown > 0}
        onClick={() => {
          if (requestCode.isPending || cooldown > 0) return;
          requestCode.mutate();
        }}
      >
        {cooldown > 0
          ? `Send another code in ${cooldown}s`
          : requestCode.isSuccess
            ? "Send another code"
            : "Email me a code"}
      </button>
    </div>
  );
}
