"use client";

/**
 * `/auth/forgot-password` — ask for a client-realm password-reset link (D-174).
 *
 * The client twin of the operator page. Separate file, separate realm literal — see
 * `lib/authn/clientSession.tsx` on why the duplication is the point.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { ResetRequestForm } from "@/components/authn/resetRequestForm";
import { CLIENT_SIGN_IN_PATH, clientAuthn } from "@/lib/authn/clientAuthn";

export default function ClientForgotPasswordPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console">
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Reset your password
          </h1>
          <ResetRequestForm authn={clientAuthn} />
          <p className="text-sm text-ink-muted">
            <Link href={CLIENT_SIGN_IN_PATH} className="text-brand-strong underline underline-offset-2">
              Back to sign-in
            </Link>
          </p>
        </div>
      </AuthPageFrame>
    </Providers>
  );
}
