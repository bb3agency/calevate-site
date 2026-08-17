"use client";

/**
 * `/auth/admin/forgot-password` — ask for an operator password-reset link (D-174).
 *
 * One form, one answer, no oracle. See `components/authn/resetRequestForm.tsx`.
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { ResetRequestForm } from "@/components/authn/resetRequestForm";
import { ADMIN_SIGN_IN_PATH, adminAuthn } from "@/lib/authn/adminAuthn";

export default function AdminForgotPasswordPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Operator console">
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Reset your operator password
          </h1>
          <ResetRequestForm authn={adminAuthn} />
          <p className="text-sm text-ink-muted">
            <Link href={ADMIN_SIGN_IN_PATH} className="text-brand-strong underline underline-offset-2">
              Back to sign-in
            </Link>
          </p>
        </div>
      </AuthPageFrame>
    </Providers>
  );
}
