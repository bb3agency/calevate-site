"use client";

/**
 * `/auth/admin/forgot-password` — ask for an operator password-reset link (D-174).
 *
 * One form, one answer, no oracle. See `components/authn/resetRequestForm.tsx`.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthCard, AuthHeading, AuthPageFrame } from "@/components/authPage";
import { ResetRequestForm } from "@/components/authn/resetRequestForm";
import { ADMIN_SIGN_IN_PATH, adminAuthn } from "@/lib/authn/adminAuthn";

export default function AdminForgotPasswordPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Operator console">
        <AuthCard>
          <AuthHeading title="Reset your operator password" />
          <ResetRequestForm authn={adminAuthn} />
        </AuthCard>
        <p className="mt-6 text-center text-sm text-ink-muted">
          <Link href={ADMIN_SIGN_IN_PATH} className="inline-flex items-center text-brand-strong underline underline-offset-2 touch:min-h-11 dark:text-brand-bright">
            Back to sign-in
          </Link>
        </p>
      </AuthPageFrame>
    </Providers>
  );
}
