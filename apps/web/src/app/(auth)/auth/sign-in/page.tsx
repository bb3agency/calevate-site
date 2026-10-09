"use client";

/**
 * `app.calevate.tech/auth/sign-in` — where a client's staff sign in (D-174).
 *
 * The client realm is not in `MFA_REQUIRED_REALMS`, so `POST /login` answers
 * `authenticated` here and the form never reaches its second step. It is the SAME form as
 * the admin realm's, and it renders one step or two because the SERVER said so.
 *
 * Duplicated page rather than a shared one parameterised by realm: every realm-dependent
 * value here is a literal, and CLAUDE.md's "never share session logic" is the rule that
 * makes that worth the repetition.
 *
 * Where signing in lands is `clientSignedInDestination`: the console page in `?next=`
 * when a signed-out console page sent the person here, otherwise `/c`, the junction that
 * decides where a signed-in person belongs (`app/c/page.tsx`).
 */

import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthCard, AuthHeading, AuthPageFrame } from "@/components/authPage";
import { AuthShowcase } from "@/components/authn/authShowcase";
import { SignInForm } from "@/components/authn/signInForm";
import { SignedOutToast } from "@/components/authn/signedOutToast";
import {
  CLIENT_FORGOT_PATH,
  clientAuthn,
  clientSignedInDestination,
} from "@/lib/authn/clientAuthn";
import { ClientGuestOnly } from "@/lib/authn/clientSession";

export default function ClientSignInPage() {
  return (
    <Providers>
      <AuthPageFrame realmLabel="Client console" aside={<AuthShowcase />}>
        <SignedOutToast realm="client" realmLabel="Calevate" />
        <AuthCard>
          <ClientGuestOnly>
            <SignInForm
              authn={clientAuthn}
              forgotPath={CLIENT_FORGOT_PATH}
              heading={
                <AuthHeading
                  title="Sign in to Calevate"
                  lead="Welcome back. Use the email address your workspace invited."
                />
              }
              onSignedIn={() => {
                // Through `clientConsoleUrl` (inside the destination helper) because this
                // screen is served on three hostnames and the apex refuses `/c/`.
                window.location.assign(clientSignedInDestination());
              }}
              footer={
                <p className="text-sm text-ink-muted">
                  Invited by a colleague? Open the link in their email. It sets your
                  password and adds you to their workspace in one step.
                </p>
              }
            />
          </ClientGuestOnly>
        </AuthCard>
        <p className="mt-6 text-center text-sm text-ink-muted">
          New to Calevate?{" "}
          <Link
            href="/signup"
            className="font-medium text-brand-strong underline underline-offset-2 dark:text-brand-bright"
          >
            Get started
          </Link>
        </p>
      </AuthPageFrame>
    </Providers>
  );
}
