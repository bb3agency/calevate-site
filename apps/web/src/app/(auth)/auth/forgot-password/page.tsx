"use client";

/**
 * `/auth/forgot-password` — ask for a client-realm password-reset link (D-174).
 *
 * The client twin of the operator page. Separate file, separate realm literal — see
 * `lib/authn/clientSession.tsx` on why the duplication is the point.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthCard, AuthHeading, AuthPageFrame } from "@/components/authPage";
import { ResetRequestForm } from "@/components/authn/resetRequestForm";
import { CLIENT_SIGN_IN_PATH, clientAuthn } from "@/lib/authn/clientAuthn";

export default function ClientForgotPasswordPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        <AuthCard>
          <AuthHeading title="Reset your password" />
          <ResetRequestForm authn={clientAuthn} />
        </AuthCard>
        <p className="mt-6 text-center text-sm text-ink-muted">
          <Link href={CLIENT_SIGN_IN_PATH} className="inline-flex items-center text-brand-strong underline underline-offset-2 touch:min-h-11 dark:text-brand-bright">
            Back to sign-in
          </Link>
        </p>
      </AuthPageFrame>
    </Providers>
  );
}
