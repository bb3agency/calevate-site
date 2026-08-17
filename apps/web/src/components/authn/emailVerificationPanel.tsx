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

import { useState } from "react";

import { useMutation } from "@tanstack/react-query";
import { MailCheck, ShieldCheck } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { NoticeBox, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import type { RealmAuthn } from "@/lib/authn/realm";
import { useCountdown } from "@/lib/authn/useCountdown";

const RESEND_COOLDOWN_MS = 60_000;

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
  const [resendReadyAt, setResendReadyAt] = useState<number | null>(null);
  const cooldown = useCountdown(resendReadyAt);

  const requestCode = useMutation({
    mutationFn: () => authn.requestEmailCode(),
    onSuccess: () => {
      setCode("");
      setResendReadyAt(Date.now() + RESEND_COOLDOWN_MS);
    },
  });

  const verify = useMutation({
    mutationFn: () => authn.verifyEmailCode(code.trim()),
    onSuccess: () => {
      setCode("");
      setResendReadyAt(null);
      onVerified();
    },
  });

  if (verified) {
    return (
      <NoticeBox
        tone="ok"
        icon={<ShieldCheck aria-hidden className="h-4 w-4" />}
        title="Your email address is verified"
      >
        <p className="mt-1">Nothing to do here.</p>
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
            if (verify.isPending) return;
            verify.mutate();
          }}
        >
          <AuthField
            label="Six-digit code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={16}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <AuthProblemNotice error={verify.error} />
          <button
            type="submit"
            className={PRIMARY_BUTTON}
            disabled={verify.isPending || code.trim() === ""}
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
