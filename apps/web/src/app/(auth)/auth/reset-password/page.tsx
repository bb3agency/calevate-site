"use client";

/**
 * `/auth/reset-password?token=…` — spend a client-realm reset link (D-174).
 *
 * The client twin of the operator page; see it for why the token is stripped from the URL
 * and why the idempotency key is derived from the token.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { MissingLinkCode, SetPasswordForm } from "@/components/authn/setPasswordForm";
import { Card, NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import { CLIENT_FORGOT_PATH, CLIENT_SIGN_IN_PATH, clientAuthn } from "@/lib/authn/clientAuthn";
import { useIdempotencyKey } from "@/lib/authn/useIdempotencyKey";
import { useLinkToken } from "@/lib/authn/useLinkToken";

export default function ClientResetPasswordPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Choose a new password
          </h1>
          <ClientResetBody />
        </div>
      </AuthPageFrame>
    </Providers>
  );
}

function ClientResetBody() {
  const { token } = useLinkToken();
  const idempotencyKey = useIdempotencyKey(`reset-confirm:client:${token}`);

  return (
    <SetPasswordForm
      submitLabel="Set my new password"
      intro={
        <p>
          This link works once and expires an hour after it was sent. Setting a password
          here also signs you out everywhere else, on every device.
        </p>
      }
      onSubmit={({ token: linkToken, password }) =>
        clientAuthn.confirmPasswordReset({ token: linkToken, password }, idempotencyKey)
      }
      renderSuccess={() => (
        <Card>
          <div className="space-y-3 text-sm text-ink-muted">
            <NoticeBox tone="ok" title="Your password has been changed">
              <p className="mt-1">
                Every session on this account has been ended. Sign in again with the new
                password.
              </p>
            </NoticeBox>
            <Link href={CLIENT_SIGN_IN_PATH} className={PRIMARY_BUTTON}>
              Go to sign-in
            </Link>
          </div>
        </Card>
      )}
      renderMissingToken={
        <MissingLinkCode
          what="reset"
          remedy={`If that does not work, ask for a fresh link from ${CLIENT_FORGOT_PATH}.`}
        />
      }
    />
  );
}
